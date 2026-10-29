-- StressLess no longer uses heart rate variability or skin temperature: the phone app cannot read them from Health
-- Connect, so nothing ever wrote these columns. Breathing rate and resting heart rate take their place.
alter table public.sleep_nights
  drop column if exists hrv_rmssd_ms,
  drop column if exists hrv_sdnn_ms,
  drop column if exists skin_temp_dev;

-- Retire the data types too, unless a stored record or sync stream still names one (then leave it).
delete from public.data_types as t
where t.key in ('hrv_rmssd', 'hrv_sdnn', 'skin_temperature')
  and not exists (select 1 from public.source_records as r where r.data_type = t.key)
  and not exists (select 1 from public.connection_streams as s where s.data_type = t.key);
