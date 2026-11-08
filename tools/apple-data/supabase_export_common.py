"""Shared local conversion utilities; no network or database access."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import gzip
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import uuid
from zoneinfo import ZoneInfo
from apple_contract import VERSION

UTC = timezone.utc
RECORD_COLUMNS = ['source', 'data_type', 'source_record_id', 'data_origin',
                  'start_at', 'end_at', 'start_offset_min', 'end_offset_min',
                  'value', 'unit', 'payload', 'source_modified_at']
METRIC_COLUMNS = ['day', 'metric_key', 'value', 'source']


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def stable_id(prefix, identity):
    return prefix + ':' + hashlib.sha256(json_text(identity).encode()).hexdigest()


def parse_time(value):
    if not value or not value.strip():
        return None
    text = value.strip().replace('Z', '+00:00')
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        # Apple's export uses a space before its numeric UTC offset. Python
        # 3.10 does not accept this form in fromisoformat.
        stamp = datetime.strptime(text, '%Y-%m-%d %H:%M:%S %z')
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('timestamp lacks a UTC offset')
    return stamp


def offset_minutes(stamp):
    if stamp is None:
        return None
    offset = stamp.utcoffset().total_seconds() / 60
    if not offset.is_integer() or not -840 <= offset <= 840:
        raise ValueError('UTC offset outside schema limits')
    return int(offset)


def iso_utc(stamp):
    return stamp.astimezone(UTC).isoformat() if stamp is not None else None


def date_bounds(since, until, zone):
    """Inclusive lower/exclusive upper instants. Naive inputs use the IANA zone.

    Refuse ambiguous/nonexistent local wall times rather than silently choosing
    the wrong hour at DST transitions. Explicit offsets disambiguate them.
    """
    def bound(value):
        if value is None:
            return None
        try:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            raise ValueError('date bounds must be ISO dates/times, e.g. 2026-10-21T04:00:00') from None
        if stamp.tzinfo is None:
            local = stamp.replace(tzinfo=zone)
            returned = local.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
            if returned != stamp or local.utcoffset() != stamp.replace(tzinfo=zone, fold=1).utcoffset():
                raise ValueError('ambiguous/nonexistent local date bound; supply an explicit UTC offset')
            stamp = local
        offset_minutes(stamp)
        return stamp.astimezone(UTC)
    lower, upper = bound(since), bound(until)
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError('--since must precede --until')
    return lower, upper


def numeric(value):
    """Return exact decimal text, suitable for Postgres numeric input."""
    if value is None or value == '':
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'invalid numeric value: {value!r}') from exc
    if not number.is_finite():
        raise ValueError('numeric value must be finite')
    return str(number)


def source_record(source, data_type, identity, origin, start, end, value, unit, payload, modified=None):
    if start is None:
        raise ValueError('source_records.start_at requires a known timestamp')
    if end is not None and end < start:
        raise ValueError('end precedes start')
    if origin is not None and len(origin) > 200:
        # Preserve the complete origin in payload while keeping the indexed label bounded.
        payload = dict(payload, full_data_origin=origin)
        origin = origin[:180] + ':' + hashlib.sha256(origin.encode()).hexdigest()[:16]
    if unit is not None and not 1 <= len(unit) <= 32:
        raise ValueError('unit violates schema length limit')
    return dict(source=source, data_type=data_type, source_record_id=identity,
                data_origin=origin, start_at=iso_utc(start), end_at=iso_utc(end),
                start_offset_min=offset_minutes(start), end_offset_min=offset_minutes(end),
                value=numeric(value), unit=unit, payload=payload, source_modified_at=iso_utc(modified))


def uuid_arg(value):
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError('expected a UUID') from exc


def add_arguments(parser, default_output):
    parser.add_argument('-o', '--output-dir', type=Path, default=Path(default_output),
                        help='new output directory; existing directories are never overwritten')
    parser.add_argument('--user-id', type=uuid_arg,
                        help='auth.users UUID; omit only for authenticated API ingestion using auth.uid()')
    parser.add_argument('--connection-id', type=uuid_arg, help='existing connection owned by this user')
    parser.add_argument('--format', choices=['csv', 'jsonl', 'both'], default='csv')
    parser.add_argument('--gzip', action='store_true', help='compress CSV/JSONL files for large exports')


class Bundle:
    """Stream rows and deduplicate on disk, then atomically publish a new directory."""
    def __init__(self, args, source, label, category):
        self.args, self.source, self.label, self.category = args, source, label, category
        self.output = args.output_dir.expanduser().resolve()
        self.types, self.metrics, self.handles, self.writers = {}, {}, [], {}
        self.counts = Counter()
        self.first = self.last = None

    def __enter__(self):
        if self.output.exists():
            raise ValueError(f'output directory already exists: {self.output}')
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix='.' + self.output.name + '-', dir=self.output.parent))
        self.db = sqlite3.connect(self.temp / 'dedup.sqlite')
        self.db.execute('CREATE TABLE seen (key BLOB PRIMARY KEY) WITHOUT ROWID')
        self.rejects = (self.temp / 'rejected.jsonl').open('w', encoding='utf-8')
        self.handles.append(self.rejects)
        return self

    def register_type(self, key, label, category):
        definition = dict(key=key, label=label, category=category)
        if key in self.types and self.types[key] != definition:
            raise ValueError(f'data type collision: {key}')
        self.types[key] = definition

    def write(self, table, row, columns):
        if self.args.user_id:
            row = dict(row, user_id=self.args.user_id)
        if table == 'source_records' and self.args.connection_id:
            row = dict(row, connection_id=self.args.connection_id)
        if self.args.format in ('csv', 'both'):
            key = table, 'csv'
            if key not in self.writers:
                path = self.temp / (f'{table}.csv.gz' if self.args.gzip else f'{table}.csv')
                stream = gzip.open(path, 'wt', encoding='utf-8', newline='') if self.args.gzip else path.open('w', encoding='utf-8', newline='')
                self.handles.append(stream)
                fields = list(columns) + (['user_id'] if self.args.user_id else [])
                if table == 'source_records' and self.args.connection_id:
                    fields.append('connection_id')
                self.writers[key] = csv.DictWriter(stream, fieldnames=fields)
                self.writers[key].writeheader()
            self.writers[key].writerow({k: json_text(v) if isinstance(v, (dict, list)) else v
                                       for k, v in row.items()})
        if self.args.format in ('jsonl', 'both'):
            key = table, 'jsonl'
            if key not in self.writers:
                path = self.temp / (f'{table}.jsonl.gz' if self.args.gzip else f'{table}.jsonl')
                stream = gzip.open(path, 'wt', encoding='utf-8') if self.args.gzip else path.open('w', encoding='utf-8')
                self.handles.append(stream)
                self.writers[key] = stream
            self.writers[key].write(json_text(row) + '\n')
        self.counts[table] += 1

    def record(self, row):
        key = hashlib.sha256((row['source'] + ':' + row['source_record_id']).encode()).digest()
        cursor = self.db.execute('INSERT OR IGNORE INTO seen VALUES (?)', (key,))
        if not cursor.rowcount:
            self.counts['duplicates'] += 1
            return
        self.first = min(self.first or row['start_at'], row['start_at'])
        self.last = max(self.last or row['start_at'], row['start_at'])
        self.write('source_records', row, RECORD_COLUMNS)

    def reject(self, reason, context):
        self.counts['rejected'] += 1
        self.rejects.write(json_text(dict(reason=str(reason), context=context)) + '\n')

    def metric(self, day, key, value, label, unit):
        self.metrics[key] = dict(key=key, label=label, unit=unit, good_direction='none')
        self.write('daily_metrics', dict(day=day, metric_key=key, value=numeric(value), source=self.source), METRIC_COLUMNS)

    def finish(self, **extra):
        setup = ["-- REVIEW ONLY. Additive registry rows, NOT an upload or permission migration.",
                 "-- Do not run until approved for the target project. No existing rows are changed.",
                 "-- Existing registry definitions are preserved; verify any conflicting keys.",
                 "BEGIN;"]
        def seed(table, rows):
            for row in rows:
                def quote(value):
                    return "'" + str(value).replace("'", "''") + "'"
                setup.append(f"INSERT INTO public.{table} ({', '.join(row)}) VALUES "
                             f"({', '.join(quote(v) for v in row.values())}) ON CONFLICT (key) DO NOTHING;")
        seed('sources', [dict(key=self.source, label=self.label, category=self.category, delivery='file')])
        seed('data_types', sorted(self.types.values(), key=lambda t: t['key']))
        seed('metric_definitions', sorted(self.metrics.values(), key=lambda t: t['key']))
        setup.extend(['COMMIT;', ''])
        (self.temp / 'setup.sql').write_text('\n'.join(setup), encoding='utf-8')
        manifest = dict(converter_version=str(VERSION), source=self.source,
                        created_at=datetime.now(UTC).isoformat(), counts=dict(self.counts),
                        first_record_start=self.first, last_record_start=self.last,
                        user_id=self.args.user_id, connection_id=self.args.connection_id,
                        format=self.args.format, gzip=self.args.gzip,
                        data_types=list(self.types.values()), metric_definitions=list(self.metrics.values()),
                        source_records_conflict_key=['user_id', 'source', 'source_record_id'],
                        daily_metrics_conflict_key=['user_id', 'day', 'metric_key'],
                        **extra)
        (self.temp / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def __exit__(self, exc_type, exc, tb):
        for stream in self.handles:
            stream.close()
        self.db.close()
        if exc_type is not None:
            shutil.rmtree(self.temp)
        else:
            (self.temp / 'dedup.sqlite').unlink()
            if self.output.exists():
                raise ValueError(f'output appeared during conversion; staged files retained at {self.temp}')
            self.temp.rename(self.output)


def print_result(bundle):
    print(f"Wrote {bundle.counts['source_records']} source records to {bundle.output}; "
          f"{bundle.counts['duplicates']} duplicates, {bundle.counts['rejected']} rejected.")
    if not bundle.args.user_id:
        print('user_id omitted: use an authenticated user API client, or rerun with --user-id for CSV/admin import.')
