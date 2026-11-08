#!/usr/bin/env python3
"""Convert Screen Time session CSV into Supabase source_records and daily_metrics."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import screentime_daily as daily
from supabase_export_common import (Bundle, add_arguments, iso_utc, numeric,
                                    parse_time, print_result, source_record, stable_id)

SOURCE = 'apple_screen_time'
DATA_TYPE = 'apple_screen_session'


def convert(args):
    zone = ZoneInfo(args.timezone)
    devices = set(args.device) if args.device else None
    source = args.input.expanduser().resolve()
    if source == args.output_dir.expanduser().resolve() or source in args.output_dir.expanduser().resolve().parents:
        raise ValueError('output must not replace the input')
    # Reuse the existing tested union/day-boundary logic. Validation completes
    # before any final output is published.
    summaries, summary_stats = daily.summarize(source, zone, args.day_start, devices, False, args.paired_only)
    with Bundle(args, SOURCE, 'Apple Screen Time (Biome)', 'screen') as bundle:
        bundle.register_type(DATA_TYPE, 'Apple app focus session', 'screen')
        bundle.register_type('app_usage', 'App usage sessions', 'screen')
        with source.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            reader.fieldnames = [n.strip().lower() for n in reader.fieldnames or []]
            required = {'device_id', 'bundle_id', 'start', 'end', 'duration_seconds', 'quality'}
            if not required <= set(reader.fieldnames):
                raise ValueError('input must be the sessions export, including bundle_id and device_id')
            for line, row in enumerate(reader, 2):
                if devices and row['device_id'] not in devices:
                    continue
                try:
                    start, end = parse_time(row['start']), parse_time(row['end'])
                    if start is None:
                        raise ValueError('missing_start: cannot satisfy source_records.start_at')
                    if not row['bundle_id'].strip():
                        raise ValueError('missing bundle_id')
                    quality = row['quality'].strip()
                    duration = numeric(row['duration_seconds'])
                    usable = (end is not None and duration is not None
                              and quality.split(';')[0] in daily.SUPPORTED_QUALITIES)
                    if duration is not None and Decimal(duration) < 0:
                        raise ValueError('negative duration')
                    offset = row.get('source_offset')
                    payload = dict(schema_version=1, bundle_id=row['bundle_id'], device_id=row['device_id'],
                                   quality=quality, duration_seconds=duration, usable_duration=usable,
                                   provenance=dict(source_file=Path(row.get('source_file') or '').name,
                                                   source_offset=int(offset) if offset else None))
                    # Existing app-usage views expect minutes and the bundle ID
                    # before the first colon. Keep device identity in the hash
                    # and payload, never collapse sessions from two devices.
                    app_id = row['bundle_id']
                    prefix = app_id if len(app_id) <= 130 else 'ast'
                    identity = stable_id(prefix, [row['device_id'], app_id, iso_utc(start)])
                    record_type = 'app_usage' if usable else DATA_TYPE
                    value = str(Decimal(duration) / 60) if usable else None
                    bundle.record(source_record(SOURCE, record_type, identity, app_id,
                                                start, end, value, 'min', payload))
                except (ValueError, TypeError) as exc:
                    bundle.reject(exc, dict(line=line, device_id=row.get('device_id'),
                                            bundle_id=row.get('bundle_id'), start=row.get('start'), end=row.get('end')))
        for row in summaries:
            if not row['included_session_count']:
                continue
            bundle.metric(row['date'], 'apple_screen.total_seconds', row['total_screen_time_seconds'],
                          'Apple app focus time', 's')
            bundle.metric(row['date'], 'apple_screen.first_active_unix_s',
                          parse_time(row['first_active']).timestamp(), 'Apple first app activity', 'unix_s')
            bundle.metric(row['date'], 'apple_screen.last_active_unix_s',
                          parse_time(row['last_active']).timestamp(), 'Apple last app activity', 'unix_s')
        bundle.finish(timezone=args.timezone, day_start=args.day_start.strftime('%H:%M'),
                      selected_devices=sorted(devices) if devices else 'all', paired_only=args.paired_only,
                      daily_summary=summary_stats,
                      notes=['Focus telemetry estimates, not hardware display-on time.',
                             'Daily metrics union all selected devices; overlapping use counts once.',
                             'A fixed day cutoff approximates the sleep day, not actual sleep detection.',
                             'Raw records retain inferred/incomplete sessions; missing starts are rejected.'])
    print_result(bundle)
    return 2 if bundle.counts['rejected'] else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', type=Path, default=Path('screentime.csv'))
    add_arguments(parser, 'exports/supabase_screen')
    parser.add_argument('--timezone', default='Europe/Stockholm')
    parser.add_argument('--day-start', type=daily.day_start, default=daily.day_start('04:00'))
    parser.add_argument('--device', action='append')
    parser.add_argument('--paired-only', action='store_true', help='daily metrics use only paired sessions')
    args = parser.parse_args(argv)
    try:
        return convert(args)
    except (ValueError, OSError, sqlite3.Error, ZoneInfoNotFoundError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
