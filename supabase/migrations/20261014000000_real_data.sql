-- Real data for the whole app and the daily/weekly reports (design: docs/SCHEMA.md).
--
-- Three layers, all owned by one auth user and removed with them (on delete cascade):
--   sources & sync  provider_connections (one per user x provider x account or phone install) + connection_streams
--   raw             source_records: every record any source delivers, deduplicated on (user, source, record id)
--   derived         sleep_nights, heart_rate_days, daily_activity (what the engine reads), daily_metrics (any other
--                   per-day value), calendar_events
-- Registries (sources, data_types, metric_definitions) name what may exist, so a new source is new rows, not DDL.
--
-- Only the API writes data tables (service role); signed-in users can read their own rows. Nothing is dropped:
-- biometric_samples, event_analytics, media_events, user_events and narratives stay as they are, marked deprecated.
-- Needs Postgres 15+ (on delete set null with a column list).

-- --------------------------------------------------------------------------------------------------- registries --
create table if not exists public.sources (
  key      text primary key check (key ~ '^[a-z][a-z0-9_]{1,39}$'),
  label    text not null,
  category text not null check (category in ('calendar', 'health', 'media', 'screen', 'checkin', 'internal')),
  delivery text not null check (delivery in ('oauth', 'phone', 'file', 'manual', 'internal')),
  active   boolean not null default true               -- false: known (old rows may use it) but not offered
);

insert into public.sources (key, label, category, delivery, active) values
  ('google_calendar', 'Google Calendar',          'calendar', 'oauth',    true),
  ('health_connect',  'Health Connect (Android)', 'health',   'phone',    true),
  ('apple_health',    'Apple Health (iPhone)',    'health',   'phone',    true),
  ('stressless',      'StressLess',               'internal', 'internal', true),   -- accepted suggestions
  ('manual',          'Added by hand',            'internal', 'manual',   true),
  ('apple_calendar',  'Apple Calendar',           'calendar', 'phone',    false),  -- allowed by the old checks
  ('garmin',          'Garmin',                   'health',   'oauth',    false)
on conflict (key) do nothing;

-- What a raw record or a sync stream holds. Health Connect and HealthKit map onto the same keys, except HRV: RMSSD
-- (Health Connect) and SDNN (HealthKit) are different measures and never share a key.
create table if not exists public.data_types (
  key      text primary key check (key ~ '^[a-z][a-z0-9_]{1,39}$'),
  label    text not null,
  category text not null check (category in ('sleep', 'heart', 'vitals', 'activity', 'calendar', 'media', 'screen', 'checkin'))
);

insert into public.data_types (key, label, category) values
  ('sleep_session',      'Sleep',                    'sleep'),
  ('heart_rate',         'Heart rate',               'heart'),
  ('hrv_rmssd',          'Heart rate variability (RMSSD)', 'heart'),
  ('hrv_sdnn',           'Heart rate variability (SDNN)',  'heart'),
  ('resting_heart_rate', 'Resting heart rate',       'heart'),
  ('respiratory_rate',   'Respiratory rate',         'vitals'),
  ('oxygen_saturation',  'Blood oxygen',             'vitals'),
  ('skin_temperature',   'Skin temperature',         'vitals'),
  ('steps',              'Steps',                    'activity'),
  ('exercise',           'Workouts',                 'activity'),
  ('calendar_event',     'Calendar events',          'calendar')
on conflict (key) do nothing;

