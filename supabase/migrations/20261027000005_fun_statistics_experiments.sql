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
    select
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

create or replace function public.cardiac_wrapped()
returns table (
  archetype text,
  item_title text,
  artist_name text,
  primary_value numeric,
  comparison_value numeric,
  sample_count bigint,
  plays_count bigint,
  note text
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
  spotify_plays as (
    select
      media.id as play_id,
      media.user_id,
      media.title as song_title,
      coalesce(media.creator, 'Unknown Artist') as artist_name,
      media.occurred_at - coalesce(media.minutes, 3.0) * interval '1 minute' as starts_at,
      media.occurred_at as ends_at
    from public.media_events as media
    cross join user_context as context
    where media.user_id = context.user_id
      and media.provider = 'spotify'
      and media.occurred_at >= now() - interval '7 days'
      and coalesce(media.minutes, 0) >= 0.5
  ),
  play_stats as (
    select
      plays.play_id,
      plays.user_id,
      plays.song_title,
      plays.artist_name,
      plays.starts_at,
      plays.ends_at,
      count(heart_rate.value) as sample_count,
      avg(heart_rate.value) as avg_bpm,
      max(heart_rate.value) as peak_bpm,
      (array_agg(heart_rate.value order by heart_rate.start_at, heart_rate.id))[1] as start_bpm
    from spotify_plays as plays
    join public.source_records as heart_rate
      on heart_rate.user_id = plays.user_id
     and heart_rate.data_type = 'heart_rate'
     and heart_rate.start_at >= plays.starts_at
     and heart_rate.start_at <= plays.ends_at
     and heart_rate.value is not null
    group by
      plays.play_id, plays.user_id, plays.song_title, plays.artist_name,
      plays.starts_at, plays.ends_at
  ),
  anthem as (
    select
      'Cardiac Anthem'::text as archetype,
      stats.song_title as item_title,
      stats.artist_name,
      (stats.peak_bpm - stats.start_bpm)::numeric as primary_value,
      stats.peak_bpm::numeric as comparison_value,
      stats.sample_count::bigint as sample_count,
      1::bigint as plays_count,
      'Largest rise from the first to peak recorded playback HR this week on a low-activity day (2,000 steps or fewer; stationary proxy).'::text as note,
      1 as sort_order
    from play_stats as stats
    cross join user_context as context
    join public.daily_activity as activity
      on activity.user_id = stats.user_id
     and activity.day = (stats.starts_at at time zone context.time_zone)::date
     and activity.steps <= 2000
    order by stats.peak_bpm - stats.start_bpm desc, stats.starts_at desc
    limit 1
  ),
  non_spotify_baseline as (
    select avg(heart_rate.value) as avg_bpm
    from public.source_records as heart_rate
    where heart_rate.user_id = (select auth.uid())
      and heart_rate.data_type = 'heart_rate'
      and heart_rate.start_at >= now() - interval '7 days'
      and heart_rate.value is not null
      and not exists (
        select 1
        from spotify_plays as plays
        where plays.user_id = heart_rate.user_id
          and heart_rate.start_at >= plays.starts_at
          and heart_rate.start_at <= plays.ends_at
      )
  ),
  artist_stats as (
    select
      stats.artist_name,
      avg(stats.avg_bpm) as avg_bpm,
      sum(stats.sample_count)::bigint as sample_count,
      count(*)::bigint as plays_count,
      baseline.avg_bpm as comparison_bpm
    from play_stats as stats
    cross join non_spotify_baseline as baseline
    group by stats.artist_name, baseline.avg_bpm
    having count(*) >= 2
       and baseline.avg_bpm is not null
       and avg(stats.avg_bpm) < baseline.avg_bpm
  ),
  calmer as (
    select
      'True Calmer'::text as archetype,
      'Artist with lowest average heart rate'::text as item_title,
      artists.artist_name,
      (artists.comparison_bpm - artists.avg_bpm)::numeric as primary_value,
      artists.avg_bpm::numeric as comparison_value,
      artists.sample_count,
      artists.plays_count,
      'Compared with heart rate outside logged Spotify plays; this is not a measured silence or audio-output signal.'::text as note,
      2 as sort_order
    from artist_stats as artists
    order by artists.comparison_bpm - artists.avg_bpm desc
    limit 1
  ),
  focus_cadence_stats as (
    select
      plays.song_title,
      plays.artist_name,
      stddev_pop(heart_rate.value) as bpm_variance,
      avg(heart_rate.value) as avg_bpm,
      count(*)::bigint as sample_count,
      count(distinct plays.play_id)::bigint as plays_count
    from spotify_plays as plays
    join public.calendar_events as focus
      on focus.user_id = plays.user_id
     and focus.category = 'focus'
     and plays.starts_at < focus.ends_at
     and plays.ends_at > focus.starts_at
    join public.source_records as heart_rate
      on heart_rate.user_id = plays.user_id
     and heart_rate.data_type = 'heart_rate'
     and heart_rate.start_at >= greatest(plays.starts_at, focus.starts_at)
     and heart_rate.start_at <= least(plays.ends_at, focus.ends_at)
     and heart_rate.value is not null
    group by plays.song_title, plays.artist_name
    having count(*) >= 2
  ),
  cadence as (
    select
      'Focus Cadence'::text as archetype,
      stats.song_title as item_title,
      stats.artist_name,
      stats.bpm_variance::numeric as primary_value,
      stats.avg_bpm::numeric as comparison_value,
      stats.sample_count,
      stats.plays_count,
      'Lowest heart-rate variation during overlapping Spotify plays and focus calendar blocks.'::text as note,
      3 as sort_order
    from focus_cadence_stats as stats
    order by stats.bpm_variance asc, stats.song_title, stats.artist_name
    limit 1
  )
  select
    results.archetype,
    results.item_title,
    results.artist_name,
    round(results.primary_value, 1),
    round(results.comparison_value, 1),
    results.sample_count,
    results.plays_count,
    results.note
  from (
    select * from anthem
    union all
    select * from calmer
    union all
    select * from cadence
  ) as results
  order by results.sort_order
$$;

revoke all on function public.cardiac_wrapped() from public, anon;
grant execute on function public.cardiac_wrapped() to authenticated;

create or replace function public.meeting_hangover_index()
returns table (
  event_id uuid,
  event_title text,
  starts_at timestamptz,
  ends_at timestamptz,
  attendee_count integer,
  post_meeting_hr_drift numeric,
  night_resting_hr_delta numeric,
  deep_sleep_delta_min numeric,
  post_hr_sample_count bigint
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
  meetings as (
    select
      events.id as event_id,
      events.title as event_title,
      events.starts_at,
      events.ends_at,
      events.attendee_count,
      context.user_id,
      context.time_zone,
      case
        when extract(hour from events.ends_at at time zone context.time_zone) < 6
          then (events.ends_at at time zone context.time_zone)::date - 1
        else (events.ends_at at time zone context.time_zone)::date
      end as event_night_date
    from public.calendar_events as events
    cross join user_context as context
    where events.user_id = context.user_id
      and events.category = 'meeting'
      and events.ends_at > events.starts_at
      and events.starts_at >= now() - interval '30 days'
      and events.ends_at <= now() - interval '3 hours'
  ),
  measured_meetings as (
    select
      meetings.event_id,
      meetings.event_title,
      meetings.starts_at,
      meetings.ends_at,
      meetings.attendee_count,
      post_hr.avg_bpm - pre_hr.avg_bpm as post_meeting_hr_drift,
      sleep.resting_hr - baselines.resting_hr as night_resting_hr_delta,
      sleep.deep_min - baselines.deep_min as deep_sleep_delta_min,
      post_hr.sample_count as post_hr_sample_count
    from meetings
    join lateral (
      select avg(records.value) as avg_bpm, count(*)::bigint as sample_count
      from public.source_records as records
      where records.user_id = meetings.user_id
        and records.data_type = 'heart_rate'
        and records.start_at >= meetings.ends_at
        and records.start_at < meetings.ends_at + interval '3 hours'
        and records.value is not null
      having count(*) >= 2
    ) as post_hr on true
    join lateral (
      select avg(records.value) as avg_bpm
      from public.source_records as records
      where records.user_id = meetings.user_id
        and records.data_type = 'heart_rate'
        and records.start_at >= meetings.starts_at - interval '1 hour'
        and records.start_at < meetings.starts_at
        and records.value is not null
      having count(*) >= 1
    ) as pre_hr on true
    left join public.sleep_nights as sleep
      on sleep.user_id = meetings.user_id
     and sleep.night_date = meetings.event_night_date
    left join lateral (
      select
        avg(nights.resting_hr) as resting_hr,
        avg(nights.deep_min) as deep_min
      from public.sleep_nights as nights
      where nights.user_id = meetings.user_id
        and nights.night_date >= meetings.event_night_date - 30
        and nights.night_date < meetings.event_night_date
    ) as baselines on true
  ),
  ranked_meetings as (
    select
      measured_meetings.*,
      row_number() over (
        order by measured_meetings.post_meeting_hr_drift desc, measured_meetings.starts_at desc
      ) as meeting_rank
    from measured_meetings
  )
  select
    ranked_meetings.event_id,
    ranked_meetings.event_title,
    ranked_meetings.starts_at,
    ranked_meetings.ends_at,
    ranked_meetings.attendee_count,
    round(ranked_meetings.post_meeting_hr_drift, 1),
    round(ranked_meetings.night_resting_hr_delta, 1),
    round(ranked_meetings.deep_sleep_delta_min, 1),
    ranked_meetings.post_hr_sample_count
  from ranked_meetings
  where ranked_meetings.meeting_rank <= 5
  order by ranked_meetings.meeting_rank
$$;

revoke all on function public.meeting_hangover_index() from public, anon;
grant execute on function public.meeting_hangover_index() to authenticated;
