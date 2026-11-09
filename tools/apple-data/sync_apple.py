#!/usr/bin/env python3
"""Standalone Apple export, read-only preview, then explicitly approved append-only upload."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
from zoneinfo import ZoneInfo

from apple_contract import VERSION
import health_to_supabase
import screentime_daily
import screentime_export
import screentime_to_supabase
from supabase_api import APIError, Client, settings
from supabase_export_common import date_bounds, iso_utc, json_text, parse_time, uuid_arg

ROOT = Path(__file__).resolve().parent
TABLES = ('source_records', 'daily_metrics')


class SyncError(ValueError):
    pass


def read_config(path):
    """Literal KEY=value reader: no shell execution or secret logging."""
    values = {}
    if path.exists():
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                raise SyncError(f'{path.name} line {number}: expected KEY=value')
            key, value = line.split('=', 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            values[key.strip()] = value
    values.update(os.environ)
    return values


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def filtered_screen_csv(source, output, lower, upper, zone):
    """Apply the exporter's same overlap/clipping rules to an existing CSV.

    Never modify the input. Malformed/untimestamped rows fail closed rather than
    accidentally escaping the selected date range.
    """
    with source.open(encoding='utf-8-sig', newline='') as stream, output.open('x', encoding='utf-8', newline='') as dest:
        reader = csv.DictReader(stream)
        reader.fieldnames = [key.strip().lower() for key in reader.fieldnames or []]
        if not {'device_id', 'bundle_id', 'start', 'end', 'duration_seconds', 'quality'} <= set(reader.fieldnames):
            raise SyncError('Date filtering requires a Screen Time sessions CSV.')
        writer = csv.DictWriter(dest, fieldnames=reader.fieldnames)
        writer.writeheader()
        for raw in reader:
            row = dict(raw, start=parse_time(raw['start']), end=parse_time(raw['end']),
                       duration_seconds=raw['duration_seconds'] or None)
            if row['start'] is None and row['end'] is None:
                raise SyncError('Cannot date-filter a screen row with no known timestamp.')
            for selected in screentime_export.select_rows([row], 'sessions', lower, upper):
                for key in ('start', 'end'):
                    selected[key] = selected[key].astimezone(zone).isoformat() if selected[key] else ''
                writer.writerow(selected)


def build_run(args, user_id=None):
    lower, upper = date_bounds(args.since, args.until, ZoneInfo(args.timezone))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run = args.output_root.expanduser().resolve() / (stamp + '-' + uuid.uuid4().hex[:8])
    run.mkdir(parents=True, mode=0o700)
    print(f'Run files: {run}', flush=True)
    state = dict(version=VERSION, transport='standalone-edge-append-only', status='collecting',
                 bundles=[], progress={}, timezone=args.timezone, day_start=args.day_start, warnings=[],
                 date_filter=dict(since=iso_utc(lower), until=iso_utc(upper)))
    atomic_json(run / 'sync_state.json', state)
    try:
        selected = ['screen', 'health'] if args.only == 'all' else [args.only]
        for kind in selected:
            common = ['--output-dir', str(run / kind), '--format', 'jsonl', '--gzip']
            if kind == 'screen':
                if args.screen_csv:
                    screen_csv = args.screen_csv.expanduser().resolve()
                    if lower is not None or upper is not None:
                        selected_csv = run / 'screen_sessions.csv'
                        filtered_screen_csv(screen_csv, selected_csv, lower, upper, ZoneInfo(args.timezone))
                        screen_csv = selected_csv
                else:
                    screen_csv = run / 'screen_sessions.csv'
                    print('Collecting retained Mac and synced-device Screen Time...', flush=True)
                    bounds = (['--since', iso_utc(lower)] if lower is not None else []) + (['--until', iso_utc(upper)] if upper is not None else [])
                    code = screentime_export.main(['--source', str(args.screen_source.expanduser()),
                        '--timezone', args.timezone, '--format', 'csv', '--output', str(screen_csv), *bounds])
                    if code == 1 or code == 2 and not args.allow_partial:
                        raise SyncError('Screen collection failed or was partial. Check Full Disk Access and diagnostics. No upload was attempted.')
                    if code == 2:
                        state['warnings'].append('Some Screen Time segments could not be decoded.')
                print('Cleaning Screen Time and calculating sleep-day totals...', flush=True)
                code = screentime_to_supabase.main([str(screen_csv), *common,
                    '--timezone', args.timezone, '--day-start', args.day_start])
                if code != 1 and screentime_daily.main([str(screen_csv), '-o', str(run / 'screen_daily.csv'),
                        '--timezone', args.timezone, '--day-start', args.day_start]) != 0:
                    raise SyncError('Daily CSV generation failed. No upload was attempted.')
            else:
                print('Reading and cleaning the Health export...', flush=True)
                bounds = (['--since', iso_utc(lower)] if lower is not None else []) + (['--until', iso_utc(upper)] if upper is not None else [])
                code = health_to_supabase.main([str(args.health_export.expanduser()), *common, '--timezone', args.timezone, *bounds])
            if code == 1:
                raise SyncError(f'{kind} conversion failed. No upload was attempted.')
            if code == 2:
                state['warnings'].append(f'{kind}: records were excluded; see {kind}/manifest.json and rejected.jsonl.')
            manifest_path = run / kind / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['requested_window'] = state['date_filter']
            atomic_json(manifest_path, manifest)
            state['bundles'].append(kind)
        state['status'] = 'ready'
        atomic_json(run / 'sync_state.json', state)
        return run, state
    except BaseException:
        state['status'] = 'collection_failed'
        atomic_json(run / 'sync_state.json', state)
        raise


def batches(path, size):
    """Bound both row count and JSON body size, leaving room for request metadata."""
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        batch, nbytes = [], 0
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            length = len(json_text(row).encode('utf-8')) + 2
            if length > 850_000:
                raise SyncError('A single record is too large for the importer.')
            if batch and (len(batch) >= size or nbytes + length > 850_000):
                yield batch
                batch, nbytes = [], 0
            batch.append(row)
            nbytes += length
        if batch:
            yield batch


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run_files(run, state):
    run = run.resolve()
    if (state.get('version') != VERSION or state.get('transport') != 'standalone-edge-append-only'
            or state.get('status') not in ('ready', 'uploading', 'upload_failed', 'complete')
            or not isinstance(state.get('bundles'), list) or not state['bundles']
            or len(set(state['bundles'])) != len(state['bundles'])
            or any(kind not in ('screen', 'health') for kind in state['bundles'])):
        raise SyncError('This run is incomplete or uses the old contract. Prepare a new run; old exports are preserved.')
    files, manifests = {}, {}
    for kind in state['bundles']:
        manifest_path = run / kind / 'manifest.json'
        if run not in manifest_path.resolve().parents:
            raise SyncError('Bundle files must stay inside the run directory.')
        manifest = json.loads(manifest_path.read_text())
        expected = 'apple_health' if kind == 'health' else 'apple_screen_time'
        if manifest.get('converter_version') != str(VERSION) or manifest.get('source') != expected:
            raise SyncError('Bundle contract/source mismatch; prepare a new run.')
        manifests[kind] = manifest
        files[f'{kind}/manifest.json'] = digest_file(manifest_path)
        for table in TABLES:
            path = run / kind / (table + '.jsonl.gz')
            if path.exists():
                if run not in path.resolve().parents:
                    raise SyncError('Bundle files must stay inside the run directory.')
                files[f'{kind}/{table}.jsonl.gz'] = digest_file(path)
            elif manifest['counts'].get(table, 0):
                raise SyncError('A bundle file is missing.')
    return files, manifests


def local_report(run, state):
    files, manifests = run_files(run, state)
    report = dict(contract_version=VERSION, mode='local-only', network_used=False,
        date_filter=state.get('date_filter'),
        planned_tables=list(TABLES), existing_row_policy='skip, even if changed', schema_changes=False,
        other_tables_written=[], file_sha256=files, warnings=state['warnings'],
        counts={kind: m['counts'] for kind, m in manifests.items()},
        limitations=['Focus telemetry is not exact hardware screen-on time.',
                    '04:00 cutoff is configurable; it does not detect actual sleep.',
                    'No writes to shared health summaries or existing Android/Garmin metrics.',
                    'Append-only daily totals do not grow when that same day is reimported.'])
    atomic_json(run / 'safety_report.json', report)
    # Draft only. The Python program has no database connection or SQL executor.
    registry = ['-- REVIEW ONLY: additive definitions. NOT executed by the uploader.',
                '-- No new tables, indexes, grants, RLS policies, or existing-row updates.', 'BEGIN;']
    for kind in state['bundles']:
        sql = (run / kind / 'setup.sql').read_text()
        registry.extend(line for line in sql.splitlines() if line.startswith('INSERT INTO public.'))
    registry.extend(['COMMIT;', ''])
    (run / 'registry_review.sql').write_text('\n'.join(registry), encoding='utf-8')
    return files


def preview(client, run, state, batch_size, target):
    files, _ = run_files(run, state)
    totals = {}
    for name in files:
        if not name.endswith('.jsonl.gz'):
            continue
        table = Path(name).name.split('.')[0]
        totals[name] = dict(submitted=0, would_insert=0, would_skip=0)
        for rows in batches(run / name, batch_size):
            result = client.import_batch(table, rows, preview=True)
            for k in totals[name]:
                totals[name][k] += result[k]
        print(f'  {name}: {totals[name]["would_insert"]:,} new; {totals[name]["would_skip"]:,} existing skipped', flush=True)
    if run_files(run, state)[0] != files:
        raise SyncError('Files changed during preview. No upload was made; preview a fresh snapshot.')
    plan = dict(version=1, contract_version=VERSION, user_id=client.user_id, project_ref=client.project_ref,
                target=target, batch_size=batch_size, files=files, totals=totals, warnings=state['warnings'],
                date_filter=state.get('date_filter'))
    approval = hashlib.sha256(json_text(plan).encode()).hexdigest()
    atomic_json(run / 'upload_plan.json', dict(plan=plan, approval_hash=approval))
    print(f'Project: {client.project_ref}\nUser: {client.user_id}\nApproval hash: {approval}')
    if state.get('date_filter'):
        print('Selected window (UTC): ' + json_text(state['date_filter']))
    print('Preview complete. No application data was inserted or changed.')
    return approval


def upload(client, run, state, batch_size, target, approval):
    saved = json.loads((run / 'upload_plan.json').read_text())
    plan = saved['plan']
    actual = hashlib.sha256(json_text(plan).encode()).hexdigest()
    if approval != actual or saved.get('approval_hash') != actual:
        raise SyncError('Approval hash does not match the saved preview.')
    if (plan['files'] != run_files(run, state)[0] or plan['user_id'] != client.user_id
            or plan['target'] != target or plan['project_ref'] != client.project_ref
            or plan['batch_size'] != batch_size or plan.get('contract_version') != VERSION
            or plan.get('date_filter') != state.get('date_filter')):
        raise SyncError('Files, batch size, project or user changed after preview; no upload attempted.')
    if state.get('target') not in (None, target) or state.get('user_id') not in (None, client.user_id):
        raise SyncError('The run was already uploaded to a different project or user.')
    state.update(target=target, user_id=client.user_id, status='uploading')
    atomic_json(run / 'sync_state.json', state)
    for name in plan['totals']:
        table = Path(name).name.split('.')[0]
        progress = state['progress'].get(name, dict(batches=0, submitted=0, inserted=0, skipped=0))
        for index, rows in enumerate(batches(run / name, batch_size)):
            if index < progress['batches']:
                continue
            result = client.import_batch(table, rows, preview=False)
            for k in ('submitted', 'inserted', 'skipped'):
                progress[k] += result[k]
            progress['batches'] = index + 1
            state['progress'][name] = progress
            atomic_json(run / 'sync_state.json', state)
            if index % 20 == 0:
                print(f'  {name}: {progress["submitted"]:,} rows acknowledged', flush=True)
    state['status'] = 'complete'
    atomic_json(run / 'sync_state.json', state)


def derive_body(lower, upper, zone):
    """The local dates the server should recompute: the nights and days the selected window covers."""
    body = dict(timeZone=str(zone))
    if upper is not None:
        body['until'] = (upper - timedelta(microseconds=1)).astimezone(zone).date().isoformat()
    if lower is not None:
        since = lower.astimezone(zone).date()
        if upper is not None:  # the server recomputes at most 400 days per request; the app looks at the last 70
            since = max(since, datetime.fromisoformat(body['until']).date() - timedelta(days=400))
        body['since'] = since.isoformat()
    return body


def derive(client, config, body):
    api = (config.get('STRESSLESS_API_URL') or '').strip()
    if not api:
        print('STRESSLESS_API_URL is not set: the app summaries (sleep scores, steps, heart rate) were not computed.\n'
              'Set it in .env, then run: python3 sync_apple.py --derive')
        return False
    print('Computing sleep scores, heart rate, activity and screen-time summaries on the server...', flush=True)
    result = client.derive(api, body)
    stored = result.get('stored') or {}
    print(f'  {result.get("since")} .. {result.get("until")}: ' + ', '.join(f'{v:,} {k.replace("_", " ")}' for k, v in stored.items()))
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='local-only (also the default)')
    mode.add_argument('--preview', action='store_true', help='validate batches online without writing application data')
    mode.add_argument('--upload', action='store_true', help='append new rows only; requires a saved approved preview')
    mode.add_argument('--check-connection', action='store_true', help='verify login, consent and standalone endpoint; no application-data writes')
    mode.add_argument('--derive', action='store_true', help='only (re)compute the app summaries from already uploaded raw data; '
                      '--since/--until pick the dates (default: the last 70 days)')
    parser.add_argument('--approve-plan', help='SHA256 printed by the reviewed online preview')
    parser.add_argument('--only', choices=['all', 'screen', 'health'], default='all')
    parser.add_argument('--health-export', type=Path, default=ROOT / 'apple_health_export')
    parser.add_argument('--screen-source', type=Path, default=screentime_export.DEFAULT_SOURCE)
    parser.add_argument('--screen-csv', type=Path, help='use an existing session CSV instead of collection')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'exports' / 'sync')
    parser.add_argument('--timezone', default='Europe/Stockholm')
    parser.add_argument('--day-start', default='04:00', type=lambda v: screentime_daily.day_start(v).strftime('%H:%M'))
    parser.add_argument('--since', help='inclusive date/time for BOTH sources; naive values use --timezone')
    parser.add_argument('--until', help='exclusive date/time for BOTH sources; Health is selected by record start')
    parser.add_argument('--allow-partial', action='store_true', help='explicitly permit upload of a snapshot with exclusions')
    parser.add_argument('--batch-size', type=int, default=500)
    parser.add_argument('--resume', type=Path, help='use a prepared contract-v3 snapshot without recollection')
    args = parser.parse_args(argv)
    run = state = None
    try:
        try:
            date_bounds(args.since, args.until, ZoneInfo(args.timezone))
        except (ValueError, KeyError) as exc:
            raise SyncError(str(exc)) from None
        if (args.resume or args.check_connection) and (args.since is not None or args.until is not None):
            raise SyncError('Date filters apply only when preparing a NEW run. Resume uses the saved selection; omit the filters.')
        if not 1 <= args.batch_size <= 500:
            raise SyncError('--batch-size must be between 1 and 500.')
        if args.upload and (not args.resume or not args.approve_plan):
            raise SyncError('--upload requires --resume RUN and --approve-plan HASH from an online preview.')
        if args.approve_plan and not args.upload:
            raise SyncError('--approve-plan is only valid with --upload.')
        if args.derive:
            config = read_config(args.env_file.expanduser())
            url, key, _ = settings(config)
            client = Client(url, key)
            client.login(config)
            zone = ZoneInfo(args.timezone)
            return 0 if derive(client, config, derive_body(*date_bounds(args.since, args.until, zone), zone)) else 1
        if args.check_connection:
            config = read_config(args.env_file.expanduser())
            url, key, _ = settings(config)
            client = Client(url, key)
            user_id = uuid_arg(client.login(config))
            info = client.preflight()
            print(f'Project: {info["project_ref"]}\nUser: {user_id}\nUploads enabled: {info["enabled"]}')
            print('Login, consent and append-only endpoint verified. No application data was written.')
            return 0
        if args.resume:
            run = args.resume.expanduser().resolve()
            state = json.loads((run / 'sync_state.json').read_text())
            run_files(run, state)
        else:
            run, state = build_run(args)
        if not args.upload:
            local_report(run, state)
        if not (args.preview or args.upload):
            print('Local export complete. No sign-in, network access or database changes.')
            print(f'Review: {run / "safety_report.json"}')
        else:
            if args.upload and state['warnings'] and not args.allow_partial:
                raise SyncError('This run has exclusions/warnings. Review them, then add --allow-partial if acceptable.')
            config = read_config(args.env_file.expanduser())
            url, key, target = settings(config)
            client = Client(url, key)
            user_id = uuid_arg(client.login(config))
            if config.get('SUPABASE_USER_ID') and uuid_arg(config['SUPABASE_USER_ID']) != user_id:
                raise SyncError('Signed-in user differs from optional SUPABASE_USER_ID; stopped.')
            info = client.preflight()
            if args.preview:
                preview(client, run, state, args.batch_size, target)
            else:
                if not info.get('enabled'):
                    raise SyncError('Server-side uploads are disabled. See the admin setup in README.md.')
                upload(client, run, state, args.batch_size, target, args.approve_plan)
                print('Append-only upload complete. Existing raw rows were not overwritten.')
                window = state.get('date_filter') or {}
                lower, upper = (parse_time(window.get(k)) for k in ('since', 'until'))
                derive(client, config, derive_body(lower, upper, ZoneInfo(state['timezone'])))
        for warning in state['warnings']:
            print('Warning: ' + warning)
        return 2 if state['warnings'] else 0
    except (Exception, KeyboardInterrupt) as exc:
        if run is not None and state is not None and state.get('status') == 'uploading':
            state['status'] = 'upload_failed'
            atomic_json(run / 'sync_state.json', state)
            print('Upload interrupted. Reuse the same run, batch size and approval hash to resume.', file=sys.stderr)
        if isinstance(exc, KeyboardInterrupt):
            print('Interrupted. Any acknowledged inserts remain; nothing is automatically deleted.', file=sys.stderr)
        elif isinstance(exc, (APIError, SyncError, argparse.ArgumentTypeError)):
            print(f'Error: {exc}', file=sys.stderr)
        else:
            print(f'Error: {type(exc).__name__}. Stopped; no credentials or record values were logged.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