-- Keys of per-day values in daily_metrics; they become report Metric rows as they are ("screen.minutes"). Filled
-- by the migration that adds a source, e.g. ('screen.minutes', 'Screen time', 'min', 'down').
create table if not exists public.metric_definitions (
  key            text primary key check (key ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$'),
  label          text not null,
  unit           text not null check (length(unit) between 1 and 32),
  good_direction text not null default 'none' check (good_direction in ('up', 'down', 'zero', 'none'))
);

-- ------------------------------------------------------------------------------------------- sources and sync --
-- The allowed providers move from CHECK constraints to the sources registry. The old checks were made in the
-- dashboard, so they are found by column rather than by name.
do $$
declare c record;
begin
  for c in
    select rel.relname, con.conname
    from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace ns on ns.oid = rel.relnamespace
    join pg_attribute att on att.attrelid = rel.oid and att.attnum = con.conkey[1]
    where ns.nspname = 'public' and con.contype = 'c' and cardinality(con.conkey) = 1 and att.attname = 'provider'
      and rel.relname in ('provider_connections', 'calendar_events')
  loop
    execute format('alter table public.%I drop constraint %I', c.relname, c.conname);
  end loop;
end $$;

alter table public.provider_connections drop constraint if exists provider_connections_provider_fkey;
alter table public.provider_connections add constraint provider_connections_provider_fkey
  foreign key (provider) references public.sources (key);

-- Phones: provider_account_id is an install id the app generates, so every phone is its own connection.
alter table public.provider_connections
  add column if not exists device_label text check (length(device_label) <= 80),           -- "Pixel 8"
  add column if not exists platform     text check (platform in ('android', 'ios', 'web')),
  add column if not exists time_zone    text check (length(time_zone) <= 64),              -- last zone the device reported
  add column if not exists last_error   text check (length(last_error) <= 500);

-- Lets the tables below require that a row's connection belongs to the same user.
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'provider_connections_id_user_key') then
    alter table public.provider_connections add constraint provider_connections_id_user_key unique (id, user_id);
  end if;
end $$;

-- Sync state per connection and data type: feeds the readiness dialog (SourceStatus) and explains gaps.
create table if not exists public.connection_streams (
  connection_id  uuid not null,
  user_id        uuid not null default auth.uid() references auth.users (id) on delete cascade,
  data_type      text not null references public.data_types (key),
  permitted      boolean not null default true,         -- Health Connect / HealthKit permissions are per type
  data_from      timestamptz,                           -- oldest data the source could give (30-day limit on Android)
  data_until     timestamptz,                           -- newest data point held: "data available up to"
  last_synced_at timestamptz,
  updated_at     timestamptz not null default now(),
  primary key (connection_id, data_type),
  foreign key (connection_id, user_id) references public.provider_connections (id, user_id) on delete cascade
);
create index if not exists connection_streams_user_idx on public.connection_streams (user_id);

-- ------------------------------------------------------------------------------------------------------- raw --
-- Every record a source delivers, kept until the account is deleted so summaries can be recomputed. Health Connect
-- deletions carry only the record id, hence the unique key without data_type. A deleted connection keeps its
-- records (connection_id becomes null): Health Connect cannot re-read history older than 30 days.
create table if not exists public.source_records (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null default auth.uid() references auth.users (id) on delete cascade,
  connection_id      uuid,
  source             text not null references public.sources (key),
  data_type          text not null references public.data_types (key),
  source_record_id   text not null check (length(source_record_id) between 1 and 200),
  data_origin        text check (length(data_origin) <= 200),         -- app that measured it: com.garmin.android...
  start_at           timestamptz not null,
  end_at             timestamptz,                                     -- null for a point reading
  start_offset_min   smallint check (start_offset_min between -840 and 840),
  end_offset_min     smallint check (end_offset_min between -840 and 840),
  value              numeric,                                         -- point readings and totals
  unit               text check (length(unit) between 1 and 32),
  payload            jsonb not null default '{}'::jsonb,              -- stages, samples [{t, bpm}], ...; no free text
  source_modified_at timestamptz,                                     -- Health Connect lastModifiedTime
  received_at        timestamptz not null default now(),
  check (end_at is null or end_at >= start_at),
  unique (user_id, source, source_record_id),
  foreign key (connection_id, user_id) references public.provider_connections (id, user_id) on delete set null (connection_id)
);
create index if not exists source_records_user_type_start_idx on public.source_records (user_id, data_type, start_at);

-- --------------------------------------------------------------------------------------------------- derived --
-- Written by the API when data arrives, for the nights and days it touches. One row per user and local date, so a
-- report reads about 70 rows per table. Origins are chosen per data type (profiles.preferred_origins first).

