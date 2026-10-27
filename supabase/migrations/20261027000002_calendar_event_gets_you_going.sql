drop function if exists public.top_calendar_events_by_heart_rate();

create function public.top_calendar_events_by_heart_rate()
returns table (
  event_rank bigint,
  event_id uuid,
  event_title text,
  starts_at timestamptz,
  ends_at timestamptz,
  gets_you_going_score numeric,
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
  with user_rhr as (
    select coalesce(avg(nights.resting_hr), 65.0) as base_rhr
    from public.sleep_nights as nights
    where nights.user_id = (select auth.uid())
      and nights.night_date >= current_date - interval '14 days'
      and nights.resting_hr is not null
  ),
  event_heart_rates as (
    select
      events.id as event_id,
      events.title as event_title,
      events.starts_at,
      events.ends_at,
      baseline.base_rhr,
      count(heart_rate.value) as sample_count,
      avg(heart_rate.value) as avg_bpm,
      max(heart_rate.value) as max_bpm,
      min(heart_rate.value) as min_bpm,
      (array_agg(heart_rate.value order by heart_rate.start_at, heart_rate.id))[1] as start_bpm
    from public.calendar_events as events
    cross join user_rhr as baseline
    join public.source_records as heart_rate
      on heart_rate.user_id = events.user_id
     and heart_rate.data_type = 'heart_rate'
     and heart_rate.start_at >= events.starts_at
     and heart_rate.start_at <= events.ends_at
     and heart_rate.value is not null
    where events.user_id = (select auth.uid())
      and heart_rate.user_id = (select auth.uid())
    group by
      events.id,
      events.title,
      events.starts_at,
      events.ends_at,
      baseline.base_rhr
    having count(heart_rate.value) >= 2
  ),
  event_scores as (
    select
      event_heart_rates.event_id,
      event_heart_rates.event_title,
      event_heart_rates.starts_at,
      event_heart_rates.ends_at,
      event_heart_rates.avg_bpm,
      event_heart_rates.min_bpm,
      event_heart_rates.max_bpm,
      event_heart_rates.sample_count,
      greatest(0.0, least(100.0,
        (0.50 * least(100.0, greatest(0.0, ((event_heart_rates.avg_bpm - event_heart_rates.base_rhr) / 30.0) * 100.0))) +
        (0.30 * least(100.0, greatest(0.0, ((event_heart_rates.max_bpm - (event_heart_rates.base_rhr + 10.0)) / 35.0) * 100.0))) +
        (0.20 * least(100.0, greatest(0.0, ((event_heart_rates.max_bpm - event_heart_rates.start_bpm) / 20.0) * 100.0)))
      )) as gets_you_going_score
    from event_heart_rates
  ),
  ranked_events as (
    select
      row_number() over (
        order by event_scores.gets_you_going_score desc, event_scores.starts_at desc, event_scores.event_id
      ) as event_rank,
      event_scores.*
    from event_scores
  )
  select
    ranked_events.event_rank,
    ranked_events.event_id,
    ranked_events.event_title,
    ranked_events.starts_at,
    ranked_events.ends_at,
    round(ranked_events.gets_you_going_score, 1),
    round(ranked_events.avg_bpm, 1),
    round(ranked_events.min_bpm, 1),
    round(ranked_events.max_bpm, 1),
    ranked_events.sample_count
  from ranked_events
  where ranked_events.event_rank <= 5
  order by ranked_events.event_rank
$$;

revoke all on function public.top_calendar_events_by_heart_rate() from public, anon;
grant execute on function public.top_calendar_events_by_heart_rate() to authenticated;
