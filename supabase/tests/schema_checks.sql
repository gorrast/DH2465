-- Checks for the schema in supabase/migrations. Not meant to be run on its own: tools/schema_rollback_test.sh wraps
-- it after every migration in one transaction that always ends in an error, so nothing is ever committed. Paste
-- that script's output into the Supabase SQL editor. Success is the final error "ALL SCHEMA CHECKS PASSED".
--
-- Two throwaway users (A and B) get one row in every user table; then each one signs in (role authenticated with
-- a JWT sub claim) and must see only their own rows and be unable to write data tables.

-- Fails unless running stmt raises the given SQLSTATE.
create or replace function public.schema_test_expect(stmt text, expected text) returns void
language plpgsql as $$
begin
  execute stmt;
  raise exception 'expected SQLSTATE % but it succeeded: %', expected, stmt;
exception when others then
  if sqlstate <> expected then
    raise exception 'expected SQLSTATE %, got % (%): %', expected, sqlstate, sqlerrm, stmt;
  end if;
end $$;
grant execute on function public.schema_test_expect(text, text) to authenticated;

-- ------------------------------------------------------------------------------------------------ fixtures --
insert into auth.users (id, email) values
  ('aaaaaaaa-0000-4000-8000-00000000000a', 'schema-test-a@example.invalid'),
  ('bbbbbbbb-0000-4000-8000-00000000000b', 'schema-test-b@example.invalid');

insert into public.metric_definitions (key, label, unit, good_direction) values ('test.minutes', 'Test', 'min', 'down');

do $$
declare
  u uuid;
  conn uuid;
begin
  foreach u in array array['aaaaaaaa-0000-4000-8000-00000000000a', 'bbbbbbbb-0000-4000-8000-00000000000b']::uuid[] loop
    insert into public.profiles (user_id) values (u) on conflict (user_id) do nothing;
    insert into public.provider_connections (user_id, provider, provider_account_id, status, platform)
      values (u, 'health_connect', 'install-' || u, 'connected', 'android') returning id into conn;
    insert into public.connection_streams (connection_id, user_id, data_type, data_until)
      values (conn, u, 'sleep_session', now());
    insert into public.source_records (user_id, connection_id, source, data_type, source_record_id, data_origin,
                                       start_at, end_at, start_offset_min, end_offset_min, payload)
      values (u, conn, 'health_connect', 'sleep_session', 'hc-' || u, 'com.example.watch',
              '2026-10-13 21:30+00', '2026-10-14 05:30+00', 120, 120, '{"stages": []}');
    insert into public.sleep_nights (user_id, night_date, source, utc_offset_min, asleep_min, score)
      values (u, '2026-10-13', 'health_connect', 120, 450, 80);
    insert into public.heart_rate_days (user_id, day, source, utc_offset_min, bpm, worn_minutes)
      values (u, '2026-10-13', 'health_connect', 120, array_fill(60::smallint, array[1440]), 1440);
    insert into public.daily_activity (user_id, day, source, utc_offset_min, steps, hourly_steps)
      values (u, '2026-10-13', 'health_connect', 120, 8000, array_fill(0, array[24]));
    insert into public.daily_metrics (user_id, day, metric_key, value, source)
      values (u, '2026-10-13', 'test.minutes', 42, 'manual');
    insert into public.calendar_events (user_id, provider, provider_event_id, title, category, starts_at, ends_at, guests)
      values (u, 'google_calendar', 'cal:ev-' || u, 'Standup', 'meeting', '2026-10-13 07:00+00', '2026-10-13 07:30+00',
              '[{"response_status": "accepted"}, {"response_status": "needsAction"}]');
  end loop;
end $$;

-- ------------------------------------------------------------------------------------ constraints (as owner) --
do $$
declare a constant uuid := 'aaaaaaaa-0000-4000-8000-00000000000a';
begin
  assert (select attendee_count from public.calendar_events where user_id = a) = 2, 'attendee_count is not computed';

  perform public.schema_test_expect(format(
    $q$insert into public.source_records (user_id, source, data_type, source_record_id, start_at)
       values (%L, 'health_connect', 'heart_rate', 'hc-%s', now())$q$, a, a), '23505');          -- same record id twice
  perform public.schema_test_expect(format(
    $q$insert into public.source_records (user_id, source, data_type, source_record_id, start_at)
       values (%L, 'no_such_source', 'heart_rate', 'x1', now())$q$, a), '23503');                -- unknown source
  perform public.schema_test_expect(format(
    $q$insert into public.daily_metrics (user_id, day, metric_key, value, source)
       values (%L, '2026-10-14', 'no.such_metric', 1, 'manual')$q$, a), '23503');                -- unknown metric key
  perform public.schema_test_expect(format(
    $q$insert into public.calendar_events (user_id, provider, provider_event_id, category, starts_at, ends_at)
       values (%L, 'google_calendar', 'cal:x', 'banana', now(), now() + interval '1 hour')$q$, a), '23514');  -- type
  perform public.schema_test_expect(format(
    $q$insert into public.heart_rate_days (user_id, day, source, utc_offset_min, bpm, worn_minutes)
       values (%L, '2026-10-14', 'health_connect', 120, array[60, 61]::smallint[], 2)$q$, a), '23514');   -- 1440 values
  perform public.schema_test_expect(format(
    $q$insert into public.connection_streams (connection_id, user_id, data_type)
       select id, 'bbbbbbbb-0000-4000-8000-00000000000b', 'steps' from public.provider_connections where user_id = %L$q$, a),
    '23503');                                                                                     -- someone else's connection
  perform public.schema_test_expect(format(
    $q$insert into public.reports (user_id, kind, period_start, status) values (%L, 'daily', '2026-10-01', 'ready')$q$, a),
    '23514');                                                                                     -- ready without a report
