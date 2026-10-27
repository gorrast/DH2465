create or replace function public.top_calendar_events_by_heart_rate()
returns table (
  event_rank bigint,
  event_id uuid,
  event_title text,
  starts_at timestamptz,
  ends_at timestamptz,
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
  with event_heart_rates as (
    select
      events.id as event_id,
      events.title as event_title,
      events.starts_at,
      events.ends_at,
      heart_rate.value as bpm
    from public.calendar_events as events
    join public.source_records as heart_rate
      on heart_rate.user_id = events.user_id
     and heart_rate.data_type = 'heart_rate'
     and heart_rate.start_at >= events.starts_at
     and heart_rate.start_at <= events.ends_at
     and heart_rate.value is not null
    where events.user_id = (select auth.uid())
      and heart_rate.user_id = (select auth.uid())
  ),
  event_stats as (
    select
      event_heart_rates.event_id,
      event_heart_rates.event_title,
      event_heart_rates.starts_at,
      event_heart_rates.ends_at,
      count(*) as hr_sample_count,
      round(avg(event_heart_rates.bpm), 1) as avg_bpm,
      min(event_heart_rates.bpm) as min_bpm,
      max(event_heart_rates.bpm) as max_bpm
    from event_heart_rates
    group by
      event_heart_rates.event_id,
      event_heart_rates.event_title,
      event_heart_rates.starts_at,
      event_heart_rates.ends_at
  ),
  ranked_events as (
    select
      row_number() over (
        order by event_stats.avg_bpm desc, event_stats.starts_at desc, event_stats.event_id
      ) as event_rank,
      event_stats.event_id,
      event_stats.event_title,
      event_stats.starts_at,
      event_stats.ends_at,
      event_stats.avg_bpm,
      event_stats.min_bpm,
      event_stats.max_bpm,
      event_stats.hr_sample_count
    from event_stats
  )
  select
    ranked_events.event_rank,
    ranked_events.event_id,
    ranked_events.event_title,
    ranked_events.starts_at,
    ranked_events.ends_at,
    ranked_events.avg_bpm,
    ranked_events.min_bpm,
    ranked_events.max_bpm,
    ranked_events.hr_sample_count
  from ranked_events
  where ranked_events.event_rank <= 5
  order by ranked_events.event_rank
$$;

revoke all on function public.top_calendar_events_by_heart_rate() from public, anon;
grant execute on function public.top_calendar_events_by_heart_rate() to authenticated;
