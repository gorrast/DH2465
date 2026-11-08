#!/usr/bin/env python3
"""Read-only, dependency-free App.InFocus exporter for Python 3.10+."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import struct
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import zlib

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
DEFAULT_SOURCE = Path.home() / 'Library/Biome/streams/restricted/App.InFocus'
EVENT_COLUMNS = ['device_id', 'timestamp', 'bundle_id', 'event', 'app_version',
                 'transition_reason', 'source_file', 'source_offset']
SESSION_COLUMNS = ['device_id', 'bundle_id', 'start', 'end', 'duration_seconds',
                   'quality', 'source_file', 'source_offset']


class DecodeError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise DecodeError(message)


def segb_records(data: bytes):
    """Yield (state, payload, payload offset), validating bounds and CRCs.

    SEGB1 has inline record headers; SEGB2 has an index at EOF whose end
    offsets are relative to the 32-byte header. Deletion entries supersede
    written entries referring to the same SEGB2 payload.
    """
    if len(data) >= 56 and data[52:56] == b'SEGB':
        limit = struct.unpack_from('<I', data)[0]
        require(56 <= limit <= len(data), 'invalid SEGB1 data boundary')
        pos = 56
        while pos < limit:
            require(pos + 32 <= limit, 'truncated SEGB1 record header')
            length, state = struct.unpack_from('<ii', data, pos)
            crc = struct.unpack_from('<I', data, pos + 24)[0]
            pos += 32
            require(0 <= length <= limit - pos, 'invalid SEGB1 payload length')
            payload = data[pos:pos + length]
            if state == 1:
                require(zlib.crc32(payload) == crc, 'SEGB1 CRC mismatch')
            yield state, payload, pos
            pos = (pos + length + 7) // 8 * 8
    elif data[:4] == b'SEGB':
        require(len(data) >= 32, 'truncated SEGB2 header')
        count = struct.unpack_from('<i', data, 4)[0]
        require(0 <= count <= (len(data) - 32) // 16, 'invalid SEGB2 index count')
        index_start = len(data) - 16 * count
        entries = {}
        for pos in range(index_start, len(data), 16):
            end, state = struct.unpack_from('<ii', data, pos)
            if state == 0 and end == 0:
                continue
            require(state in (1, 2, 3, 4), 'unknown SEGB2 record state')
            if state == 4:
                continue
            require(0 < end <= index_start - 32, 'invalid SEGB2 end offset')
            # A written and deleted entry can reference the same payload.
            entries[end] = state if state != 1 else entries.get(end, state)
        start = 32
        for relative_end, state in sorted(entries.items()):
            end = relative_end + 32
            # Stale index entries may point inside already consumed data.
            if end < start + 8:
                continue
            crc = struct.unpack_from('<I', data, start)[0]
            payload = data[start + 8:end]
            if state == 1:
                require(zlib.crc32(payload) == crc, 'SEGB2 CRC mismatch')
            yield state, payload, start + 8
            start = (end + 3) // 4 * 4
    else:
        raise DecodeError('not a SEGB1 or SEGB2 file')


def varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        require(pos < len(data), 'truncated protobuf varint')
        byte = data[pos]
        pos += 1
        require(shift != 63 or byte <= 1, 'protobuf varint overflow')
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise DecodeError('protobuf varint overflow')


def protobuf_fields(data):
    fields = {}
    pos = 0
    while pos < len(data):
        tag, pos = varint(data, pos)
        field, wire = tag >> 3, tag & 7
        require(0 < field < 2**29, 'invalid protobuf field number')
        if wire == 0:
            value, pos = varint(data, pos)
        else:
            if wire == 2:
                size, pos = varint(data, pos)
            elif wire in (1, 5):
                size = 8 if wire == 1 else 4
            else:
                raise DecodeError(f'unsupported protobuf wire type {wire}')
            require(size <= len(data) - pos, 'truncated protobuf field')
            value = data[pos:pos + size]
            pos += size
        fields[field] = (wire, value)
    return fields


def focus_event(payload, device, path, offset):
    fields = protobuf_fields(payload)
    require(fields.get(4, (None,))[0] == 1, 'missing focus timestamp')
    require(fields.get(6, (None,))[0] == 2, 'missing bundle identifier')
    state_wire, state = fields.get(3, (0, 0))  # proto3 omits default zero
    require(state_wire == 0 and state in (0, 1), 'invalid focus state')
    seconds = struct.unpack('<d', fields[4][1])[0]
    require(math.isfinite(seconds), 'non-finite timestamp')
    try:
        timestamp = APPLE_EPOCH + timedelta(seconds=seconds)
        require(2001 <= timestamp.year <= 2200, 'implausible timestamp')
        def string(number):
            wire, value = fields.get(number, (2, b''))
            require(wire == 2, f'invalid string field {number}')
            return value.decode('utf-8')
        bundle = string(6)
        require(bool(bundle) and '\x00' not in bundle, 'invalid bundle identifier')
        return dict(device_id=device, timestamp=timestamp, bundle_id=bundle,
                    event='focus_gained' if state else 'focus_lost',
                    app_version=string(9), transition_reason=string(1),
                    source_file=str(path), source_offset=offset)
    except (OverflowError, UnicodeError) as exc:
        raise DecodeError(str(exc)) from exc


def discover(source):
    """Accept App.InFocus, local, remote, device folder, or a segment file."""
    if source.is_file():
        device = source.parent.name if source.parent.parent.name == 'remote' else 'local'
        return [(device, source)]
    require(source.is_dir(), f'source directory does not exist: {source}')
    parts = source.parts
    if source.name == 'App.InFocus':
        roots = [(source / 'local', 'local'), (source / 'remote', None)]
    elif source.name == 'remote':
        roots = [(source, None)]
    else:
        roots = [(source, source.name if 'remote' in parts else 'local')]
    files = []
    def fail(exc):
        raise exc
    for root, fixed_device in roots:
        # iterdir explicitly propagates permission failures, unlike glob.
        try:
            children = list(root.iterdir())
        except FileNotFoundError:
            continue
        device_roots = [(root, fixed_device)] if fixed_device else [
            (p, p.name) for p in children if p.is_dir() and p.name != 'tombstone']
        for device_root, device in device_roots:
            for folder, dirs, names in os.walk(device_root, onerror=fail, followlinks=False):
                dirs[:] = [d for d in dirs if d != 'tombstone' and not d.startswith('.')]
                for name in names:
                    if not name.startswith('.'):
                        path = Path(folder) / name
                        if not path.is_symlink():
                            files.append((device, path))
    return sorted(files)


def load_events(files):
    events = {}
    stats = dict(files=0, non_segb_files=0, deleted_records=0,
                 rejected_records=0, duplicates=0, errors=[])
    for device, path in files:
        # Read a byte snapshot; never open the source for writing.
        try:
            data = path.read_bytes()
            if data[:4] != b'SEGB' and data[52:56] != b'SEGB':
                stats['non_segb_files'] += 1
                continue
            stats['files'] += 1
            for state, payload, offset in segb_records(data):
                if state != 1:
                    stats['deleted_records'] += 1
                    continue
                try:
                    event = focus_event(payload, device, path, offset)
                except DecodeError as exc:
                    stats['rejected_records'] += 1
                    stats['errors'].append(f'{path}:{offset}: {exc}')
                    continue
                key = device, event['timestamp'], event['bundle_id'], event['event']
                if key in events:
                    stats['duplicates'] += 1
                else:
                    events[key] = event
        except PermissionError:
            raise
        except (OSError, DecodeError, struct.error) as exc:
            stats['errors'].append(f'{path}: {exc}')
    # Close old focus before opening new focus at the same timestamp.
    return sorted(events.values(), key=lambda e: (
        e['timestamp'], e['event'] == 'focus_gained', e['device_id'], e['bundle_id'])), stats


def sessions(events, max_seconds):
    active = {}
    result = []
    def close(event, end, quality):
        duration = (end - event['timestamp']).total_seconds() if end else None
        if duration is not None and duration > max_seconds:
            # Keep boundaries for auditing but do not claim a reliable duration.
            duration, quality = None, 'gap_exceeds_limit'
        result.append(dict(device_id=event['device_id'], bundle_id=event['bundle_id'],
                           start=event['timestamp'], end=end, duration_seconds=duration,
                           quality=quality, source_file=event['source_file'],
                           source_offset=event['source_offset']))
    for event in events:
        device = event['device_id']
        previous = active.get(device)
        if event['event'] == 'focus_gained':
            if previous:
                quality = 'repeated_focus' if previous['bundle_id'] == event['bundle_id'] else 'inferred_switch'
                close(previous, event['timestamp'], quality)
            active[device] = event
        elif previous and previous['bundle_id'] == event['bundle_id']:
            close(previous, event['timestamp'], 'paired')
            del active[device]
        else:
            # Missing starts cannot supply a duration.
            result.append(dict(device_id=device, bundle_id=event['bundle_id'],
                               start=None, end=event['timestamp'], duration_seconds=None,
                               quality='missing_start', source_file=event['source_file'],
                               source_offset=event['source_offset']))
    for event in active.values():
        close(event, None, 'missing_end')
    return sorted(result, key=lambda r: (r['start'] or r['end'], r['device_id']))


def select_rows(rows, mode, since, until):
    result = []
    for row in rows:
        if mode == 'events':
            if (since is None or row['timestamp'] >= since) and (until is None or row['timestamp'] < until):
                result.append(row)
            continue
        start, end = row['start'], row['end']
        if start is None or end is None:
            known = start or end
            if (since is None or known >= since) and (until is None or known < until):
                result.append(row)
            continue
        if (since is not None and end <= since) or (until is not None and start >= until):
            continue
        copy = row.copy()
        copy['start'] = max(start, since) if since else start
        copy['end'] = min(end, until) if until else end
        if row['duration_seconds'] is not None:
            copy['duration_seconds'] = (copy['end'] - copy['start']).total_seconds()
        if (copy['start'], copy['end']) != (start, end):
            copy['quality'] += ';clipped'
        result.append(copy)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--list-devices', action='store_true', help='list stream identifiers and file counts')
    parser.add_argument('--device', action='append', help='local or remote UUID; repeat to select several')
    parser.add_argument('--mode', choices=['events', 'sessions'], default='sessions')
    parser.add_argument('--format', choices=['csv', 'json'])
    parser.add_argument('-o', '--output', type=Path, help='output file (default: stdout); existing files require --overwrite')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--timezone', default='UTC', help='IANA zone, e.g. Europe/Stockholm')
    parser.add_argument('--since', help='inclusive ISO date/time in the selected timezone')
    parser.add_argument('--until', help='exclusive ISO date/time in the selected timezone')
    parser.add_argument('--max-session-hours', type=float, default=4,
                        help='longer sessions keep boundaries but have null duration (default: 4)')
    args = parser.parse_args(argv)
    try:
        zone = ZoneInfo(args.timezone)
        def bound(value):
            if value is None:
                return None
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return (dt if dt.tzinfo else dt.replace(tzinfo=zone)).astimezone(timezone.utc)
        since, until = bound(args.since), bound(args.until)
        require(since is None or until is None or since < until, '--since must precede --until')
        require(math.isfinite(args.max_session_hours) and args.max_session_hours > 0,
                '--max-session-hours must be positive and finite')
        source = args.source.expanduser().resolve()
        if args.output:
            output = args.output.expanduser().resolve()
            require(output != source and source not in output.parents,
                    'output must be outside the source directory')
        files = discover(source)
        if args.list_devices:
            counts = {}
            for device, _ in files:
                counts[device] = counts.get(device, 0) + 1
            print(json.dumps(counts, indent=2))
            return 0
        if args.device:
            available = {device for device, _ in files}
            require(set(args.device) <= available, f'unknown device; available: {sorted(available)}')
            files = [(device, p) for device, p in files if device in args.device]
        require(bool(files), 'no stream files found; check --source and Screen Time sync')
        events, stats = load_events(files)
        for error in stats['errors'][:10]:
            print(f'Warning: {error}', file=sys.stderr)
        if len(stats['errors']) > 10:
            print(f"Warning: {len(stats['errors']) - 10} more decoding errors", file=sys.stderr)
        require(bool(events), 'no valid App.InFocus events decoded')
        rows = events if args.mode == 'events' else sessions(events, args.max_session_hours * 3600)
        rows = select_rows(rows, args.mode, since, until)
        serialized = [{k: v.astimezone(zone).isoformat() if isinstance(v, datetime) else v
                       for k, v in row.items()} for row in rows]
        fmt = args.format or ('csv' if args.output and args.output.suffix.lower() == '.csv' else 'json')
        stream = output.open('w' if args.overwrite else 'x', encoding='utf-8', newline='') if args.output else sys.stdout
        try:
            if fmt == 'json':
                json.dump(serialized, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.write('\n')
            else:
                writer = csv.DictWriter(stream, fieldnames=EVENT_COLUMNS if args.mode == 'events' else SESSION_COLUMNS)
                writer.writeheader()
                writer.writerows(serialized)
        finally:
            if args.output:
                stream.close()
        print(f"Decoded {len(events)} events; exported {len(rows)} {args.mode}; "
              f"{stats['files']} SEGB files; {stats['duplicates']} duplicates; "
              f"{len(stats['errors'])} errors. Latest event: {events[-1]['timestamp'].astimezone(zone).isoformat()}", file=sys.stderr)
        return 2 if stats['errors'] else 0
    except PermissionError as exc:
        print(f'Access denied: {exc}. Enable Full Disk Access for your terminal in '
              'System Settings > Privacy & Security, then quit and reopen it.', file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