-- The night that starts on the evening of night_date (engine: SleepNight). No row = the watch was not worn.
create table if not exists public.sleep_nights (
  user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
  night_date        date not null,
  source            text not null references public.sources (key),
  data_origin       text check (length(data_origin) <= 200),
  utc_offset_min    smallint not null check (utc_offset_min between -840 and 840),
  in_bed_at         timestamptz,
  onset_at          timestamptz,
  wake_at           timestamptz,
  out_of_bed_at     timestamptz,
  asleep_min        smallint not null default 0 check (asleep_min >= 0),   -- core + deep + rem
  deep_min          smallint not null default 0 check (deep_min >= 0),
  rem_min           smallint not null default 0 check (rem_min >= 0),
  core_min          smallint not null default 0 check (core_min >= 0),
  awake_min         smallint not null default 0 check (awake_min >= 0),
  interruptions     smallint not null default 0 check (interruptions >= 0),
  has_stages        boolean not null default false,                         -- false: phone-only, duration only
  stages            jsonb not null default '[]'::jsonb,                     -- [{kind, start, end}], kind in STAGE_KINDS
  hrv_rmssd_ms      real,
  hrv_sdnn_ms       real,
  resting_hr        smallint,
  resp_rate         real,
  spo2              real,
  skin_temp_dev     real,                                                   -- degC vs personal baseline
  score             smallint check (score between 0 and 100),
  score_parts       jsonb not null default '{}'::jsonb,
  score_source      text not null default 'stressless',
  algorithm_version text not null default 'v1',
  computed_at       timestamptz not null default now(),
  primary key (user_id, night_date)
);

-- Minute-level heart rate for one local day (engine: HeartRateDay). bpm[i] is minute i-1 of the local wall clock
-- (1-based arrays); null = not worn. DST days keep 1440 entries.
create table if not exists public.heart_rate_days (
  user_id        uuid not null default auth.uid() references auth.users (id) on delete cascade,
  day            date not null,
  source         text not null references public.sources (key),
  data_origin    text check (length(data_origin) <= 200),
  utc_offset_min smallint not null check (utc_offset_min between -840 and 840),
  bpm            smallint[] not null check (cardinality(bpm) = 1440),
  worn_minutes   smallint not null check (worn_minutes between 0 and 1440),
  computed_at    timestamptz not null default now(),
  primary key (user_id, day)
);

-- Steps and workouts for one local day (engine: DailyActivity).
create table if not exists public.daily_activity (
  user_id        uuid not null default auth.uid() references auth.users (id) on delete cascade,
  day            date not null,
  source         text not null references public.sources (key),
  utc_offset_min smallint not null check (utc_offset_min between -840 and 840),
  steps          integer check (steps >= 0),
  active_min     smallint check (active_min >= 0),
  hourly_steps   integer[] not null default '{}' check (cardinality(hourly_steps) in (0, 24)),
  workouts       jsonb not null default '[]'::jsonb,   -- [{kind, start, end, avg_hr, max_hr, calories, data_origin}]
  computed_at    timestamptz not null default now(),
  primary key (user_id, day)
);

-- Any other per-day value (screen time, music minutes, caffeine check-ins, ...): the extension point. Adding a
-- source means adding metric_definitions rows, not columns.
create table if not exists public.daily_metrics (
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  day         date not null,
  metric_key  text not null references public.metric_definitions (key),
  value       numeric not null,
  source      text not null references public.sources (key),
  computed_at timestamptz not null default now(),
  primary key (user_id, day, metric_key)
);

-- Calendar events: providers from the registry, the connection they came through (kept when it is replaced, as a
-- Google reconnect does), and what the engine needs besides the type in category.
alter table public.calendar_events drop constraint if exists calendar_events_provider_fkey;
alter table public.calendar_events add constraint calendar_events_provider_fkey
  foreign key (provider) references public.sources (key);

alter table public.calendar_events
  add column if not exists connection_id  uuid,
  add column if not exists recurring_key  text check (length(recurring_key) <= 200),   -- Google recurringEventId
  add column if not exists attendee_count integer generated always as
    (case when jsonb_typeof(guests) = 'array' then jsonb_array_length(guests) else 0 end) stored;

alter table public.calendar_events drop constraint if exists calendar_events_connection_fkey;
alter table public.calendar_events add constraint calendar_events_connection_fkey
  foreign key (connection_id, user_id) references public.provider_connections (id, user_id) on delete set null (connection_id);

