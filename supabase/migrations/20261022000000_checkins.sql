-- Manual check-ins (coffee and alcohol), following "Adding a source" in docs/SCHEMA.md: registry rows only, no new
-- tables. The web app posts a day's numbers to POST /api/checkins/{day}; the API writes them into daily_metrics with
-- source 'manual' (already in the sources registry). A check-in is its own raw record, so nothing goes to
-- source_records. "day" is the local date the coffee or drinks were had, the same key as sleep_nights.night_date, so
-- an evening's drinks line up with the night that starts that evening. No row means "not logged", not zero.

insert into public.metric_definitions (key, label, unit, good_direction) values
  ('intake.coffee_cups',    'Coffee',  'cups',  'none'),
  ('intake.alcohol_units',  'Alcohol', 'units', 'down')
on conflict (key) do nothing;
