'use client';
import { useState } from 'react';
import { getSupabase } from '@/lib/supabase/client';
import { ViewHead } from './common';

type AppUsage = {
  appName: string;
  packageName: string;
  minutes: number;
};

type AppHeartRate = {
  app_rank: number;
  app_name: string;
  package_name: string;
  gets_you_going_score: number;
  peak_session_score: number;
  avg_bpm: number;
  peak_bpm: number;
  total_minutes: number;
  sessions_measured: number;
};

type CalendarEventHeartRate = {
  event_rank: number;
  event_id: string;
  event_title: string | null;
  starts_at: string;
  ends_at: string;
  gets_you_going_score: number;
  avg_bpm: number;
  min_bpm: number;
  max_bpm: number;
  hr_sample_count: number;
};

type SpotifyTrackScore = {
  track_rank: number;
  song_title: string;
  artist_name: string;
  gets_you_going_score: number;
  avg_bpm: number;
  peak_bpm: number;
  bpm_above_resting: number;
  times_played: number;
};

type FlowCandidate = {
  event_title: string | null;
  event_category: string;
  starts_at: string;
  ends_at: string;
  avg_bpm: number;
  hr_variability_bpm: number;
  hr_sample_count: number;
  screen_minutes: number;
  app_sessions: number;
  unlocks_during_event: number;
};

type CardiacWrappedResult = {
  archetype: string;
  item_title: string;
  artist_name: string | null;
  primary_value: number | null;
  comparison_value: number | null;
  sample_count: number;
  plays_count: number;
  note: string;
};

type WeeklySpotifyGetsYouGoing = {
  song_title: string;
  artist_name: string;
  gets_you_going_score: number;
  avg_bpm: number;
  peak_bpm: number;
  bpm_above_resting: number;
  times_played: number;
};

type MeetingHangoverResult = {
  event_id: string;
  event_title: string | null;
  starts_at: string;
  ends_at: string;
  attendee_count: number | null;
  post_meeting_hr_drift: number | null;
  night_resting_hr_delta: number | null;
  deep_sleep_delta_min: number | null;
  post_hr_sample_count: number;
};

function displayAppName(packageName: string): string {
  const cleaned = packageName
    .replace(/^(com|org|net|io|co|ai|app|se|de|uk|fr)\.([^.]+\.)*/i, '')
    .replace(/[._]/g, ' ')
    .trim()
    .toLowerCase();
  return cleaned ? cleaned.replace(/\b[a-z]/g, (letter) => letter.toUpperCase()) : packageName;
}