-- Engine event types (models.EVENT_TYPES). NOT VALID: checked for new and changed rows only, not prototype rows.
alter table public.calendar_events drop constraint if exists calendar_events_category_type_check;
alter table public.calendar_events add constraint calendar_events_category_type_check
  check (category in ('meeting', 'focus', 'workout', 'social', 'travel', 'personal', 'protected', 'uncategorized')) not valid;

-- The redundant second unique key from the dashboard (same columns as the table's own unique key).
do $$
begin
  if exists (select 1 from pg_constraint where conname = 'calendar_events_provider_event_unique'
             and conrelid = 'public.calendar_events'::regclass) then
    alter table public.calendar_events drop constraint calendar_events_provider_event_unique;
  else
    drop index if exists public.calendar_events_provider_event_unique;
  end if;
end $$;

-- Calendar rows are written only by the API now (Google sync, accepted suggestions).
drop policy if exists calendar_events_insert_own on public.calendar_events;
drop policy if exists calendar_events_update_own on public.calendar_events;
drop policy if exists calendar_events_delete_own on public.calendar_events;
revoke all on public.calendar_events from anon;
revoke insert, update, delete on public.calendar_events from authenticated;

-- ------------------------------------------------------------------------------------- user state and settings --
alter table public.profiles
  add column if not exists time_zone         text not null default 'Europe/Stockholm'
                                             check (length(time_zone) between 1 and 64),   -- IANA, checked by the API
  add column if not exists consented_at      timestamptz,   -- sign-up consent; null = no uploads, no Claude calls
  add column if not exists preferred_origins jsonb not null default '{}'::jsonb
                                             check (jsonb_typeof(preferred_origins) = 'object');   -- {data_type: origin}

-- A ready report always has its content, a pending one never does.
alter table public.reports drop constraint if exists reports_ready_has_report;
alter table public.reports add constraint reports_ready_has_report check ((status = 'ready') = (report is not null));

-- -------------------------------------------------------------------------------------- row-level security --
do $$
declare t text;
begin
  -- Registries: readable by every signed-in user, changed only by migrations.
  foreach t in array array['sources', 'data_types', 'metric_definitions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_read', t);
    execute format('create policy %I on public.%I for select to authenticated using (true)', t || '_read', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
  end loop;

  -- User data: each user reads their own rows; only the API (service role) writes.
  foreach t in array array['connection_streams', 'source_records', 'sleep_nights', 'heart_rate_days',
                           'daily_activity', 'daily_metrics'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I on public.%I', t || '_read_own', t);
    execute format('create policy %I on public.%I for select to authenticated using (user_id = (select auth.uid()))',
                   t || '_read_own', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
  end loop;
end $$;

-- ------------------------------------------------------------------------------------------------- comments --
comment on table public.sources is 'Registry: every provider a connection, record or event can come from.';
comment on table public.data_types is 'Registry: kinds of raw records and sync streams.';
comment on table public.metric_definitions is 'Registry: keys of daily_metrics, used as report Metric keys.';
comment on table public.connection_streams is 'Sync state per connection and data type (readiness dialog).';
comment on table public.source_records is 'Raw records from every source, deduplicated on (user_id, source, source_record_id).';
comment on table public.sleep_nights is 'Derived: one row per night (night_date = evening it starts). Written by the API.';
comment on table public.heart_rate_days is 'Derived: 1440 per-minute bpm values per local day. Written by the API.';
comment on table public.daily_activity is 'Derived: steps, hourly steps and workouts per local day. Written by the API.';
comment on table public.daily_metrics is 'Derived: any other per-day value, keyed by metric_definitions.';
comment on table public.biometric_samples is 'Deprecated: replaced by source_records and the derived tables.';
comment on table public.event_analytics is 'Deprecated: per-event analysis is out of scope.';
comment on table public.media_events is 'Deprecated: media sources will use source_records and daily_metrics.';
comment on table public.user_events is 'Development demo only: events added on top of the simulated dataset.';
comment on table public.narratives is 'Development demo only: replaced by reports.';
