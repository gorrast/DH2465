-- Baseline of the integration tables that were created in the Supabase dashboard, written down from the live
-- project (columns, constraints, indexes and policies as of 2026-10-12) so the repo matches the database.
-- Safe to run against that project: everything is "if not exists" or dropped and recreated identically.
--
-- Not captured here: table grants (Supabase's defaults apply), the dashboard-managed rls_auto_enable event
-- trigger, and a second, redundant unique index on calendar_events (calendar_events_provider_event_unique).

-- A user's link to an outside account. Written only by the server (service role); users can read their own.
create table if not exists public.provider_connections (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null default auth.uid() references auth.users (id) on delete cascade,
  provider            text not null check (provider in ('apple_health', 'garmin', 'google_calendar', 'apple_calendar')),
  provider_account_id text,
  status              text not null default 'pending' check (status in ('pending', 'connected', 'revoked', 'error')),
  scopes              text[] not null default '{}',
  connected_at        timestamptz,
  last_synced_at      timestamptz,
  created_at          timestamptz not null default now(),
  unique (user_id, provider, provider_account_id)
);

-- The secrets behind a connection. No policies: nothing but the service role can read or write it.
create table if not exists public.provider_connection_credentials (
  provider_connection_id   uuid primary key references public.provider_connections (id) on delete cascade,
  oauth_state_hash         text unique,              -- sha-256 of the pending OAuth state, cleared once used
  oauth_state_created_at   timestamptz,
  refresh_token_ciphertext text,                     -- AES-GCM, key held by the API (GOOGLE_TOKEN_ENCRYPTION_KEY)
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  check ((oauth_state_hash is null and oauth_state_created_at is null)
      or (oauth_state_hash is not null and oauth_state_created_at is not null))
);

create table if not exists public.calendar_events (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
  provider          text not null check (provider in ('google_calendar', 'apple_calendar', 'manual')),
  provider_event_id text,
  title             text,
  category          text not null default 'uncategorized' check (length(category) between 1 and 80),
  starts_at         timestamptz not null,
  ends_at           timestamptz not null,
  location          text,
  description       text,
  guests            jsonb not null default '[]'::jsonb,
  created_at        timestamptz not null default now(),
  check (ends_at > starts_at),
  unique (user_id, provider, provider_event_id)
);
create index if not exists calendar_events_user_start_idx on public.calendar_events (user_id, starts_at);

create table if not exists public.biometric_samples (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null default auth.uid() references auth.users (id) on delete cascade,
  provider         text not null check (provider in ('apple_health', 'garmin', 'manual')),
  metric_type      text not null check (length(metric_type) between 1 and 80),
  value            numeric not null,
  unit             text not null check (length(unit) between 1 and 32),
  measured_at      timestamptz not null,
  source_record_id text,
  created_at       timestamptz not null default now(),
  unique (user_id, provider, metric_type, measured_at, source_record_id)
);
create index if not exists biometric_samples_user_metric_time_idx on public.biometric_samples (user_id, metric_type, measured_at);
create index if not exists biometric_samples_user_time_idx on public.biometric_samples (user_id, measured_at desc);

-- Per-event statistics of a biometric before, during and after the event. Users can read their own.
create table if not exists public.event_analytics (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null default auth.uid() references auth.users (id) on delete cascade,
  calendar_event_id uuid not null references public.calendar_events (id) on delete cascade,
  metric_type       text not null check (length(metric_type) between 1 and 80),
  window_label      text not null check (window_label in ('before', 'during', 'after')),
  sample_count      integer not null check (sample_count >= 0),
  mean_value        numeric,
  median_value      numeric,
  min_value         numeric,
  max_value         numeric,
  algorithm_version text not null default 'v1',
  computed_at       timestamptz not null default now(),
  unique (calendar_event_id, metric_type, window_label, algorithm_version)
);
create index if not exists event_analytics_user_event_idx on public.event_analytics (user_id, calendar_event_id);

create table if not exists public.media_events (
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  id          text not null,
  provider    text not null check (provider in ('spotify', 'netflix')),
  title       text not null,
  creator     text,
  occurred_at timestamptz not null,
  minutes     numeric not null default 0 check (minutes >= 0),
  source      jsonb not null default '{}'::jsonb,
  imported_at timestamptz not null default now(),
  primary key (user_id, id)
);

-- Row-level security: on for every table; the policies below are the only access signed-in users have.
do $$
declare
  t text;
  own constant text := '((select auth.uid()) is not null and user_id = (select auth.uid()))';
begin
  foreach t in array array['provider_connections', 'provider_connection_credentials', 'calendar_events',
                           'biometric_samples', 'event_analytics', 'media_events'] loop
    execute format('alter table public.%I enable row level security', t);
  end loop;

  foreach t in array array['provider_connections', 'event_analytics', 'calendar_events', 'biometric_samples'] loop
    execute format('drop policy if exists %I on public.%I', t || '_read_own', t);
    execute format('create policy %I on public.%I for select to authenticated using %s', t || '_read_own', t, own);
  end loop;

  foreach t in array array['calendar_events', 'biometric_samples'] loop
    execute format('drop policy if exists %I on public.%I', t || '_insert_own', t);
    execute format('create policy %I on public.%I for insert to authenticated with check %s', t || '_insert_own', t, own);
    execute format('drop policy if exists %I on public.%I', t || '_update_own', t);
    execute format('create policy %I on public.%I for update to authenticated using %s with check %s', t || '_update_own', t, own, own);
    execute format('drop policy if exists %I on public.%I', t || '_delete_own', t);
    execute format('create policy %I on public.%I for delete to authenticated using %s', t || '_delete_own', t, own);
  end loop;
end $$;

drop policy if exists "own media events" on public.media_events;
create policy "own media events" on public.media_events for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
