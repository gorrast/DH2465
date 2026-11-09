-- The same fix as 20261110000000_fun_statistics_as_of.sql, for the two functions behind the Weekly tab's
-- "Your Cardiac Wrapped" card: they counted the last 7 days back from the database clock, so on the demo (today
-- frozen with STRESSLESS_ANCHOR) the card came up empty. p_as_of defaults to now(); bodies are otherwise unchanged.

drop function if exists public.cardiac_wrapped();

create function public.cardiac_wrapped(p_as_of timestamptz default now())
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
      and media.occurred_at >= p_as_of - interval '7 days'
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
      and heart_rate.start_at >= p_as_of - interval '7 days'
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

revoke all on function public.cardiac_wrapped(timestamptz) from public, anon;
grant execute on function public.cardiac_wrapped(timestamptz) to authenticated;

drop function if exists public.top_spotify_track_gets_you_going_this_week();

create function public.top_spotify_track_gets_you_going_this_week(p_as_of timestamptz default now())
returns table (
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
      and media.provider = 'spotify'
      and media.occurred_at >= p_as_of - interval '7 days'
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
  )
  select
    track_stats.song_title,
    track_stats.artist_name,
    round(track_stats.average_score, 1),
    round(track_stats.avg_bpm, 1),
    round(track_stats.peak_bpm, 1),
    round(track_stats.bpm_above_resting, 1),
    track_stats.times_played
  from track_stats
  order by track_stats.average_score desc, track_stats.song_title, track_stats.artist_name
  limit 1
$$;

revoke all on function public.top_spotify_track_gets_you_going_this_week(timestamptz) from public, anon;
grant execute on function public.top_spotify_track_gets_you_going_this_week(timestamptz) to authenticated;
