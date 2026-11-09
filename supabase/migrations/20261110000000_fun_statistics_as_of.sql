-- The fun-statistics cards on the Weekly tab counted back from the database clock (now(), current_date), so on
-- the demo, whose "today" is frozen with STRESSLESS_ANCHOR, their windows fell after the data and the cards came
-- up empty. Each function now takes the moment to count back from; it defaults to now(), so callers that pass
-- nothing behave as before. Bodies are unchanged apart from that.

drop function if exists public.top_apps_by_heart_rate();

create function public.top_apps_by_heart_rate(p_as_of timestamptz default now())
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
      and nights.night_date >= p_as_of::date - interval '14 days'
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

revoke all on function public.top_apps_by_heart_rate(timestamptz) from public, anon;
grant execute on function public.top_apps_by_heart_rate(timestamptz) to authenticated;

drop function if exists public.top_calendar_events_by_heart_rate();

create function public.top_calendar_events_by_heart_rate(p_as_of timestamptz default now())
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
      and nights.night_date >= p_as_of::date - interval '14 days'
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

revoke all on function public.top_calendar_events_by_heart_rate(timestamptz) from public, anon;
grant execute on function public.top_calendar_events_by_heart_rate(timestamptz) to authenticated;

drop function if exists public.top_spotify_tracks_by_gets_you_going();

create function public.top_spotify_tracks_by_gets_you_going(p_as_of timestamptz default now())
returns table (
  track_rank bigint,
  song_title text,
  artist_name text,
  gets_you_going_score numeric,
  avg_bpm numeric,
  peak_bpm numeric,
  bpm_above_resting numeric,
  times_played bigint
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
      and nights.night_date >= p_as_of::date - interval '14 days'
      and nights.resting_hr is not null
  ),
  spotify_plays as (
    select
      media.id as play_id,
      media.user_id,
      media.title as song_title,
      coalesce(media.creator, 'Unknown Artist') as artist_name,
      coalesce(media.minutes, 3.0) as duration_minutes,
      media.occurred_at - coalesce(media.minutes, 3.0) * interval '1 minute' as starts_at,
      media.occurred_at as ends_at
    from public.media_events as media
    where media.user_id = (select auth.uid())
      and lower(media.provider) like '%spotify%'
      and media.occurred_at is not null
      and coalesce(media.minutes, 0) >= 0.5
  ),
  track_heart_rates as (
    select
      plays.play_id,
      plays.user_id,
      plays.song_title,
      plays.artist_name,
      plays.duration_minutes,
      baseline.base_rhr,
      count(heart_rate.value) as sample_count,
      avg(heart_rate.value) as avg_bpm,
      max(heart_rate.value) as max_bpm,
      (array_agg(heart_rate.value order by heart_rate.start_at, heart_rate.id))[1] as start_bpm
    from spotify_plays as plays
    cross join user_rhr as baseline
    join public.source_records as heart_rate
      on heart_rate.user_id = plays.user_id
     and heart_rate.data_type = 'heart_rate'
     and heart_rate.start_at >= plays.starts_at
     and heart_rate.start_at <= plays.ends_at
     and heart_rate.value is not null
    where heart_rate.user_id = (select auth.uid())
    group by
      plays.play_id,
      plays.user_id,
      plays.song_title,
      plays.artist_name,
      plays.duration_minutes,
      baseline.base_rhr
    having count(heart_rate.value) >= 1
  ),
  scored_plays as (
    select
      track_heart_rates.user_id,
      track_heart_rates.song_title,
      track_heart_rates.artist_name,
      track_heart_rates.avg_bpm,
      track_heart_rates.max_bpm,
      track_heart_rates.base_rhr,
      greatest(0.0, least(100.0,
        (0.50 * least(100.0, greatest(0.0, ((track_heart_rates.avg_bpm - track_heart_rates.base_rhr) / 30.0) * 100.0))) +
        (0.30 * least(100.0, greatest(0.0, ((track_heart_rates.max_bpm - (track_heart_rates.base_rhr + 10.0)) / 35.0) * 100.0))) +
        (0.20 * least(100.0, greatest(0.0, ((track_heart_rates.max_bpm - track_heart_rates.start_bpm) / 20.0) * 100.0)))
      )) as play_score
    from track_heart_rates
  ),
  track_stats as (
    select
      scored_plays.user_id,
      scored_plays.song_title,
      scored_plays.artist_name,
      avg(scored_plays.play_score) as average_score,
      avg(scored_plays.avg_bpm) as avg_bpm,
      max(scored_plays.max_bpm) as peak_bpm,
      avg(scored_plays.avg_bpm - scored_plays.base_rhr) as bpm_above_resting,
      count(*) as times_played
    from scored_plays
    group by scored_plays.user_id, scored_plays.song_title, scored_plays.artist_name
  ),
  ranked_tracks as (
    select
      dense_rank() over (partition by track_stats.user_id order by track_stats.average_score desc) as track_rank,
      track_stats.*
    from track_stats
  )
  select
    ranked_tracks.track_rank,
    ranked_tracks.song_title,
    ranked_tracks.artist_name,
    round(ranked_tracks.average_score, 1),
    round(ranked_tracks.avg_bpm, 1),
    round(ranked_tracks.peak_bpm, 1),
    round(ranked_tracks.bpm_above_resting, 1),
    ranked_tracks.times_played
  from ranked_tracks
  where ranked_tracks.track_rank <= 5
  order by ranked_tracks.track_rank, ranked_tracks.song_title, ranked_tracks.artist_name
$$;

revoke all on function public.top_spotify_tracks_by_gets_you_going(timestamptz) from public, anon;
grant execute on function public.top_spotify_tracks_by_gets_you_going(timestamptz) to authenticated;

drop function if exists public.flow_state_candidates();

create function public.flow_state_candidates(p_as_of timestamptz default now())
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
      and events.starts_at >= p_as_of - interval '30 days'
      and events.ends_at < p_as_of
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

revoke all on function public.flow_state_candidates(timestamptz) from public, anon;
grant execute on function public.flow_state_candidates(timestamptz) to authenticated;

drop function if exists public.meeting_hangover_index();

create function public.meeting_hangover_index(p_as_of timestamptz default now())
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
      and events.starts_at >= p_as_of - interval '30 days'
      and events.ends_at <= p_as_of - interval '3 hours'
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

revoke all on function public.meeting_hangover_index(timestamptz) from public, anon;
grant execute on function public.meeting_hangover_index(timestamptz) to authenticated;
