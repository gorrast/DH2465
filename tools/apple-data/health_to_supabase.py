#!/usr/bin/env python3
"""Stream Apple Health export.xml into Supabase source_records (Python 3.10+)."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from apple_contract import CANONICAL_HEALTH

from supabase_export_common import (Bundle, add_arguments, date_bounds, iso_utc, numeric, parse_time,
                                    print_result, source_record, stable_id)

SOURCE = 'apple_health'
SUPPORTED = {'Record', 'Workout', 'ActivitySummary', 'Correlation', 'Audiogram',
             'ClinicalRecord', 'VisionPrescription'}


class SafeXML:
    """Allow Apple's internal element DTD, but refuse custom entity declarations."""
    def __init__(self, stream):
        self.stream, self.tail = stream, b''

    def read(self, size=-1):
        data = self.stream.read(size)
        check = self.tail + data
        if b'<!ENTITY' in check.upper():
            raise ValueError('XML entity declarations are not supported')
        if b'\x00' in data:
            raise ValueError('expected a UTF-8 Apple Health XML file')
        self.tail = check[-32:]
        return data


def tree_data(element):
    result = dict(tag=element.tag, attributes=dict(element.attrib))
    if element.text and element.text.strip():
        result['text'] = element.text.strip()
    if len(element):
        result['children'] = [tree_data(child) for child in element]
    return result


def type_definition(kind):
    name = re.sub(r'^HK(?:QuantityTypeIdentifier|CategoryTypeIdentifier|DataTypeIdentifier|CorrelationTypeIdentifier)', '', kind)
    snake = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    snake = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', snake)
    snake = re.sub('[^a-z0-9]+', '_', snake.lower()).strip('_') or 'record'
    key = 'ah_' + snake
    if len(key) > 40:
        key = key[:29] + '_' + stable_id('', kind)[1:11]
    lowered = name.lower()
    if 'sleep' in lowered:
        category = 'sleep'
    elif any(word in lowered for word in ('heartrate', 'heartbeat', 'hrv', 'atrial')):
        category = 'heart'
    elif 'mindful' in lowered:
        category = 'checkin'
    elif any(word in lowered for word in ('step', 'distance', 'energyburned', 'exercise', 'stand',
                                          'workout', 'activitysummary', 'walking', 'running', 'cycling', 'flights', 'vo2')):
        category = 'activity'
    else:
        category = 'vitals'
    return key, 'Apple Health ' + name, category


def element_start(element, zone):
    if element.tag == 'ActivitySummary':
        day = datetime.strptime(element.attrib['dateComponents'], '%Y-%m-%d').date()
        return datetime.combine(day, time(), tzinfo=zone)
    return parse_time(element.get('startDate') or element.get('receivedDate'))


def convert_element(element, zone):
    attrs = element.attrib
    kind = attrs.get('type', element.tag)
    data_type, label, category = type_definition(kind)
    # Only map to the app's existing types when the exported unit agrees.
    # Preserve other types/units verbatim under Apple-specific names.
    canonical = CANONICAL_HEALTH.get(kind)
    if canonical and attrs.get('unit') == canonical[3]:
        data_type, label, category = canonical[:3]
    payload = dict(schema_version=1, apple_type=kind, **tree_data(element))
    origin = attrs.get('sourceName')
    if element.tag == 'ActivitySummary':
        day = datetime.strptime(attrs['dateComponents'], '%Y-%m-%d').date()
        start = element_start(element, zone)
        end = datetime.combine(day + timedelta(days=1), time(), tzinfo=zone)
        value, unit = None, None
        payload['timezone_assumed'] = str(zone)
        identity = stable_id('ah', [element.tag, day.isoformat(), str(zone)])
    else:
        start = element_start(element, zone)
        end = parse_time(attrs.get('endDate'))
        value, unit = None, attrs.get('unit') or None
        if element.tag == 'Record' and kind.startswith('HKQuantityTypeIdentifier'):
            value = numeric(attrs.get('value'))
        elif element.tag == 'Workout':
            value, unit = numeric(attrs.get('duration')), attrs.get('durationUnit') or None
        # Category states (sleep, stand hours, etc.) remain strings in payload.
        metadata = {child.get('key'): child.get('value') for child in element if child.tag == 'MetadataEntry'}
        external_id = attrs.get('uuid') or attrs.get('identifier') or metadata.get('HKMetadataKeySyncIdentifier') or metadata.get('HKExternalUUID')
        if external_id:
            identity = stable_id('ah', [element.tag, kind, origin, external_id])
        else:
            # Apple's export often has no stable sample UUID. Semantic identity
            # excludes device pointer addresses, version, creationDate and file order.
            identity = stable_id('ah', [element.tag, kind, origin, attrs.get('startDate'),
                                        attrs.get('endDate'), attrs.get('value'), attrs.get('unit'),
                                        attrs.get('workoutActivityType')])
    # creationDate is retained in payload, but is not a last-modified timestamp.
    row = source_record(SOURCE, data_type, identity, origin, start, end, value, unit, payload)
    return row, (data_type, label, category)


