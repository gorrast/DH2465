create or replace function public.top_apps_by_heart_rate()
returns table (
  app_rank bigint,
  app_name text,
  package_name text,
  avg_bpm numeric,
  min_bpm numeric,
  max_bpm numeric,
  hr_sample_count bigint
)
language sql
stable
security invoker
set search_path = ''
as $$
  with app_sessions as (
    select
      records.user_id,
      split_part(records.source_record_id, ':', 1) as package_name,
      coalesce(
        nullif(
          initcap(
            replace(
              replace(
                regexp_replace(
                  split_part(records.source_record_id, ':', 1),
                  '^(com|org|net|io|co|ai|app|se|de|uk|fr)\.([^.]+\.)*',
                  ''
                ),
                '.', ' '
              ),
              '_', ' '
            )
          ),
          ''
        ),
        split_part(records.source_record_id, ':', 1)
      ) as app_name,
      records.start_at as session_start,
      coalesce(records.end_at, records.start_at + coalesce(records.value, 0) * interval '1 minute') as session_end
    from public.source_records as records
    where records.user_id = (select auth.uid())
      and records.data_type = 'app_usage'
      and records.start_at is not null
  ),
  app_heart_rates as (
    select
      sessions.user_id,
      sessions.package_name,
      sessions.app_name,
      heart_rate.value as bpm
    from app_sessions as sessions
    join public.source_records as heart_rate
      on heart_rate.user_id = sessions.user_id
     and heart_rate.data_type = 'heart_rate'
     and heart_rate.start_at >= sessions.session_start
     and heart_rate.start_at <= sessions.session_end
     and heart_rate.value is not null
    where heart_rate.user_id = (select auth.uid())
  ),
  app_stats as (
    select
      app_heart_rates.app_name,
      app_heart_rates.package_name,
      count(*) as hr_sample_count,
      round(avg(app_heart_rates.bpm), 1) as avg_bpm,
      min(app_heart_rates.bpm) as min_bpm,
      max(app_heart_rates.bpm) as max_bpm,
      dense_rank() over (order by avg(app_heart_rates.bpm) desc) as app_rank
    from app_heart_rates
    group by app_heart_rates.app_name, app_heart_rates.package_name
  )
  select
    app_stats.app_rank,
    app_stats.app_name,
    app_stats.package_name,
    app_stats.avg_bpm,
    app_stats.min_bpm,
    app_stats.max_bpm,
    app_stats.hr_sample_count
  from app_stats
  where app_stats.app_rank <= 5
  order by app_stats.app_rank, app_stats.package_name
$$;

revoke all on function public.top_apps_by_heart_rate() from public, anon;
grant execute on function public.top_apps_by_heart_rate() to authenticated;
