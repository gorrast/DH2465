-- Apple Health values the Android sync has no equivalent for, computed by POST /api/apple/derive
-- (backend/stressless/server/apple_sync.py) from the raw records the Apple importer uploads.
insert into public.metric_definitions (key, label, unit, good_direction) values
  ('health.active_energy', 'Active energy',               'kcal',      'up'),
  ('health.exercise_min',  'Exercise minutes',            'min',       'up'),
  ('health.stand_hours',   'Stand hours',                 'count',     'up'),
  ('health.vo2max',        'VO2 max',                     'mL/kg/min', 'up'),
  ('health.walking_hr',    'Walking heart rate',          'bpm',       'down'),
  ('health.hrv_sdnn_day',  'Heart rate variability (day)', 'ms',       'up'),
  ('health.mindful_min',   'Mindful minutes',             'min',       'up')
on conflict (key) do nothing;
