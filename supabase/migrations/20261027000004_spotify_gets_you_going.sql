create or replace function public.top_spotify_tracks_by_gets_you_going()
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
      and nights.night_date >= current_date - interval '14 days'
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

revoke all on function public.top_spotify_tracks_by_gets_you_going() from public, anon;
grant execute on function public.top_spotify_tracks_by_gets_you_going() to authenticated;
