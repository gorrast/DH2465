# StressLess database schema

How the Supabase database holds real data for the whole app and the daily and weekly AI reports. The SQL is in
`supabase/migrations/`; this document explains it. Decided 2026-10-14 from the schema-design handoffs (backend port,
Health Connect app, report generation).

StressLess is a course demo for invited friends and family, so the schema favours few tables and simple rules over
completeness. Supabase is used only for auth and storage. All logic lives in the FastAPI backend (`/api/*`), and the
web app never queries tables directly.

## Decisions

| Topic | Decision |
|---|---|
| Scope | The whole app (Morning, Week, Replay, Reality, Planner, Habits, reports) runs on real data. The simulated personas stay for development only, behind an environment flag on the API. |
| Analysis | The per-night engine plus LLM-written reports. No per-event before/during/after statistics. |
| Sources now | Google Calendar (OAuth, server pull), Health Connect (Android app) and HealthKit (iOS app). |
| Sources later | Spotify/Netflix, screen time and manual check-ins, added without schema redesign (see [Adding a source](#adding-a-source)). |
| Out of scope | Location (raw pings and visits). Very sensitive, and visits need clustering plus a place lookup. |
| Ingestion | The phone app posts raw records to FastAPI with the user's Supabase access token (Supabase login inside the app). The API validates, deduplicates, stores and summarises. |
| Writes | Only the API writes data tables, using the service role. Users can read their own rows through RLS, as a safety net. |
| Reports | Stay on the user's JWT, so the database enforces the one-claim-per-period rule (`20261008000000_reports.sql`). |
| Raw data | Kept until the account is deleted, so summaries can be recomputed when an algorithm changes. |
| Heart rate | Derived into one row per local day holding 1440 per-minute values. |
| Overlapping apps | Picked automatically per data type. The user can pin a preferred app (`profiles.preferred_origins`). |
| Devices | One connection per phone install. One calendar source per user, enforced in code. |
| Consent | One timestamp, `profiles.consented_at`, set from a sign-up checkbox. While it is null, the API accepts no uploads and makes no Claude calls. |
| Deletion | "Delete account" removes the auth user, and every table cascades, reports included. Disconnecting Google removes its events, as already built. |
| Suggestions | Stored in StressLess only, as a `calendar_events` row with provider `stressless`, plus the .ics download. Google stays read-only. |
| Sync tokens | Health Connect changes tokens and HealthKit anchors stay on the phone. A reinstall re-reads everything, and the raw unique key makes that harmless. |
| Sleep score | Always computed by StressLess when data arrives (`score_source`, `algorithm_version`). Neither platform exposes one. |
| Baselines | Usual resting HR, breathing rate, sleep need, bed and wake times are computed from history, not stored. |
| Heart rate | The app averages Health Connect samples to one per minute; `heart_rate_days` merges each sync into the stored day. HRV and skin temperature are not collected. |
| Local time | `profiles.time_zone` (IANA) defines "today", "last night" and the Monday-to-Sunday week. Night D starts on the evening of local date D. Every derived row stores the UTC offset it used. |

## Layers

```
 phone app ──POST /api/ingest──┐        Google ──OAuth pull──┐
                               ▼                             ▼
 ┌─ sources & sync ─────────────────────────────────────────────────────────┐
 │ provider_connections (user × provider × account/install)                 │
 │   ├─ provider_connection_credentials   (service role only)               │
 │   └─ connection_streams (per data type: permitted, data_until, synced)   │
 └──────────────────────────────────────────────────────────────────────────┘
                               ▼
 ┌─ raw ────────────────────────────────────────────────────────────────────┐
 │ source_records  unique (user_id, source, source_record_id), payload jsonb│
 └──────────────────────────────────────────────────────────────────────────┘
                               ▼  API recomputes the days it touched
 ┌─ derived (what the engine and reports read, ~70 rows per table) ─────────┐
 │ sleep_nights · heart_rate_days · daily_activity · daily_metrics          │
 │ calendar_events (Google sync writes here directly; no raw copy)          │
 └──────────────────────────────────────────────────────────────────────────┘
                               ▼
 reports (one row per user × kind × period; claimed before the model is called)

 registries: sources · data_types · metric_definitions      settings: profiles
```

## Tables

### Registries

They are read by every signed-in user and changed only by migrations. Foreign keys point at them instead of CHECK
lists, so a new source means new rows, not ALTERs on several tables.

| Table | Key | Holds |
|---|---|---|
| `sources` | `key` | Every provider: `google_calendar`, `health_connect`, `apple_health`, `stressless` (accepted suggestions), `manual`, plus the legacy `apple_calendar` and `garmin` (`active = false`). Also `category` and `delivery` (oauth, phone, file, manual, internal). |
| `data_types` | `key` | Raw record and sync-stream kinds: `sleep_session`, `heart_rate`, `resting_heart_rate`, `respiratory_rate`, `oxygen_saturation`, `steps`, `exercise`, `calendar_event`. |
| `metric_definitions` | `key` (`screen.minutes`) | Keys allowed in `daily_metrics`, with label, unit and good direction. These are the report's `Metric` keys. It starts empty. |

### Sources and sync

- **`provider_connections`** (evolved): `provider` references `sources`. For phones, `provider_account_id` is an
  install id that the app generates, so each phone is its own row. New columns: `device_label`, `platform`
  (`android`, `ios`, `web`), `time_zone` (the last zone the device reported) and `last_error`. A unique `(id,
  user_id)` key lets child tables require a connection that belongs to the same user.
- **`provider_connection_credentials`** (unchanged): the encrypted OAuth refresh token. It has no policies, so only
  the service role can read it.
- **`connection_streams`**: one row per connection and data type, with `permitted`, `data_from`, `data_until` and
  `last_synced_at`. It feeds `SourceStatus` in the readiness dialog: "sleep not permitted", "data available up to
  …", "updated …", and why history is short (`data_from`). Google Calendar writes one `calendar_event` stream.

### Raw: `source_records`

One row per record from any source. Columns: `source`, `data_type`, `source_record_id` (not null), `data_origin`
(the app that measured it, e.g. `com.garmin.android.apps.connectmobile`), `start_at`/`end_at` with zone offsets in
minutes, `value`/`unit` for point readings, `payload jsonb` for the rest (sleep stages, heart-rate samples with
timestamps, workout details), `source_modified_at`, and `received_at`.

- The unique key `(user_id, source, source_record_id)` has no `data_type`, because a Health Connect deletion
  carries only the record id. Upserts keep the newer `source_modified_at`.
- When a connection is deleted, its records stay with `connection_id` set to null. Health Connect cannot re-read
  history older than 30 days, so a reinstall or reconnect must never wipe what is already stored.
- No free text is stored: no sleep titles or notes, no workout GPS routes.

### Derived

The API writes these when data arrives, for the local dates it touched, picking one origin per data type. Each row
is one local date, so the 70-day history a report needs is one query of about 70 rows per table.

| Table | Key | Engine type | Notes |
|---|---|---|---|
| `sleep_nights` | `(user_id, night_date)` | `SleepNight` | Times (in bed, onset, wake, out of bed), minutes per stage, interruptions, `stages jsonb`, `has_stages`, resting HR, respiratory rate, SpO2 (measured while asleep), `score`, `score_parts`, `algorithm_version`. No row means the watch was not worn. |
| `heart_rate_days` | `(user_id, day)` | `HeartRateDay` | `bpm smallint[1440]`, where `bpm[i]` is minute i-1 of the local wall clock and null means not worn. DST days keep 1440 entries. Plus `worn_minutes`. |
| `daily_activity` | `(user_id, day)` | `DailyActivity` | `steps`, `active_min`, `hourly_steps` (24 or empty), `workouts jsonb` (`WatchWorkout` fields plus `data_origin`). |
| `daily_metrics` | `(user_id, day, metric_key)` | report `Metric` | Any other per-day value. `metric_key` references `metric_definitions`. This is the extension point. |
| `calendar_events` | `id`; unique `(user_id, provider, provider_event_id)` | `CalendarEvent` | Evolved. `category` holds the engine event type (a NOT VALID check, so new rows only). New: `connection_id` (set to null when the connection goes), `recurring_key`, and a generated `attendee_count` from `guests`. Users can no longer write these rows directly. |

Origin choice per data type: if `profiles.preferred_origins` names an app that has data that day, it wins.
Otherwise the most complete origin wins: the one with sleep stages, the most heart-rate samples, or a watch over
the phone for steps.

### Settings and user state

- **`profiles`** (evolved): new `time_zone` (default `Europe/Stockholm`; the browser sets it, and the API validates
  it against IANA names), `consented_at` and `preferred_origins` (`{data_type: data_origin}`). `persona`, `seed` and
  `anchor` remain for development mode. Users still edit their own row, which is how the consent checkbox is saved.
- **`answers`** (unchanged): reality-check answers. With real data, `event_id` is a `calendar_events.id`. Whether
  the Reality view survives without location is still open.
- **`accepted`** (unchanged): suggestion id → the `calendar_events.id` (provider `stressless`) it created.
- **`reports`** (from `feat/report-generation`): unchanged, plus a check that `status = 'ready'` exactly when
  `report` is not null.

### Deprecated and dropped tables

`biometric_samples` and `event_analytics` were dropped on 2026-10-15 (`20261015000000_drop_unused_tables.sql`).
They were empty and unused: `source_records` plus the derived tables replace the first, and per-event analysis is
out of scope.

| Table | Status |
|---|---|
| `media_events`, `media_documents` | Kept. The collaborator's Spotify/Netflix import writes to them from outside this repo (`media_documents` exists only in the dashboard). Moving it to `source_records` + `daily_metrics` is to be agreed with them. |
| `user_events`, `narratives` | Simulated dataset only. Drop them in the same change that removes the simulation from the API, because `stressless_state()` and `stressless_clear_state()` still use them. |

### Access rules

| Tables | Signed-in user | API |
|---|---|---|
| Registries | read | migrations only |
| `connection_streams`, `source_records`, derived tables, `calendar_events`, `provider_connections` | read own | service role |
| `provider_connection_credentials` | nothing | service role |
| `profiles`, `answers`, `accepted` | read and write own | user JWT, as today |
| `reports` | read own, claim `pending`, finish own `pending` | user JWT |

Every `user_id` references `auth.users` with `on delete cascade`, so deleting the auth user deletes everything.
`anon` has no access to any of these tables.

## What each part of the app reads

| Consumer | Reads |
|---|---|
| Readiness dialog | `provider_connections` + `connection_streams` (`data_until`, `last_synced_at`, `permitted`) |
| Daily report, Morning | `sleep_nights` (last night plus 70 days of history), `heart_rate_days`, `daily_activity`, `calendar_events` (yesterday and today), `daily_metrics`, `answers`, `profiles.time_zone`; then `reports` |
| Weekly report, Week | The same over Monday to Sunday plus 6 weeks for habits; then `reports` |
| Replay | `heart_rate_days`, `calendar_events`, `sleep_nights`, `daily_activity` for one day. The location lane stays empty. |
| Reality | `calendar_events`, `heart_rate_days`, `daily_activity.workouts`, `answers` |
| Planner, what-if | `calendar_events` (Google sync covers 90 days ahead), `accepted`, the history above |
| Habits | `sleep_nights` + `calendar_events` over 6 weeks |
| Lab | Development demo only |

The engine's `Dataset` is built from these rows the way `connectors/build.py` builds one from imported files. The
`Persona` of a real user is just a name and `profiles.time_zone`; the baselines come from history.

## Ingest flow (phone)

1. The app reads changes per data type from Health Connect or HealthKit and posts a batch to the API: the install
   id, device zone, permissions per type, upserted records, and ids of deleted records.
2. The API checks `profiles.consented_at` and upserts the connection and its `connection_streams`.
3. It upserts `source_records`, keeping the newer `source_modified_at`, and deletes records by
   `(user, source, source_record_id)`.
4. It collects the local dates that the changed records touch.
5. It recomputes `sleep_nights`, `heart_rate_days`, `daily_activity` and `daily_metrics` for those dates.
6. It sets `data_until` and `last_synced_at`.

## Adding a source

Example: Spotify listening time.

1. Write a migration that inserts rows:
   - in `sources`: `('spotify', 'Spotify', 'media', 'oauth', true)`
   - in `data_types`: `('track_play', 'Songs played', 'media')`
   - in `metric_definitions`: `('media.music_min', 'Music', 'min', 'none')` and
     `('media.late_music_min', 'Music after 22:00', 'min', 'down')`
2. Add a connector that upserts `source_records` (one per play, keyed by the played-at time plus the track id)
   and a stream row in `connection_streams`.
3. Add a summariser that writes those keys into `daily_metrics`.
4. The report builder turns `daily_metrics` rows into `Metric` rows by key. The report schemas, the model and the
   tables need no change.

Screen time and manual check-ins follow the same recipe. Check-ins use source `manual` and the app's own record ids.
A view that needs time spans (a song at 23:40) reads `source_records` for that day.

## Code changes this schema needs (later sessions)

- `server/calendar.py`:
  - write `connection_id` and `recurring_key` (Google `recurringEventId`)
  - write a `calendar_event` stream row on sync
  - mirror the changes in `tests/test_calendar.py`
- An ingest endpoint for the phone app, with the origin rules and the summarisers.
- A store interface for the real-data `Dataset`, alongside the report store methods.
- An account-deletion endpoint: revoke Google tokens, then delete the auth user through the Admin API.
- The consent checkbox and the `time_zone` setting on the web app.
- Phone app:
  - Supabase login and the upload calls
  - raw sleep and workout records with stages and heart-rate timestamps
  - the extra Health Connect permissions (history beyond 30 days, background reads); heart rate, resting HR, respiratory rate and SpO2 are synced

## Open items

- Whether the Reality view stays, using the watch only, now that location is out.
- Per-event analysis, if the collaborator wants it back. It can be computed from `heart_rate_days` with no new
  table.
- Dropping `user_events` and `narratives` together with the simulated dataset, and the future of the media tables.

## Testing and applying

`tools/schema_rollback_test.sh > /tmp/schema_test.sql` prints one script:

- every migration, in order
- then `supabase/tests/schema_checks.sql`
- all inside one transaction that always ends in an error, so nothing is ever committed

To test, paste the file into the SQL editor of the live project. The expected result is the error
`ALL SCHEMA CHECKS PASSED (everything was rolled back on purpose)`; any other error names the failing check.
Afterwards, `select to_regclass('public.source_records')` returns null.

The checks cover:
- users see only their own rows and cannot write to data tables
- duplicate record ids, unknown sources and unknown metric keys are rejected
- `attendee_count` is computed
- the report claim rules hold
- deleting a connection keeps its records
- deleting an account cascades everywhere

The migrations are idempotent. Applying them for real means running the migration files in order in the SQL editor,
or having the project owner do it. That step is separate and has not been done.
