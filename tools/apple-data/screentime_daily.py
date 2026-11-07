#!/usr/bin/env python3
"""Summarize exported App.InFocus sessions into a daily CSV (Python 3.10+)."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime, time, timedelta, timezone
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
COLUMNS = ['date', 'device_id', 'total_screen_time_seconds',
           'total_screen_time_minutes', 'first_active', 'last_active',
           'included_session_count', 'estimated_session_count',
           'excluded_session_count']
SUPPORTED_QUALITIES = {'paired', 'inferred_switch', 'repeated_focus'}


def day_start(value):
    try:
        if len(value) != 5 or value[2] != ':':
            raise ValueError
        return time(int(value[:2]), int(value[3:]))
    except ValueError as exc:
        raise argparse.ArgumentTypeError('day start must be HH:MM, e.g. 04:00') from exc


def boundary(day, zone, cutoff):
    # UTC conversion normalizes a nonexistent spring-forward wall time forward.
    # fold=0 picks the earlier occurrence of an ambiguous autumn wall time.
    return datetime.combine(day, cutoff, tzinfo=zone).astimezone(UTC)


def activity_day(stamp, zone, cutoff):
    day = stamp.astimezone(zone).date()
    return day if stamp >= boundary(day, zone, cutoff) else day - timedelta(days=1)


def split_interval(start, end, zone, cutoff):
    day = activity_day(start, zone, cutoff)
    while start < end:
        stop = min(end, boundary(day + timedelta(days=1), zone, cutoff))
        yield day, start, stop
        start = stop
        day += timedelta(days=1)


def merge_intervals(intervals):
    """Union overlaps so duplicates and concurrent devices count only once."""
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def timestamp(value):
    if not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamps must include a UTC offset')
    return parsed.astimezone(UTC)


def summarize(input_path, zone, cutoff, devices=None, per_device=False, paired_only=False):
    buckets = defaultdict(lambda: dict(intervals=[], included=0, estimated=0, excluded=0))
    read = selected = excluded = 0
    known_devices = set()
    with input_path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        # Accept spreadsheet-exported column casing without changing semantics.
        names = reader.fieldnames or []
        reader.fieldnames = [name.strip().lower() for name in names]
        required = {'device_id', 'start', 'end', 'duration_seconds', 'quality'}
        if not required <= set(reader.fieldnames):
            raise ValueError('input must be a sessions CSV with columns: ' + ', '.join(sorted(required)))
        for line, row in enumerate(reader, 2):
            read += 1
            try:
                device = row['device_id'].strip()
                if not device:
                    raise ValueError('missing device_id')
                known_devices.add(device)
                if devices and device not in devices:
                    continue
                selected += 1
                group = device if per_device else 'all'
                start, end = timestamp(row['start']), timestamp(row['end'])
                quality = row['quality'].strip().split(';')[0]
                raw_duration = row['duration_seconds'].strip()
                duration = float(raw_duration) if raw_duration else None
                if duration is not None and (not math.isfinite(duration) or duration < 0):
                    raise ValueError('duration must be finite and nonnegative')
                if start is not None and end is not None and end < start:
                    raise ValueError('end precedes start')
                usable = (start is not None and end is not None and duration is not None
                          and quality in SUPPORTED_QUALITIES
                          and (not paired_only or quality == 'paired'))
                if not usable:
                    excluded += 1
                    # Count exclusions without claiming unobserved activity.
                    if start is not None or end is not None:
                        day = activity_day(start or end, zone, cutoff)
                        buckets[day, group]['excluded'] += 1
                    continue
                actual = (end - start).total_seconds()
                if abs(actual - duration) > max(0.1, actual * 1e-6):
                    raise ValueError('duration disagrees with timestamps')
                if start == end:
                    # An observed instant contributes a boundary, but no time.
                    pieces = [(activity_day(start, zone, cutoff), start, end)]
                else:
                    pieces = split_interval(start, end, zone, cutoff)
                for day, left, right in pieces:
                    bucket = buckets[day, group]
                    bucket['intervals'].append((left, right))
                    bucket['included'] += 1
                    bucket['estimated'] += quality != 'paired'
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f'CSV line {line}: {exc}') from exc
    if devices and not devices <= known_devices:
        raise ValueError('unknown device(s): ' + ', '.join(sorted(devices - known_devices)))
    if not selected:
        raise ValueError('no sessions found for the selected devices')
    if not buckets:
        raise ValueError('no timestamped sessions found')
    # Emit calendar gaps too: zero means no usable activity in the input, not
    # proof the screen was off. Counts make incomplete days visible.
    groups = {group for _, group in buckets}
    for group in groups:
        days = [day for day, g in buckets if g == group]
        day, last = min(days), max(days)
        while day <= last:
            buckets[day, group]
            day += timedelta(days=1)
    rows = []
    for (day, group), bucket in sorted(buckets.items()):
        intervals = merge_intervals(bucket['intervals'])
        total = sum((end - start).total_seconds() for start, end in intervals)
        rows.append(dict(date=day.isoformat(), device_id=group,
                         total_screen_time_seconds=round(total, 6),
                         total_screen_time_minutes=round(total / 60, 6),
                         first_active=intervals[0][0].astimezone(zone).isoformat() if intervals else '',
                         last_active=intervals[-1][1].astimezone(zone).isoformat() if intervals else '',
                         included_session_count=bucket['included'],
                         estimated_session_count=bucket['estimated'],
                         excluded_session_count=bucket['excluded']))
    return rows, dict(read=read, selected=selected, excluded=excluded)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', type=Path, default=Path('screentime.csv'),
                        help='sessions CSV from screentime_export.py (default: screentime.csv)')
    parser.add_argument('-o', '--output', type=Path, default=Path('daily_screentime.csv'))
    parser.add_argument('--timezone', default='Europe/Stockholm')
    parser.add_argument('--day-start', type=day_start, default=time(4),
                        help='local day boundary; earlier activity belongs to previous day (default: 04:00)')
    parser.add_argument('--device', action='append', help='select device_id; may be repeated')
    parser.add_argument('--per-device', action='store_true', help='separate daily rows for each device')
    parser.add_argument('--paired-only', action='store_true', help='exclude inferred sessions')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args(argv)
    try:
        input_path = args.input.expanduser().resolve()
        output_path = args.output.expanduser().resolve()
        if input_path == output_path:
            raise ValueError('output must differ from input')
        rows, stats = summarize(input_path, ZoneInfo(args.timezone), args.day_start,
                                set(args.device) if args.device else None,
                                args.per_device, args.paired_only)
        with output_path.open('w' if args.overwrite else 'x', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} daily rows to {output_path}. "
              f"Selected {stats['selected']} sessions; excluded {stats['excluded']} incomplete/untrusted sessions. "
              f"Day starts at {args.day_start:%H:%M} ({args.timezone}).", file=sys.stderr)
        return 0
    except (ValueError, OSError, ZoneInfoNotFoundError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
