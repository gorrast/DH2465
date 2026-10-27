drop function if exists public.top_apps_by_heart_rate();

create function public.top_apps_by_heart_rate()
returns table (
  app_rank bigint,
  app_name text,
  package_name text,
  gets_you_going_score numeric,
  peak_session_score numeric,
  avg_bpm numeric,
  peak_bpm numeric,
  total_minutes numeric,
  sessions_measured bigint
)
language sql
stable
security invoker
set search_path = ''
as $$
  with user_rhr as (
    select coalesce(avg(nights.resting_hr), 65.0) as base_rhr
    from public.sleep_nights as nights
    where nights.user_id = (select auth.uid())
      and nights.night_date >= current_date - interval '14 days'
      and nights.resting_hr is not null
  ),
  app_sessions as (
    select
      records.id as session_id,
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
      coalesce(records.end_at, records.start_at + coalesce(records.value, 0) * interval '1 minute') as session_end,
      coalesce(records.value, 0) as duration_minutes
    from public.source_records as records
    where records.user_id = (select auth.uid())
      and records.data_type = 'app_usage'
      and records.start_at is not null
  ),
  session_heart_rates as (
    select
      sessions.session_id,
      sessions.user_id,
      sessions.package_name,
      sessions.app_name,
      sessions.duration_minutes,
      baseline.base_rhr,
      count(heart_rate.value) as sample_count,
      avg(heart_rate.value) as avg_bpm,
      max(heart_rate.value) as max_bpm,
      (array_agg(heart_rate.value order by heart_rate.start_at, heart_rate.id))[1] as start_bpm
    from app_sessions as sessions
    join user_rhr as baseline on true
    join public.source_records as heart_rate
      on heart_rate.user_id = sessions.user_id
     and heart_rate.data_type = 'heart_rate'
     and heart_rate.start_at >= sessions.session_start
     and heart_rate.start_at <= sessions.session_end
     and heart_rate.value is not null
    where heart_rate.user_id = (select auth.uid())
    group by
      sessions.session_id,
      sessions.user_id,
      sessions.package_name,
      sessions.app_name,
      sessions.duration_minutes,
      baseline.base_rhr
    having count(heart_rate.value) >= 2
  ),
  session_scores as (
    select
      session_heart_rates.user_id,
      session_heart_rates.package_name,
      session_heart_rates.app_name,
      session_heart_rates.duration_minutes,
      session_heart_rates.avg_bpm,
      session_heart_rates.max_bpm,
      greatest(0.0, least(100.0,
        (0.50 * least(100.0, greatest(0.0, ((session_heart_rates.avg_bpm - session_heart_rates.base_rhr) / 30.0) * 100.0))) +
        (0.30 * least(100.0, greatest(0.0, ((session_heart_rates.max_bpm - (session_heart_rates.base_rhr + 10.0)) / 35.0) * 100.0))) +
        (0.20 * least(100.0, greatest(0.0, ((session_heart_rates.max_bpm - session_heart_rates.start_bpm) / 20.0) * 100.0)))
      )) as session_score
    from session_heart_rates
  ),
  app_stats as (
    select
      session_scores.user_id,
      session_scores.package_name,
      session_scores.app_name,
      avg(session_scores.session_score) as average_session_score,
      max(session_scores.session_score) as peak_session_score,
      avg(session_scores.avg_bpm) as avg_bpm,
      max(session_scores.max_bpm) as peak_bpm,
      sum(session_scores.duration_minutes) as total_minutes,
      count(*) as sessions_measured
    from session_scores
    group by session_scores.user_id, session_scores.package_name, session_scores.app_name
  ),
  ranked_apps as (
    select
      dense_rank() over (partition by app_stats.user_id order by app_stats.average_session_score desc) as app_rank,
      app_stats.*
    from app_stats
  )
  select
    ranked_apps.app_rank,
    ranked_apps.app_name,
    ranked_apps.package_name,
    round(ranked_apps.average_session_score, 1),
    round(ranked_apps.peak_session_score, 1),
    round(ranked_apps.avg_bpm, 1),
    round(ranked_apps.peak_bpm, 1),
    round(ranked_apps.total_minutes, 1),
    ranked_apps.sessions_measured
  from ranked_apps
  where ranked_apps.app_rank <= 5
  order by ranked_apps.app_rank, ranked_apps.package_name
$$;

revoke all on function public.top_apps_by_heart_rate() from public, anon;
grant execute on function public.top_apps_by_heart_rate() to authenticated;