end $$;

-- ------------------------------------------------------------------------------------------ signed in as A --
set local role authenticated;
select set_config('request.jwt.claims', '{"sub": "aaaaaaaa-0000-4000-8000-00000000000a", "role": "authenticated"}', true);

do $$
declare
  t text;
  n integer;
begin
  assert (select auth.uid()) = 'aaaaaaaa-0000-4000-8000-00000000000a'::uuid, 'not signed in as A';

  foreach t in array array['provider_connections', 'connection_streams', 'source_records', 'sleep_nights',
                           'heart_rate_days', 'daily_activity', 'daily_metrics', 'calendar_events', 'profiles'] loop
    execute format('select count(*) from public.%I', t) into n;
    assert n = 1, format('%s: A sees %s rows, expected only their own 1', t, n);
  end loop;

  foreach t in array array['sources', 'data_types', 'metric_definitions'] loop
    execute format('select count(*) from public.%I', t) into n;
    assert n > 0, format('%s: registry not readable', t);
  end loop;

  -- No writes to data tables, not even own rows.
  perform public.schema_test_expect($q$insert into public.source_records (source, data_type, source_record_id, start_at)
                                       values ('manual', 'steps', 'x2', now())$q$, '42501');
  perform public.schema_test_expect($q$insert into public.sleep_nights (night_date, source, utc_offset_min)
                                       values ('2026-10-01', 'manual', 0)$q$, '42501');
  perform public.schema_test_expect($q$insert into public.calendar_events (provider, provider_event_id, starts_at, ends_at)
                                       values ('manual', 'm1', now(), now() + interval '1 hour')$q$, '42501');
  perform public.schema_test_expect($q$update public.daily_metrics set value = 0$q$, '42501');
  perform public.schema_test_expect($q$insert into public.sources (key, label, category, delivery)
                                       values ('evil', 'Evil', 'media', 'oauth')$q$, '42501');

  -- Credentials stay invisible (no policies, or no grant at all).
  begin
    select count(*) into n from public.provider_connection_credentials;
    assert n = 0, 'credentials are readable by a signed-in user';
  exception when insufficient_privilege then null;
  end;

  -- Settings stay user-editable: the consent checkbox writes with the user's own token.
  update public.profiles set consented_at = now(), time_zone = 'Europe/Stockholm';
  get diagnostics n = row_count;
  assert n = 1, 'profile not editable by its owner';

  -- Reports: claim once, fill once, never twice.
  insert into public.reports (kind, period_start) values ('daily', '2026-10-14');
  perform public.schema_test_expect($q$insert into public.reports (kind, period_start) values ('daily', '2026-10-14')$q$,
                                    '23505');
  update public.reports set status = 'ready', mode = 'rules', report = '{}'::jsonb
   where kind = 'daily' and period_start = '2026-10-14' and status = 'pending';
  get diagnostics n = row_count;
  assert n = 1, 'pending report could not be finished';
  update public.reports set report = '{"changed": true}'::jsonb where kind = 'daily' and period_start = '2026-10-14';
  get diagnostics n = row_count;
  assert n = 0, 'a finished report could be changed';
  assert public.stressless_reports_last_day() >= 1, 'global cap does not count the claim';
end $$;

reset role;

-- ----------------------------------------------------------------------------------- deletion (as owner) --
do $$
declare
  a constant uuid := 'aaaaaaaa-0000-4000-8000-00000000000a';
  b constant uuid := 'bbbbbbbb-0000-4000-8000-00000000000b';
  t text;
  n integer;
begin
  -- Removing a connection keeps what it brought in, unlinked; its sync state goes.
  delete from public.provider_connections where user_id = a;
  assert (select count(*) from public.source_records where user_id = a and connection_id is null) = 1,
         'source_records were not kept when their connection was deleted';
  assert (select count(*) from public.connection_streams where user_id = a) = 0, 'connection_streams not cascaded';

  -- Deleting the account removes everything.
  delete from auth.users where id in (a, b);
  foreach t in array array['profiles', 'provider_connections', 'connection_streams', 'source_records', 'sleep_nights',
                           'heart_rate_days', 'daily_activity', 'daily_metrics', 'calendar_events', 'reports'] loop
    execute format('select count(*) from public.%I where user_id in (%L, %L)', t, a, b) into n;
    assert n = 0, format('%s: %s rows left after account deletion', t, n);
  end loop;
end $$;

-- Always the last statement: the error rolls the whole transaction back.
do $$ begin raise exception 'ALL SCHEMA CHECKS PASSED (everything was rolled back on purpose)'; end $$;
