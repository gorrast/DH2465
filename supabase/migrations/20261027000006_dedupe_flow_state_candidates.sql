create or replace function public.flow_state_candidates()
returns table (
  focus_title text,
  starts_at timestamptz,
  ends_at timestamptz,
  prior_night_hrv numeric,
  unlocks_during_focus bigint,
  steps_before_9 integer,
  spotify_minutes numeric,
  app_sessions bigint
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
  focus_blocks as (
    select distinct on (events.title, events.starts_at, events.ends_at)
      events.title as focus_title,
      events.starts_at,
      events.ends_at,
      context.user_id,
      context.time_zone,
      ((events.starts_at at time zone context.time_zone)::date - 1) as prior_night_date,
      (events.starts_at at time zone context.time_zone)::date as local_date
    from public.calendar_events as events
    cross join user_context as context
    where events.user_id = context.user_id
      and events.category = 'focus'
      and events.ends_at > events.starts_at
      and events.starts_at >= now() - interval '30 days'
      and events.ends_at < now()
    order by events.title, events.starts_at, events.ends_at, events.id
  ),
  observed_blocks as (
    select
      blocks.focus_title,
      blocks.starts_at,
      blocks.ends_at,
      sleep.hrv_rmssd_ms::numeric as prior_night_hrv,
      coalesce(unlocks.unlock_count, 0)::bigint as unlocks_during_focus,
      steps.steps_before_9,
      coalesce(music.spotify_minutes, 0)::numeric as spotify_minutes,
      coalesce(apps.session_count, 0)::bigint as app_sessions
    from focus_blocks as blocks
    left join public.sleep_nights as sleep
      on sleep.user_id = blocks.user_id
     and sleep.night_date = blocks.prior_night_date
    left join public.daily_activity as activity
      on activity.user_id = blocks.user_id
     and activity.day = blocks.local_date
    left join lateral (
      select sum(hourly.count)::integer as steps_before_9
      from unnest(activity.hourly_steps) with ordinality as hourly(count, hour_index)
      where hourly.hour_index <= 9
    ) as steps on true
    left join lateral (
      select count(*) as unlock_count
      from public.source_records as records
      where records.user_id = blocks.user_id
        and records.data_type = 'screen_event'
        and records.start_at >= blocks.starts_at
        and records.start_at < blocks.ends_at
        and records.payload ->> 'type' = 'unlock'
    ) as unlocks on true
    left join lateral (
      select sum(
        extract(epoch from
          least(media.occurred_at, blocks.ends_at)
          - greatest(media.occurred_at - media.minutes * interval '1 minute', blocks.starts_at)
        ) / 60.0
      ) as spotify_minutes
      from public.media_events as media
      where media.user_id = blocks.user_id
        and media.provider = 'spotify'
        and media.occurred_at > blocks.starts_at
        and media.occurred_at - media.minutes * interval '1 minute' < blocks.ends_at
    ) as music on true
    left join lateral (
      select count(*) as session_count
      from public.source_records as records
      where records.user_id = blocks.user_id
        and records.data_type = 'app_usage'
        and records.start_at < blocks.ends_at
        and coalesce(records.end_at, records.start_at + coalesce(records.value, 0) * interval '1 minute') > blocks.starts_at
    ) as apps on true
  ),
  ranked_blocks as (
    select
      observed_blocks.*,
      row_number() over (
        order by observed_blocks.prior_night_hrv desc nulls last,
                 observed_blocks.unlocks_during_focus asc,
                 observed_blocks.steps_before_9 desc nulls last,
                 observed_blocks.spotify_minutes desc,
                 observed_blocks.starts_at desc
      ) as candidate_rank
    from observed_blocks
  )
  select
    ranked_blocks.focus_title,
    ranked_blocks.starts_at,
    ranked_blocks.ends_at,
    ranked_blocks.prior_night_hrv,
    ranked_blocks.unlocks_during_focus,
    ranked_blocks.steps_before_9,
    round(ranked_blocks.spotify_minutes, 1),
    ranked_blocks.app_sessions
  from ranked_blocks
  where ranked_blocks.candidate_rank <= 5
  order by ranked_blocks.candidate_rank
$$;

revoke all on function public.flow_state_candidates() from public, anon;
grant execute on function public.flow_state_candidates() to authenticated;
