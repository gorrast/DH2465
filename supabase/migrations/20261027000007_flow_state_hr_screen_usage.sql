drop function if exists public.flow_state_candidates();

create function public.flow_state_candidates()
returns table (
  event_title text,
  event_category text,
  starts_at timestamptz,
  ends_at timestamptz,
  avg_bpm numeric,
  hr_variability_bpm numeric,
  hr_sample_count bigint,
  screen_minutes numeric,
  app_sessions bigint,
  unlocks_during_event bigint
)
language sql
stable
security invoker
set search_path = ''
as $$
  with user_context as (
    select
      (select auth.uid()) as user_id,
      coalesce(
        (select profiles.time_zone from public.profiles as profiles where profiles.user_id = (select auth.uid())),
        'Europe/Stockholm'
      ) as time_zone
  ),
  calendar_blocks as (
    select distinct on (events.category, events.title, events.starts_at, events.ends_at)
      events.title as event_title,
      events.category as event_category,
      events.starts_at,
      events.ends_at,
      context.user_id
    from public.calendar_events as events
    cross join user_context as context
    where events.user_id = context.user_id
      and events.ends_at > events.starts_at
      and events.starts_at >= now() - interval '30 days'
      and events.ends_at < now()
    order by events.category, events.title, events.starts_at, events.ends_at, events.id
  ),
  event_stats as (
    select
      blocks.event_title,
      blocks.event_category,
      blocks.starts_at,
      blocks.ends_at,
      avg(heart_rate.value)::numeric as avg_bpm,
      stddev_pop(heart_rate.value)::numeric as hr_variability_bpm,
      count(*)::bigint as hr_sample_count,
      coalesce(screen.screen_minutes, 0)::numeric as screen_minutes,
      coalesce(screen.app_sessions, 0)::bigint as app_sessions,
      coalesce(unlocks.unlock_count, 0)::bigint as unlocks_during_event
    from calendar_blocks as blocks
    join public.source_records as heart_rate
      on heart_rate.user_id = blocks.user_id
     and heart_rate.data_type = 'heart_rate'
     and heart_rate.start_at >= blocks.starts_at
     and heart_rate.start_at < blocks.ends_at
     and heart_rate.value is not null
    left join lateral (
      select
        sum(
          extract(epoch from
            least(coalesce(records.end_at, records.start_at + coalesce(records.value, 0) * interval '1 minute'), blocks.ends_at)
            - greatest(records.start_at, blocks.starts_at)
          ) / 60.0
        ) as screen_minutes,
        count(*) as app_sessions
      from public.source_records as records
      where records.user_id = blocks.user_id
        and records.data_type = 'app_usage'
        and records.start_at < blocks.ends_at
        and coalesce(records.end_at, records.start_at + coalesce(records.value, 0) * interval '1 minute') > blocks.starts_at
    ) as screen on true
    left join lateral (
      select count(*) as unlock_count
      from public.source_records as records
      where records.user_id = blocks.user_id
        and records.data_type = 'screen_event'
        and records.start_at >= blocks.starts_at
        and records.start_at < blocks.ends_at
        and records.payload ->> 'type' = 'unlock'
    ) as unlocks on true
    group by
      blocks.event_title,
      blocks.event_category,
      blocks.starts_at,
      blocks.ends_at,
      screen.screen_minutes,
      screen.app_sessions,
      unlocks.unlock_count
    having count(*) >= 2
  )
  select
    event_stats.event_title,
    event_stats.event_category,
    event_stats.starts_at,
    event_stats.ends_at,
    round(event_stats.avg_bpm, 1),
    round(event_stats.hr_variability_bpm, 1),
    event_stats.hr_sample_count,
    round(event_stats.screen_minutes, 1),
    event_stats.app_sessions,
    event_stats.unlocks_during_event
  from event_stats
  order by
    event_stats.avg_bpm asc,
    event_stats.hr_variability_bpm asc,
    event_stats.screen_minutes asc,
    event_stats.unlocks_during_event asc,
    event_stats.starts_at desc
  limit 5
$$;

revoke all on function public.flow_state_candidates() from public, anon;
grant execute on function public.flow_state_candidates() to authenticated;