export function FunStatisticsView({ embedded = false }: { embedded?: boolean }) {
  const [apps, setApps] = useState<AppUsage[]>([]);
  const [appsLoaded, setAppsLoaded] = useState(false);
  const [appsPending, setAppsPending] = useState(false);
  const [appsError, setAppsError] = useState('');
  const [heartRateApps, setHeartRateApps] = useState<AppHeartRate[]>([]);
  const [heartRateAppsLoaded, setHeartRateAppsLoaded] = useState(false);
  const [heartRateAppsPending, setHeartRateAppsPending] = useState(false);
  const [heartRateAppsError, setHeartRateAppsError] = useState('');
  const [heartRateEvents, setHeartRateEvents] = useState<CalendarEventHeartRate[]>([]);
  const [heartRateEventsLoaded, setHeartRateEventsLoaded] = useState(false);
  const [heartRateEventsPending, setHeartRateEventsPending] = useState(false);
  const [heartRateEventsError, setHeartRateEventsError] = useState('');
  const [spotifyTracks, setSpotifyTracks] = useState<SpotifyTrackScore[]>([]);
  const [spotifyTracksLoaded, setSpotifyTracksLoaded] = useState(false);
  const [spotifyTracksPending, setSpotifyTracksPending] = useState(false);
  const [spotifyTracksError, setSpotifyTracksError] = useState('');
  const [flowCandidates, setFlowCandidates] = useState<FlowCandidate[]>([]);
  const [flowLoaded, setFlowLoaded] = useState(false);
  const [flowPending, setFlowPending] = useState(false);
  const [flowError, setFlowError] = useState('');
  const [cardiacWrapped, setCardiacWrapped] = useState<CardiacWrappedResult[]>([]);
  const [cardiacWrappedLoaded, setCardiacWrappedLoaded] = useState(false);
  const [cardiacWrappedPending, setCardiacWrappedPending] = useState(false);
  const [cardiacWrappedError, setCardiacWrappedError] = useState('');
  const [weeklySpotifyGetsYouGoing, setWeeklySpotifyGetsYouGoing] = useState<WeeklySpotifyGetsYouGoing | null>(null);
  const [meetingHangovers, setMeetingHangovers] = useState<MeetingHangoverResult[]>([]);
  const [meetingHangoversLoaded, setMeetingHangoversLoaded] = useState(false);
  const [meetingHangoversPending, setMeetingHangoversPending] = useState(false);
  const [meetingHangoversError, setMeetingHangoversError] = useState('');

  async function showTopApps() {
    setAppsPending(true);
    setAppsError('');
    setApps([]);
    setAppsLoaded(false);
    try {
      const { data: userResult, error: userError } = await getSupabase().auth.getUser();
      if (userError) throw userError;
      if (!userResult.user) throw new Error('Sign in to view your app usage.');

      const since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
      const { data, error: queryError } = await getSupabase()
        .from('source_records')
        .select('source_record_id,value')
        .eq('user_id', userResult.user.id)
        .eq('data_type', 'app_usage')
        .gte('start_at', since);
      if (queryError) throw queryError;

      const totals = new Map<string, number>();
      for (const row of data || []) {
        const packageName = typeof row.source_record_id === 'string'
          ? row.source_record_id.split(':', 1)[0].trim()
          : '';
        const minutes = Number(row.value ?? 0);
        if (packageName && Number.isFinite(minutes) && minutes > 0) {
          totals.set(packageName, (totals.get(packageName) || 0) + minutes);
        }
      }

      setApps(Array.from(totals, ([packageName, minutes]) => ({
        appName: displayAppName(packageName),
        packageName,
        minutes: Math.round(minutes * 10) / 10,
      })).sort((a, b) => b.minutes - a.minutes || a.packageName.localeCompare(b.packageName)).slice(0, 5));
      setAppsLoaded(true);
    } catch (cause) {
      setAppsError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setAppsPending(false);
    }
  }

  async function showTopAppsByHeartRate() {
    setHeartRateAppsPending(true);
    setHeartRateAppsError('');
    setHeartRateApps([]);
    setHeartRateAppsLoaded(false);
    try {
      const { data: userResult, error: userError } = await getSupabase().auth.getUser();
      if (userError) throw userError;
      if (!userResult.user) throw new Error('Sign in to view your app and heart-rate statistics.');

      const { data, error: queryError } = await getSupabase().rpc('top_apps_by_heart_rate');
      if (queryError) throw queryError;
      setHeartRateApps((data || []) as AppHeartRate[]);
      setHeartRateAppsLoaded(true);
    } catch (cause) {
      setHeartRateAppsError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setHeartRateAppsPending(false);
    }
  }

  async function showTopEventsByHeartRate() {
    setHeartRateEventsPending(true);
    setHeartRateEventsError('');
    setHeartRateEvents([]);
    setHeartRateEventsLoaded(false);
    try {
      const { data: userResult, error: userError } = await getSupabase().auth.getUser();
      if (userError) throw userError;
      if (!userResult.user) throw new Error('Sign in to view your calendar and heart-rate statistics.');

      const { data, error: queryError } = await getSupabase().rpc('top_calendar_events_by_heart_rate');
      if (queryError) throw queryError;
      setHeartRateEvents((data || []) as CalendarEventHeartRate[]);
      setHeartRateEventsLoaded(true);
    } catch (cause) {
      setHeartRateEventsError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setHeartRateEventsPending(false);
    }
  }

  async function showTopSpotifyTracks() {
    setSpotifyTracksPending(true);
    setSpotifyTracksError('');
    setSpotifyTracks([]);
    setSpotifyTracksLoaded(false);
    try {
      const { data: userResult, error: userError } = await getSupabase().auth.getUser();
      if (userError) throw userError;
      if (!userResult.user) throw new Error('Sign in to view your Spotify and heart-rate statistics.');

      const { data, error: queryError } = await getSupabase().rpc('top_spotify_tracks_by_gets_you_going');
      if (queryError) throw queryError;
      setSpotifyTracks((data || []) as SpotifyTrackScore[]);
      setSpotifyTracksLoaded(true);
    } catch (cause) {
      setSpotifyTracksError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSpotifyTracksPending(false);
    }
  }

  async function showFlowCandidates() {
    setFlowPending(true);
    setFlowError('');
    setFlowCandidates([]);
    setFlowLoaded(false);
    try {
      const { data: userResult, error: userError } = await getSupabase().auth.getUser();
      if (userError) throw userError;
      if (!userResult.user) throw new Error('Sign in to view your Flow State insights.');

      const { data, error: queryError } = await getSupabase().rpc('flow_state_candidates');
      if (queryError) throw queryError;
      const rows = (data || []) as FlowCandidate[];
      setFlowCandidates(Array.from(new Map(
        rows.map((block) => [`${block.event_category}:${block.event_title}:${block.starts_at}:${block.ends_at}`, block]),
      ).values()));
      setFlowLoaded(true);
    } catch (cause) {
      setFlowError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setFlowPending(false);
    }
  }

  async function showCardiacWrapped() {
    setCardiacWrappedPending(true);
    setCardiacWrappedError('');
    setCardiacWrapped([]);
    setWeeklySpotifyGetsYouGoing(null);
    setCardiacWrappedLoaded(false);
    try {
      const { data: userResult, error: userError } = await getSupabase().auth.getUser();
      if (userError) throw userError;
      if (!userResult.user) throw new Error('Sign in to view your Cardiac Wrapped insights.');

      const supabase = getSupabase();
      const [wrappedResult, getsYouGoingResult] = await Promise.all([
        supabase.rpc('cardiac_wrapped'),
        supabase.rpc('top_spotify_track_gets_you_going_this_week'),
      ]);
      if (wrappedResult.error) throw wrappedResult.error;
      if (getsYouGoingResult.error) throw getsYouGoingResult.error;
      setCardiacWrapped((wrappedResult.data || []) as CardiacWrappedResult[]);
      setWeeklySpotifyGetsYouGoing(((getsYouGoingResult.data || [])[0] as WeeklySpotifyGetsYouGoing | undefined) || null);
      setCardiacWrappedLoaded(true);
    } catch (cause) {
      setCardiacWrappedError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setCardiacWrappedPending(false);
    }
  }

  async function showMeetingHangoverIndex() {
    setMeetingHangoversPending(true);
    setMeetingHangoversError('');
    setMeetingHangovers([]);
    setMeetingHangoversLoaded(false);
    try {
      const { data: userResult, error: userError } = await getSupabase().auth.getUser();
      if (userError) throw userError;
      if (!userResult.user) throw new Error('Sign in to view your Meeting Hangover insights.');

      const { data, error: queryError } = await getSupabase().rpc('meeting_hangover_index');
      if (queryError) throw queryError;
      setMeetingHangovers((data || []) as MeetingHangoverResult[]);
      setMeetingHangoversLoaded(true);
    } catch (cause) {
      setMeetingHangoversError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setMeetingHangoversPending(false);
    }
  }

  return (
    <>
      {embedded ? <h2>Your week in numbers</h2> : <ViewHead eyebrow="Weekly" title="Your week in numbers" />}
      <section className="card stack" aria-live="polite">
        <button className="btn btn-primary" type="button" onClick={showTopApps} disabled={appsPending}>
          {appsPending ? 'Loading...' : 'Show my top five apps from the last week'}
        </button>
        {appsError ? <p className="small" role="alert">{appsError}</p> : null}
        {appsLoaded && apps.length === 0 ? <p className="small muted" role="status">No app usage was registered in the last seven days.</p> : null}
        {apps.length > 0 ? (
          <ol className="stack" aria-label="Most used apps in the last seven days">
            {apps.map((app) => (
              <li key={app.packageName}>
                <strong>{app.appName}</strong>
                <span className="small secondary"> — {app.minutes.toFixed(1)} min ({(app.minutes / 60).toFixed(1)} hr)</span>
              </li>
            ))}
          </ol>
        ) : null}
      </section>
      <section className="card stack" aria-live="polite">
        <button className="btn btn-primary" type="button" onClick={showTopAppsByHeartRate} disabled={heartRateAppsPending}>
          {heartRateAppsPending ? 'Loading...' : 'Show apps with the highest gets you going score'}
        </button>
        {heartRateAppsError ? <p className="small" role="alert">{heartRateAppsError}</p> : null}
        {heartRateAppsLoaded && heartRateApps.length === 0 ? <p className="small muted" role="status">No app sessions had at least two overlapping heart-rate samples.</p> : null}
        {heartRateApps.length > 0 ? (
          <ol className="stack" aria-label="Apps ranked by gets you going score">
            {heartRateApps.map((app) => (
              <li key={app.package_name}>
                <strong>{app.app_name}</strong>
                <span className="small secondary"> — Gets you going: {Number(app.gets_you_going_score).toFixed(1)}/100; peak session {Number(app.peak_session_score).toFixed(1)}/100; {Math.ceil(Number(app.avg_bpm))} bpm average, {Math.ceil(Number(app.peak_bpm))} bpm peak; {Number(app.total_minutes).toFixed(1)} min across {Number(app.sessions_measured)} measured sessions</span>
              </li>
            ))}
          </ol>
        ) : null}
      </section>
      <section className="card stack" aria-live="polite">
        <button className="btn btn-primary" type="button" onClick={showTopEventsByHeartRate} disabled={heartRateEventsPending}>
          {heartRateEventsPending ? 'Loading...' : 'Show calendar events with the highest gets you going score'}
        </button>
        {heartRateEventsError ? <p className="small" role="alert">{heartRateEventsError}</p> : null}
        {heartRateEventsLoaded && heartRateEvents.length === 0 ? <p className="small muted" role="status">No calendar events had at least two overlapping heart-rate samples.</p> : null}
        {heartRateEvents.length > 0 ? (
          <ol className="stack" aria-label="Calendar events ranked by gets you going score">
            {heartRateEvents.map((event) => (
              <li key={event.event_id}>
                <strong>{event.event_title || 'Untitled event'}</strong>
                <span className="small secondary"> — {new Date(event.starts_at).toLocaleDateString()} · {new Date(event.starts_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}–{new Date(event.ends_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span>
                <span className="small secondary"> — Gets you going: {Number(event.gets_you_going_score).toFixed(1)}/100; {Math.ceil(Number(event.avg_bpm))} bpm average; {Math.ceil(Number(event.min_bpm))}–{Math.ceil(Number(event.max_bpm))} bpm range ({Number(event.hr_sample_count)} samples)</span>
              </li>
            ))}
          </ol>
        ) : null}
      </section>
      <section className="card stack" aria-live="polite">
        <button className="btn btn-primary" type="button" onClick={showTopSpotifyTracks} disabled={spotifyTracksPending}>
          {spotifyTracksPending ? 'Loading...' : 'Show Spotify tracks with the highest gets you going score'}
        </button>
        {spotifyTracksError ? <p className="small" role="alert">{spotifyTracksError}</p> : null}
        {spotifyTracksLoaded && spotifyTracks.length === 0 ? <p className="small muted" role="status">No Spotify plays overlapped heart-rate samples.</p> : null}
        {spotifyTracks.length > 0 ? (
          <ol className="stack" aria-label="Spotify tracks ranked by gets you going score">
            {spotifyTracks.map((track) => (
              <li key={`${track.song_title}:${track.artist_name}`}>
                <strong>{track.song_title}</strong>
                <span className="small secondary"> by {track.artist_name} — Gets you going: {Number(track.gets_you_going_score).toFixed(1)}/100; {Math.ceil(Number(track.avg_bpm))} bpm average, {Math.ceil(Number(track.peak_bpm))} bpm peak; {Math.ceil(Number(track.bpm_above_resting))} bpm above resting; played {Number(track.times_played)} times</span>
              </li>
            ))}
          </ol>
        ) : null}
      </section>
      <section className="card stack" aria-live="polite">
        <button className="btn btn-primary" type="button" onClick={showFlowCandidates} disabled={flowPending}>
          {flowPending ? 'Loading...' : 'Find my Flow State patterns'}
        </button>
        <p className="small muted">Ranks calendar events from the last 30 days by lower average heart rate, steadier heart rate, and less recorded screen use. Screen use is estimated from overlapping app sessions and unlock events; results are associations, not proof of cause.</p>
        {flowError ? <p className="small" role="alert">{flowError}</p> : null}
        {flowLoaded && flowCandidates.length === 0 ? <p className="small muted" role="status">No calendar events with at least two heart-rate samples were found in the last 30 days.</p> : null}
        {flowCandidates.length > 0 ? (
          <ol className="stack" aria-label="Calendar events ranked by calm and screen use">
            {flowCandidates.map((block) => (
              <li key={`${block.event_category}:${block.event_title}:${block.starts_at}:${block.ends_at}`}>
                <strong>{block.event_title || 'Untitled event'}</strong>
                <span className="small secondary"> — {block.event_category}</span>
                <span className="small secondary"> — {new Date(block.starts_at).toLocaleDateString()} · {new Date(block.starts_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}–{new Date(block.ends_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span>
                <span className="small secondary"> — Average HR: {Number(block.avg_bpm).toFixed(1)} bpm; HR variability: {Number(block.hr_variability_bpm).toFixed(1)} bpm ({Number(block.hr_sample_count)} samples); screen use: {Number(block.screen_minutes).toFixed(1)} min across {Number(block.app_sessions)} app sessions; {Number(block.unlocks_during_event)} unlocks</span>
              </li>
            ))}
          </ol>
        ) : null}
      </section>
      <section className="card stack" aria-live="polite">
        <button className="btn btn-primary" type="button" onClick={showCardiacWrapped} disabled={cardiacWrappedPending}>
          {cardiacWrappedPending ? 'Loading...' : 'Generate my Cardiac Wrapped'}
        </button>
        <p className="small muted">Uses the last seven days. “Stationary” means 2,000 or fewer recorded daily steps; the calmer comparison is heart rate outside logged Spotify playback, not verified silence.</p>
        {cardiacWrappedError ? <p className="small" role="alert">{cardiacWrappedError}</p> : null}
        {cardiacWrappedLoaded && cardiacWrapped.length === 0 && !weeklySpotifyGetsYouGoing ? <p className="small muted" role="status">There was not enough matching Spotify, heart-rate, focus, or activity data to create an archetype.</p> : null}
        {cardiacWrapped.length > 0 || weeklySpotifyGetsYouGoing ? (
          <ul className="stack" aria-label="Cardiac Wrapped archetypes">
            {weeklySpotifyGetsYouGoing ? (
              <li className="stack" key="gets-you-going">
                <span><span className="badge badge-low">Gets You Going</span></span>
                <strong>{weeklySpotifyGetsYouGoing.song_title}</strong>
                <span className="small secondary">Artist: {weeklySpotifyGetsYouGoing.artist_name}</span>
                <span className="small secondary">Highest song score this week: {Number(weeklySpotifyGetsYouGoing.gets_you_going_score).toFixed(1)}/100; average HR {Number(weeklySpotifyGetsYouGoing.avg_bpm).toFixed(1)} bpm; peak HR {Number(weeklySpotifyGetsYouGoing.peak_bpm).toFixed(1)} bpm; {Number(weeklySpotifyGetsYouGoing.bpm_above_resting).toFixed(1)} bpm above resting; {Number(weeklySpotifyGetsYouGoing.times_played)} measured play(s).</span>
              </li>
            ) : null}
            {cardiacWrapped.map((result) => (
              <li className="stack" key={result.archetype}>
                <span><span className="badge badge-low">{result.archetype}</span></span>
                <strong>{result.archetype === 'True Calmer' ? result.artist_name : result.item_title}</strong>
                {result.archetype !== 'True Calmer' && result.artist_name
                  ? <span className="small secondary">Artist: {result.artist_name}</span>
                  : null}
                <span className="small secondary">{result.archetype === 'Cardiac Anthem'
                  ? `Heart-rate surge: ${Number(result.primary_value).toFixed(1)} bpm; peak: ${Number(result.comparison_value).toFixed(1)} bpm.`
                  : result.archetype === 'True Calmer'
                    ? `Average heart rate: ${Number(result.primary_value).toFixed(1)} bpm below the non-Spotify comparison; artist-play average: ${Number(result.comparison_value).toFixed(1)} bpm.`
                    : `Heart-rate variation: ${Number(result.primary_value).toFixed(1)} bpm; average: ${Number(result.comparison_value).toFixed(1)} bpm.`}</span>
                <span className="small muted">{result.note} {Number(result.sample_count)} heart-rate samples across {Number(result.plays_count)} play(s).</span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
      <section className="card stack" aria-live="polite">
        <button className="btn btn-primary" type="button" onClick={showMeetingHangoverIndex} disabled={meetingHangoversPending}>
          {meetingHangoversPending ? 'Loading...' : 'Show my Meeting Hangover Index'}
        </button>
        <p className="small muted">Ranks meetings from the last 30 days by heart-rate change during the three hours afterward versus the hour before. Same-night resting HR and deep sleep are compared with your 30-day average when available. Attendee names are not shown.</p>
        {meetingHangoversError ? <p className="small" role="alert">{meetingHangoversError}</p> : null}
        {meetingHangoversLoaded && meetingHangovers.length === 0 ? <p className="small muted" role="status">No meetings with enough pre- and post-meeting heart-rate samples were found in the last 30 days.</p> : null}
        {meetingHangovers.length > 0 ? (
          <ol className="stack" aria-label="Meetings ranked by post-meeting heart-rate drift">
            {meetingHangovers.map((meeting) => (
              <li key={meeting.event_id}>
                <strong>{meeting.event_title || 'Untitled meeting'}</strong>
                <span className="small secondary"> — {new Date(meeting.starts_at).toLocaleDateString()} · {new Date(meeting.starts_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}–{new Date(meeting.ends_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}; {meeting.attendee_count ?? 0} attendee(s)</span>
                <span className="small secondary"> — Post-meeting HR drift: {meeting.post_meeting_hr_drift == null ? 'unavailable' : `${Number(meeting.post_meeting_hr_drift) > 0 ? '+' : ''}${Number(meeting.post_meeting_hr_drift).toFixed(1)} bpm`}; same-night resting HR {meeting.night_resting_hr_delta == null ? 'unavailable' : `${Number(meeting.night_resting_hr_delta) > 0 ? '+' : ''}${Number(meeting.night_resting_hr_delta).toFixed(1)} bpm vs baseline`}; deep sleep {meeting.deep_sleep_delta_min == null ? 'unavailable' : `${Number(meeting.deep_sleep_delta_min) > 0 ? '+' : ''}${Number(meeting.deep_sleep_delta_min).toFixed(1)} min vs baseline`} ({Number(meeting.post_hr_sample_count)} post-meeting samples)</span>
              </li>
            ))}
          </ol>
        ) : null}
      </section>
    </>
  );
}