def convert(args):
    zone = ZoneInfo(args.timezone)
    since, until = date_bounds(args.since, args.until, zone)
    source = args.input.expanduser().resolve()
    if source.is_dir():
        source = source / 'export.xml'
    elements, kinds, skipped = Counter(), Counter(), Counter()
    origins = set()
    with Bundle(args, SOURCE, 'Apple Health export', 'health') as bundle:
        with source.open('rb') as stream:
            stack = []
            root = None
            for event, element in ET.iterparse(SafeXML(stream), events=('start', 'end')):
                if event == 'start':
                    if root is None:
                        root = element
                        if root.tag != 'HealthData':
                            raise ValueError('expected a HealthData root; use export.xml, not export_cda.xml')
                    stack.append(element)
                    continue
                if len(stack) == 2:
                    elements[element.tag] += 1
                    if element.tag in SUPPORTED:
                        if args.origin and element.get('sourceName') not in args.origin:
                            skipped['origin_filter'] += 1
                        else:
                            try:
                                selected = True
                                if since is not None or until is not None:
                                    start = element_start(element, zone)
                                    if start is None:
                                        raise ValueError('cannot date-filter a record with no start/received timestamp')
                                    selected = not ((since is not None and start < since) or (until is not None and start >= until))
                                if selected:
                                    row, definition = convert_element(element, zone)
                                    bundle.register_type(*definition)
                                    bundle.record(row)
                                    kinds[row['payload']['apple_type']] += 1
                                    if row['data_origin']:
                                        origins.add(row['data_origin'])
                                else:
                                    skipped['date_filter'] += 1
                            except (ValueError, KeyError, OverflowError) as exc:
                                bundle.reject(exc, dict(tag=element.tag, type=element.get('type'),
                                                        start=element.get('startDate')))
                    elif element.tag not in ('Me', 'ExportDate'):
                        skipped[element.tag] += 1
                    root.remove(element)
                    element.clear()
                stack.pop()
        if bundle.counts['source_records'] == 0:
            raise ValueError('no supported records found in the selected range; check export freshness, filters and timestamps')
        bundle.finish(timezone=args.timezone, element_counts=dict(elements), type_counts=dict(kinds),
                      origins=sorted(origins), skipped=dict(skipped),
                      date_filter=dict(since=iso_utc(since), until=iso_utc(until),
                          selection='start_at >= since and start_at < until; ActivitySummary uses local midnight',
                          interval_policy='original intervals, values, payloads and record IDs are not clipped'),
                      notes=['Me demographics omitted. Linked GPX/FHIR/ECG files are not embedded; references are retained.',
                             'Date filters select by record start/received time, not creationDate; original intervals may cross a boundary.',
                             'Only top-level records are imported: nested correlation samples are retained in payload, not counted twice.',
                             'Quantity values and units are preserved exactly; category values remain in payload.attributes.value.',
                             'HRV SDNN is not RMSSD. No cross-source aggregation or wearable preference is inferred.',
                             'ActivitySummary date-only bounds use the requested timezone, marked in payload.',
                             'No original sample UUID is usually exported: identical semantic samples collapse; deleted samples cannot be inferred.',
                             'A later full export does not instruct the database to delete records absent from it.'])
    print_result(bundle)
    return 2 if bundle.counts['rejected'] or skipped.keys() - {'origin_filter', 'date_filter'} else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', type=Path, default=Path('apple_health_export'))
    add_arguments(parser, 'exports/supabase_health')
    parser.add_argument('--timezone', default='Europe/Stockholm', help='IANA zone for naive filter bounds and date-only ActivitySummary records')
    parser.add_argument('--origin', action='append', help='select exact sourceName, repeat for several origins')
    parser.add_argument('--since', help='inclusive record start date/time; naive values use --timezone')
    parser.add_argument('--until', help='exclusive record start date/time; original records are not clipped')
    args = parser.parse_args(argv)
    try:
        return convert(args)
    except (ValueError, OSError, sqlite3.Error, ET.ParseError, ZoneInfoNotFoundError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
