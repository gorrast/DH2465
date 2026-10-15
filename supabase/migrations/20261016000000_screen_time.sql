-- Screen time from the phone app (Android UsageStats), following "Adding a source" in docs/SCHEMA.md: registry rows
-- only, no new tables. Raw: one source_records row per foreground app session (data_type app_usage, data_origin = the
-- app's package, source_record_id = '<package>:<start ms>') and per screen/lock event (data_type screen_event).
-- Derived: the screen.* keys below in daily_metrics, written by POST /api/sync.

insert into public.sources (key, label, category, delivery, active) values
  ('screen_time', 'Screen time (Android)', 'screen', 'phone', true)
on conflict (key) do nothing;

insert into public.data_types (key, label, category) values
  ('app_usage',    'App usage sessions',     'screen'),
  ('screen_event', 'Screen and lock events', 'screen')
on conflict (key) do nothing;

-- "Late" is 22:00-03:00, counted on the evening it started (the same day key as sleep_nights.night_date).
insert into public.metric_definitions (key, label, unit, good_direction) values
  ('screen.minutes',      'Screen time',            'min',   'down'),
  ('screen.late_minutes', 'Screen time after 22:00', 'min',   'down'),
  ('screen.pickups',      'Phone unlocks',          'count', 'down')
on conflict (key) do nothing;
