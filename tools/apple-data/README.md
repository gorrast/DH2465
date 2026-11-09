# Apple data importer

Copy this folder into your repo as `tools/apple-data/`. Run commands from
inside it. Requires **Python 3.10+**, with no extra packages.

## Extract

- **Screen Time:** give the terminal Full Disk Access in macOS Privacy &
  Security, then restart it. Run `python3 screentime_export.py --list-devices`
  to check for files. Apple’s private Biome format can vary by macOS version;
  a successful local export is the compatibility check. Only activity retained
  on this Mac is available, including phone data that has already synced.
- **Health:** extract your Apple Health export and put `export.xml` under
  `apple_health_export/`, or pass its path with `--health-export`.

```sh
python3 sync_apple.py --since YYYY-MM-DDT04:00:00 --until YYYY-MM-DDT04:00:00 --timezone Europe/Stockholm
```

Replace the date and timezone examples. The start is inclusive and the end is
exclusive. Use `--only health` or `--only screen` for one source. This step
stays local and prints a run folder under `exports/sync/`. Review its
`safety_report.json` before uploading.

## Preview and upload

Copy `.env.example` to `.env` and fill in the public Supabase URL/key and your
app login. Leave the password blank for a private prompt, or use an app session
token for OAuth sign-in. No database password or elevated key goes on your Mac.
Never commit `.env` or personal exports.

```sh
python3 sync_apple.py --check-connection
python3 sync_apple.py --preview --resume exports/sync/YOUR_RUN
python3 sync_apple.py --upload --resume exports/sync/YOUR_RUN --approve-plan YOUR_HASH
```

Preview sends data for validation but inserts no application rows. Verify the
project, account, dates and counts. Run the upload only after admin approval and
when writes are enabled. Existing rows are skipped, not replaced; an interrupted
run may have committed some batches.

## One-time Supabase admin setup

Test in staging first. This expects the app’s existing schema, including unique
keys `source_records(user_id, source, source_record_id)` and
`daily_metrics(user_id, day, metric_key)`. Do not change table grants/RLS or run
`supabase db push`.

1. Set Edge Function secrets `APPLE_IMPORT_USER_IDS` (comma-separated approved
   app-user UUIDs) and `APPLE_IMPORT_ENABLED=false`. Each account needs app consent.
2. From this folder, use the Supabase CLI to deploy only
   `supabase functions deploy apple-import --project-ref YOUR_PROJECT_REF --use-api`.
   Review any existing deployment before replacing it. Keep JWT verification on.
3. Review the run’s `registry_review.sql`. Apply it only if Apple definitions are
   missing. After a successful preview, set `APPLE_IMPORT_ENABLED=true` for the
   approved upload; set it back to `false` afterward.

## App summaries

The upload itself only adds raw records. When it finishes, the importer calls
the StressLess API (`STRESSLESS_API_URL` in `.env`) at `POST /api/apple/derive`,
which reads those raw records back and computes what the app uses, the same
tables an Android phone sync fills:

- `sleep_nights`: one scored night per date, with stages and the overnight
  HRV (SDNN), resting heart rate, breathing rate, blood oxygen and wrist
  temperature deviation
- `heart_rate_days`: per-minute heart rate
- `daily_activity`: steps, hourly steps, exercise minutes and workouts (with
  heart rate and calories)
- `daily_metrics`: `screen.minutes` and `screen.late_minutes`, plus the
  Apple-only `health.*` values (active energy, exercise minutes, stand hours,
  VO2 max, walking heart rate, daytime HRV, mindful minutes; migration
  `20261109000000_apple_health_metrics.sql`)

It overwrites the computed rows for the dates it covers and can be repeated,
for example after uploading more data or when the URL was not set:

```sh
python3 sync_apple.py --derive --since 2026-09-01 --until 2026-11-01
```
