'use client';

import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from 'react';
import { api } from '@/lib/api';
import { Icon } from '../ui/Icon';
import { ActionButton, RevealHeading, RevealSection } from '../ui/Motion';
import { toast } from '../ui/overlays';
import { useLoad } from './common';

type Provider = 'spotify' | 'netflix' | 'steam' | 'youtube';
type MediaEvent = { id: string; provider: string; occurred_at: string; title: string; creator?: string | null; minutes: number; source?: { media_kind?: string; date_only?: boolean; duration_known?: boolean; profile?: string; artwork_url?: string | null; artwork_query?: string | null; artwork_status?: string; artwork_page?: string; album?: string; url?: string } };
type SteamGame = { appid: number; name: string; minutes: number; recent_minutes: number; last_played: string | null; artwork_url?: string };
type PosterPatch = { query: string; source: NonNullable<MediaEvent['source']> };
type MediaDocument = { id: string; filename: string; kind: string; payload: { taste?: Record<string, string>; albums?: { artist: string; album: string }[]; shows?: { name: string; publisher: string }[]; saved_track_count?: number; followed_artist_count?: number; games?: SteamGame[]; snapshot_at?: string; origin?: string; steam_id?: string; username?: string; profile_url?: string; last_synced_at?: string; history_has_more?: boolean; pending?: { page: number } | null; top_artists?: { numUniqueArtists?: number }; top_tracks?: { numUniqueTracks?: number }; top_genres?: { totalNumGenres?: number } } };
type LastfmStatus = { available: boolean; connected: boolean; configured: boolean; message: string; username: string | null; profile_url: string | null };
type SteamStatus = { configured: boolean; message: string; user_id: string; steam_id: string | null };
type MediaPayload = { events: MediaEvent[]; recent_by_provider: Record<string, MediaEvent[]>; total: number; totals: Record<string, { items: number; minutes: number }>; documents: MediaDocument[] };
type HistoryPage = { events: MediaEvent[]; total: number };
const names = { spotify: 'Spotify', netflix: 'Netflix', steam: 'Steam', youtube: 'YouTube', lastfm: 'Last.fm' };
const icons = { spotify: 'music', netflix: 'screen', steam: 'gamepad', youtube: 'play', lastfm: 'music' };

// Fixed positions and negative delays keep the initial render stable and the stream already in motion.
const logoBubbles = [
  { provider: 'spotify', x: 8, size: 82, duration: 34, delay: -9, sway: 30, stillY: 18 },
  { provider: 'netflix', x: 22, size: 58, duration: 30, delay: -22, sway: -24, stillY: 65 },
  { provider: 'steam', x: 39, size: 96, duration: 40, delay: -18, sway: 34, stillY: 30 },
  { provider: 'spotify', x: 58, size: 54, duration: 29, delay: -5, sway: -28, stillY: 72 },
  { provider: 'netflix', x: 76, size: 88, duration: 38, delay: -25, sway: 22, stillY: 22 },
  { provider: 'steam', x: 88, size: 62, duration: 32, delay: -14, sway: -34, stillY: 58 },
  { provider: 'netflix', x: 12, size: 48, duration: 35, delay: -29, sway: 28, stillY: 43 },
  { provider: 'steam', x: 29, size: 66, duration: 37, delay: -3, sway: -20, stillY: 82 },
  { provider: 'spotify', x: 47, size: 78, duration: 33, delay: -23, sway: 26, stillY: 12 },
  { provider: 'steam', x: 65, size: 48, duration: 31, delay: -27, sway: -30, stillY: 48 },
  { provider: 'spotify', x: 81, size: 68, duration: 39, delay: -12, sway: 24, stillY: 80 },
  { provider: 'netflix', x: 52, size: 60, duration: 36, delay: -16, sway: -22, stillY: 56 },
] as const;

function MediaLogoBubbles() {
  return <div className="media-logo-bubbles" aria-hidden="true">
    {logoBubbles.map((bubble, index) => <span className="media-logo-bubble" data-provider={bubble.provider} key={index} style={{
      '--bubble-x': `${bubble.x}%`, '--bubble-size': `${bubble.size}px`, '--bubble-sway': `${bubble.sway}px`,
      '--bubble-duration': `${bubble.duration}s`, '--bubble-delay': `${bubble.delay}s`, '--bubble-still-y': `${bubble.stillY}%`,
    } as CSSProperties}><span className="media-logo-mark" /></span>)}
  </div>;
}

function mediaDate(value: string, dateOnly = false) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', ...(dateOnly ? { timeZone: 'UTC' } : {}) }).format(new Date(value));
}
function hours(minutes: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(minutes / 60) + ' h';
}
function formattedTaste(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith('**') && part.endsWith('**')
    ? <strong key={index}>{part.slice(2, -2)}</strong> : <span key={index}>{part}</span>);
}

function CollectionPlaceholder({ provider, title, children, features }: { provider: Provider; title: string; children: ReactNode; features: string[] }) {
  return <div className="media-placeholder">
    <span className="media-placeholder-icon" aria-hidden="true"><Icon name={icons[provider]} size={30} /></span>
    <div><span className="eyebrow">Here whenever you’re ready</span><h3>{title}</h3><p>{children}</p>
      <ul aria-label={names[provider] + ' features'}>{features.map((feature) => <li key={feature}>{feature}</li>)}</ul>
      <p className="media-placeholder-note">No setup needed to explore the page. Each source works independently.</p>
    </div>
  </div>;
}

function ImportMedia({ provider, onImported, disabled = false, onBusyChange, afterImport }: { provider: Provider; onImported: (data: MediaPayload) => void; disabled?: boolean; onBusyChange?: (busy: boolean) => void; afterImport?: () => Promise<void> }) {
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [youtubeRange, setYoutubeRange] = useState('90');
  const [summary, setSummary] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const upload = async () => {
    if (!files.length || busy || disabled) return;
    setBusy(true); onBusyChange?.(true); setError(''); setSummary('');
    try {
      const result = await api.upload<MediaPayload & { imported: number; skipped?: number }>('/api/media/import?provider=' + provider + (provider === 'youtube' ? '&youtube_range=' + youtubeRange : ''), files);
      onImported(result); setFiles([]);
      if (provider === 'youtube') setSummary(`Imported ${result.imported.toLocaleString()} viewing entries. ${(result.skipped || 0).toLocaleString()} skipped outside the selected period or beyond the 5,000-entry limit.`);
      if (input.current) input.current.value = '';
      toast(`Imported ${result.imported.toLocaleString()} ${provider === 'steam' ? 'games' : 'records'} from ${names[provider]}.`, { kind: 'success' });
      await afterImport?.();
    } catch (err) { setError(err instanceof Error ? err.message : 'Import failed. Please try again.'); }
    finally { setBusy(false); onBusyChange?.(false); }
  };
  return <details className="media-import">
    <summary><Icon name="upload" size={16} /> Import {names[provider]} {provider === 'netflix' ? 'CSV' : 'JSON'}</summary>
    <div className="media-import-body">
      {provider === 'youtube' && <ol className="media-setup-steps"><li>Open <a href="https://takeout.google.com/" target="_blank" rel="noreferrer">Google Takeout ↗</a>, deselect all, then choose YouTube and YouTube Music.</li><li>Keep history selected and choose JSON for history under the available format options. Create your export and wait for Google’s download link.</li><li>Unzip the download and select watch-history.json below. Select all history parts together if your export is split. No API key is needed.</li></ol>}
      {provider === 'netflix' && <ol className="media-setup-steps"><li>Open Netflix in a browser, then go to Account → Profiles → your profile → Viewing activity.</li><li>Select Download all at the bottom to get your CSV. Repeat for any other profiles you want to include.</li><li>Choose the files below and click Import Netflix. No API key is needed. <a href="https://help.netflix.com/en/node/101917" target="_blank" rel="noreferrer">Netflix’s download guide ↗</a></li></ol>}
      {provider === 'spotify' && <ol className="media-setup-steps"><li>Request your listening data from <a href="https://www.spotify.com/account/privacy/" target="_blank" rel="noreferrer">Spotify’s account privacy page ↗</a>.</li><li>When it arrives, unzip the download and choose your history JSON files below.</li><li>Click Import Spotify. You can also use the optional Last.fm connection further down.</li></ol>}
      <p>{provider === 'spotify' ? 'Choose your music and podcast histories together. Taste Profile, Your Library and Wrapped summaries are also supported.' : provider === 'netflix' ? 'Download Viewing activity from your Netflix profile. Select both CSVs together to include both profiles. Dates use M/D/YY or YYYY-MM-DD; each filename labels its profile.' : provider === 'youtube' ? 'Import watch-history.json from Google Takeout. Video titles, channel names and timestamps are kept; actual watch duration is unavailable. Entries marked as Google ads are excluded. Search-history files are not viewing history.' : 'Upload one JSON response from Steam GetOwnedGames (include_appinfo=true) or GetRecentlyPlayedGames. The response must contain a games array.'}</p>
      {provider === 'youtube' && <label className="media-file-label">History to import<select className="input" value={youtubeRange} disabled={busy || disabled} onChange={(event) => { setYoutubeRange(event.target.value); setSummary(''); }}><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="all">All history (latest 5,000 entries)</option></select><span className="tiny muted">Up to 5,000 of the newest entries across all selected files. The period is relative to today. Your original export is unchanged.</span></label>}
      <label className="media-file-label">{names[provider]} export {provider === 'steam' ? 'file' : 'files'}
        <input ref={input} className="input" type="file" multiple={provider !== 'steam'} disabled={busy || disabled} accept={provider === 'netflix' ? '.csv,text/csv' : '.json,application/json'} onChange={(event) => { setFiles(Array.from(event.target.files || [])); setError(''); }} />
      </label>
      <p className="tiny muted">{provider === 'steam' ? 'Each import replaces the previous Steam snapshot.' : 'History imports replace this source’s history. Select all files you want to keep together.'} Up to {provider === 'youtube' ? '32' : '4'} MB total. Original files are discarded after parsing.</p>
      {files.length > 0 && <p className="small secondary">{files.length} {files.length === 1 ? 'file' : 'files'} selected</p>}
      <ActionButton className="btn btn-primary" disabled={!files.length || busy || disabled} aria-busy={busy} onClick={upload}><Icon name="upload" size={16} />{busy ? 'Importing…' : 'Import ' + names[provider]}</ActionButton>
      {summary && <p className="media-data-note" role="status">{summary}</p>}
      {error && <p className="media-error" role="alert">{error}</p>}
    </div>
  </details>;
}

function SteamSync({ busy, setBusy, disabled, onSynced }: { busy: boolean; setBusy: (busy: boolean) => void; disabled: boolean; onSynced: (data: MediaPayload) => void }) {
  const status = useLoad(() => api.get<SteamStatus>('/api/media/steam'), []);
  const [error, setError] = useState('');
  const [syncing, setSyncing] = useState(false);
  const sync = async () => {
    if (busy || disabled || !status.data?.configured) return;
    setBusy(true); setSyncing(true); setError('');
    try {
      const result = await api.post<MediaPayload>('/api/media/steam/sync');
      onSynced(result);
      const count = result.documents.find((document) => document.kind === 'steam_library')?.payload.games?.length || 0;
      toast(`Steam synced. ${count.toLocaleString()} games in your library.`, { kind: 'success' });
    } catch (err) { setError(err instanceof Error ? err.message : 'Steam sync failed. Please try again.'); }
    finally { setBusy(false); setSyncing(false); }
  };
  return <div className="media-steam-sync">
    <div className="media-sync-row"><div><strong>{status.data && !status.data.configured ? 'Steam sync is available' : 'Refresh from Steam'}</strong><p>{status.loading ? 'Checking your Steam setup…' : status.data?.configured ? 'Fetch your latest games and playtime directly from Steam.' : status.error ? 'Setup is temporarily unavailable. Saved games and file imports still work.' : 'Not enabled for this account yet. Bring in your library and playtime whenever you’re ready, or use a JSON import below.'}</p></div>
      <ActionButton className="btn btn-primary" disabled={busy || disabled || status.loading || !status.data?.configured} aria-busy={syncing} onClick={sync}><Icon name="refresh" size={16} />{syncing ? 'Syncing…' : 'Sync now'}</ActionButton>
    </div>
    {status.error && <p className="media-error" role="alert">Couldn’t check Steam setup: {status.error.message} <button className="media-inline-button" onClick={status.reload}>Retry</button></p>}
    {status.data && <details className="media-sync-setup"><summary>{status.data.configured ? 'Steam account details' : 'How to enable Steam sync'}</summary><div>
      {status.data.configured ? <><p>{status.data.message}</p><p>SteamID64: <code>{status.data.steam_id}</code></p></> : <>
        <p>Steam sync isn’t enabled for your account yet. You can still bring in your games with a JSON import below.</p>
      </>}
    </div></details>}
    {error && <p className="media-error" role="alert">{error}</p>}
  </div>;
}

// Share in-flight cover lookups between the featured listen and repeated album rows.
const artworkRequests = new Map<string, Promise<string | null>>();
let artworkQueue: Promise<unknown> = Promise.resolve();
function albumArtwork(artist: string, album: string) {
  const key = JSON.stringify([artist, album]);
  const cached = artworkRequests.get(key);
  if (cached) return cached;
  const request = artworkQueue.then(async () => {
    try { return (await api.get<{ artwork_url: string | null }>('/api/media/lastfm/artwork?artist=' + encodeURIComponent(artist) + '&album=' + encodeURIComponent(album))).artwork_url; }
    catch { return null; }
  });
  // Pace cache misses; covers outside the viewport do not enter this queue.
  artworkQueue = request.then(() => new Promise((resolve) => setTimeout(resolve, 300)));
  if (artworkRequests.size >= 256) artworkRequests.delete(artworkRequests.keys().next().value!);
  artworkRequests.set(key, request);
  return request;
}

function Artwork({ event, featured = false }: { event: MediaEvent; featured?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [cover, setCover] = useState<string | null>(null);
  const [failedUrls, setFailedUrls] = useState<string[]>([]);
  const attemptedLookup = useRef(false);
  const direct = event.source?.artwork_url;
  const url = cover && !failedUrls.includes(cover) ? cover : direct && !failedUrls.includes(direct) ? direct : null;
  const artist = event.creator;
  const album = event.source?.album;
  useEffect(() => {
    if (event.provider !== 'lastfm' || url || !artist || !album || !ref.current || attemptedLookup.current) return;
    let current = true;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      attemptedLookup.current = true;
      albumArtwork(artist, album).then((result) => { if (current) setCover(result); });
    });
    observer.observe(ref.current);
    return () => { current = false; observer.disconnect(); };
  }, [url, artist, album, event.provider]);
  return <span ref={ref} className={'media-artwork' + (featured ? ' is-featured' : '') + (event.provider === 'netflix' ? ' is-poster' : event.provider === 'youtube' ? ' is-video' : '')}>
    {url ? <img src={url} alt={`${event.source?.album || event.title} ${event.provider === 'netflix' ? 'poster' : 'cover'}`} width={featured ? 180 : 52} height={featured ? 180 : 52} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailedUrls((current) => [...current, url])} /> : <Icon name={event.provider === 'netflix' ? 'screen' : event.provider === 'youtube' ? 'play' : 'music'} size={featured ? 44 : 20} />}
  </span>;
}

function SteamCover({ game, rank }: { game: SteamGame; rank: number }) {
  const [failed, setFailed] = useState(false);
  return <div className="media-game-cover">
    {game.artwork_url && !failed ? <img src={game.artwork_url} alt={`${game.name} artwork`} width={460} height={215} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} /> : <><span>{String(rank).padStart(2, '0')}</span><Icon name="gamepad" size={38} /><span>STEAM / {game.appid}</span></>}
  </div>;
}

function LastfmPanel({ data, disabled, onSynced }: { data: MediaPayload | null; disabled: boolean; onSynced: (data: MediaPayload) => void }) {
  const status = useLoad(() => api.get<LastfmStatus>('/api/media/lastfm'), []);
  const [busy, setBusy] = useState<'latest' | 'older' | 'connect' | 'disconnect' | null>(null);
  const [error, setError] = useState('');
  const [username, setUsername] = useState('');
  const state = data?.documents.find((doc) => doc.kind === 'lastfm_sync')?.payload;
  const events = data?.recent_by_provider.lastfm || emptyHistory;
  const total = data?.totals.lastfm?.items || 0;
  const latest = events[0];
  const sync = async (older = false) => {
    if (busy || disabled || !status.data?.configured) return;
    setBusy(older ? 'older' : 'latest'); setError('');
    try {
      const result = await api.post<MediaPayload>('/api/media/lastfm/sync' + (older ? '?older=true' : ''));
      onSynced(result);
      toast(older ? 'Older Last.fm listening saved.' : 'Last.fm listening refreshed.', { kind: 'success' });
    } catch (err) { setError(err instanceof Error ? err.message : 'Last.fm sync failed. Please try again.'); }
    finally { setBusy(null); }
  };
  const connect = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || !username.trim()) return;
    setBusy('connect'); setError('');
    try {
      status.setData(await api.post<LastfmStatus>('/api/media/lastfm/connect', { username: username.trim() }));
      setUsername('');
      toast('Last.fm connected. Click Sync now to bring in your listening.', { kind: 'success' });
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not connect Last.fm. Please try again.'); }
    finally { setBusy(null); }
  };
  const disconnect = async () => {
    if (busy || !window.confirm('Disconnect ' + status.data?.username + ' from Last.fm? Your saved scrobbles in StressLess are deleted; nothing changes on Last.fm.')) return;
    setBusy('disconnect'); setError('');
    try {
      const result = await api.post<MediaPayload & { status: LastfmStatus }>('/api/media/lastfm/disconnect');
      status.setData(result.status);
      onSynced(result);
      toast('Last.fm disconnected.', { kind: 'success' });
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not disconnect Last.fm. Please try again.'); }
    finally { setBusy(null); }
  };
  return <div className="media-lastfm-panel" id="media-lastfm">
    <div className="media-source-bar"><span><Icon name="music" size={20} /> Last.fm</span><span className="media-source-status" role="status">{state?.last_synced_at ? 'Last synced ' + new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(state.last_synced_at)) : 'Your ongoing listening journal'}</span></div>
    <div className="media-lastfm-controls"><div><h3>Your soundtrack, kept up to date.</h3><p>{status.loading ? 'Checking your Last.fm setup…' : status.data?.connected ? 'Connected as ' + status.data.username + '. Bring your scrobbles into StressLess, with artwork from Last.fm.' : status.error ? 'Setup is temporarily unavailable. Spotify imports and saved listening still work.' : status.data && !status.data.available ? 'Last.fm sync isn’t available right now. Your saved listening is still here.' : 'Connect your Last.fm account to bring in your listening, or keep using Spotify file imports.'}</p></div>
      <ActionButton className="btn btn-primary" disabled={!!busy || disabled || !status.data?.configured} aria-busy={busy === 'latest'} onClick={() => sync()}><Icon name="refresh" size={16} />{busy === 'latest' ? 'Syncing…' : state?.pending ? 'Continue sync' : 'Sync now'}</ActionButton></div>
    {status.error && <p className="media-error" role="alert">Couldn’t check Last.fm setup: {status.error.message} <button className="media-inline-button" onClick={status.reload}>Retry</button></p>}
    {status.data?.available && !status.data.connected && <form className="media-lastfm-connect" onSubmit={connect}>
      <ol className="media-setup-steps"><li><a href="https://www.last.fm/join" target="_blank" rel="noreferrer">Create a free Last.fm account ↗</a> and <a href="https://www.last.fm/about/trackmymusic" target="_blank" rel="noreferrer">connect Spotify scrobbling ↗</a>, so new listens are recorded.</li><li>Make sure “Hide recent listening information” is off in your <a href="https://www.last.fm/settings/privacy" target="_blank" rel="noreferrer">Last.fm privacy settings ↗</a>.</li><li>Enter your Last.fm username below. No password needed: StressLess only reads your public listening.</li></ol>
      <div className="row"><input className="input" type="text" name="lastfm-username" aria-label="Last.fm username" placeholder="Last.fm username" autoComplete="username" spellCheck={false} maxLength={15} value={username} disabled={!!busy || disabled} onChange={(e) => setUsername(e.target.value)} />
        <ActionButton type="submit" className="btn btn-primary" disabled={!!busy || disabled || !username.trim()} aria-busy={busy === 'connect'}>{busy === 'connect' ? 'Checking…' : 'Connect'}</ActionButton></div>
    </form>}
    {status.data?.connected && <p className="media-data-note">Connected as <a href={status.data.profile_url || undefined} target="_blank" rel="noreferrer">{status.data.username} ↗</a> · <button type="button" className="media-inline-button" disabled={!!busy} onClick={disconnect}>{busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect'}</button></p>}
    {error && <p className="media-error" role="alert">{error}</p>}
    {state?.pending && <p className="media-data-note" role="status">More new listening is waiting. Continue sync to save the next batch without skipping any tracks.</p>}
    {latest && <div className="media-lastfm-feature"><Artwork key={latest.id + latest.source?.artwork_url} event={latest} featured /><div><span className="eyebrow">Latest saved listen</span><h3>{latest.source?.url ? <a href={latest.source.url} target="_blank" rel="noreferrer">{latest.title}</a> : latest.title}</h3><p>{latest.creator}</p>{latest.source?.album && <span>{latest.source.album}</span>}<time dateTime={latest.occurred_at}>{new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(latest.occurred_at))}</time></div></div>}
    {!!total && <History provider="lastfm" seed={events} total={total} />}
    {!total && state?.last_synced_at && <p className="media-empty">No scrobbles found yet. If your Last.fm profile shows listens, turn off “Hide recent listening information” in your Last.fm privacy settings and sync again.</p>}
    {state?.history_has_more && <ActionButton className="btn media-more" disabled={!!busy || disabled || !status.data?.configured} aria-busy={busy === 'older'} onClick={() => sync(true)}>{busy === 'older' ? 'Loading older listening…' : 'Load older listening'}<Icon name="arrow-down" size={14} /></ActionButton>}
    {(!!total || status.data?.configured) && <p className="media-data-note">{total.toLocaleString()} saved scrobbles · Up to 200 per sync. Last.fm does not supply playback duration. Spotify exports are shown separately and are not added to these counts. Sync runs when you click.</p>}
    <p className="media-lastfm-credit">Listening data and artwork from <a href={state?.profile_url || status.data?.profile_url || 'https://www.last.fm'} target="_blank" rel="noreferrer">Last.fm ↗</a></p>
  </div>;
}

function History({ provider, seed, total }: { provider: 'spotify' | 'netflix' | 'lastfm' | 'youtube'; seed: MediaEvent[]; total: number }) {
  const [events, setEvents] = useState(seed);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  useEffect(() => { generation.current++; setEvents(seed); setBusy(false); setError(''); return () => { generation.current++; }; }, [seed]);
  const more = async () => {
    const requestGeneration = generation.current;
    setBusy(true); setError('');
    try {
      const page = await api.get<HistoryPage>(`/api/media?provider=${provider}&offset=${events.length}&limit=50`);
      if (generation.current === requestGeneration) setEvents((current) => [...current, ...page.events]);
    } catch (err) { if (generation.current === requestGeneration) setError(err instanceof Error ? err.message : 'Unable to load history.'); }
    finally { if (generation.current === requestGeneration) setBusy(false); }
  };
  return <div className="media-history">
    <div className="media-list-heading"><h3>{provider === 'lastfm' ? 'Scrobble history' : provider === 'spotify' ? 'Listening history' : 'Viewing history'}</h3><span>{events.length.toLocaleString()} of {total.toLocaleString()}</span></div>
    <div className="v-media-recent-scroll" role="region" aria-label={names[provider] + ' history'} tabIndex={0}>
      <ol className="media-history-list">{events.map((event) => <li key={event.id}>
        {provider === 'lastfm' || provider === 'netflix' || provider === 'youtube' ? <Artwork key={event.source?.artwork_url} event={event} /> : <span className="media-item-icon"><Icon name={event.source?.media_kind === 'podcast' ? 'podcast' : icons[provider]} size={20} /></span>}
        <div className="media-item-copy"><strong>{(provider === 'lastfm' || provider === 'youtube') && event.source?.url ? <a href={event.source.url} target="_blank" rel="noreferrer">{provider === 'youtube' ? event.title.replace(/^(?:Watched|Tittade på)\s+/u, '') : event.title}</a> : provider === 'youtube' ? event.title.replace(/^(?:Watched|Tittade på)\s+/u, '') : event.title}</strong><span>{event.creator || event.source?.profile || names[provider]}{event.source?.album ? ' · ' + event.source.album : ''}{event.source?.media_kind === 'podcast' ? ' · Podcast' : ''}</span></div>
        <div className="media-item-meta"><time dateTime={event.occurred_at}>{provider === 'lastfm' || provider === 'youtube' ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(event.occurred_at)) : mediaDate(event.occurred_at, event.source?.date_only)}</time><span>{provider === 'lastfm' || provider === 'youtube' || (provider === 'netflix' && !event.source?.duration_known) ? 'Duration unavailable' : Math.round(event.minutes).toLocaleString() + ' min'}</span></div>
      </li>)}</ol>
    </div>
    {events.length < total && <ActionButton className="btn media-more" disabled={busy} aria-busy={busy} onClick={more}>{busy ? 'Loading…' : 'Load more history'}<Icon name="arrow-down" size={14} /></ActionButton>}
    {error && <p className="media-error" role="alert">{error}</p>}
  </div>;
}

function SpotifyDocuments({ documents }: { documents: MediaDocument[] }) {
  return <div className="media-documents">{documents.filter((document) => ['taste_profile', 'library', 'wrapped'].includes(document.kind)).map((document) => {
    const p = document.payload;
    return <details className="media-document" key={document.id}>
      <summary>{document.kind === 'taste_profile' ? 'Your taste profile' : document.kind === 'library' ? 'Your saved library' : 'Your Wrapped summary'}<span>{document.filename}</span></summary>
      <div className="media-document-body">
        {document.kind === 'taste_profile' && Object.entries(p.taste || {}).map(([label, text]) => <div key={label}><h4>{label.replace(/[A-Z]/g, (letter) => ' ' + letter)}</h4><p>{formattedTaste(text)}</p></div>)}
        {document.kind === 'library' && <><p>{p.saved_track_count || 0} saved tracks · {p.albums?.length || 0} albums · {p.followed_artist_count || 0} followed artists</p><div className="grid grid-2"><div><h4>Saved albums</h4>{(p.albums || []).slice(0, 12).map((album, index) => <p key={index}>{album.album} · {album.artist}</p>)}</div><div><h4>Saved shows</h4>{(p.shows || []).slice(0, 12).map((show, index) => <p key={index}>{show.name} · {show.publisher}</p>)}</div></div></>}
        {document.kind === 'wrapped' && <p>{p.top_artists?.numUniqueArtists || 0} artists · {p.top_tracks?.numUniqueTracks || 0} tracks · {p.top_genres?.totalNumGenres || 0} genres</p>}
      </div>
    </details>;
  })}</div>;
}

const emptyHistory: MediaEvent[] = [];
export function MediaView() {
  const media = useLoad(() => api.get<MediaPayload>('/api/media'), []);
  const [paused, setPaused] = useState(false);
  const [gameSearch, setGameSearch] = useState('');
  const [gameSort, setGameSort] = useState('minutes');
  const [steamBusy, setSteamBusy] = useState(false);
  const posters = useLoad(() => api.get<{ configured: boolean; message: string }>('/api/media/netflix/artwork'), []);
  const [posterBusy, setPosterBusy] = useState(false);
  const [netflixImportBusy, setNetflixImportBusy] = useState(false);
  const [posterCount, setPosterCount] = useState(0);
  const [posterError, setPosterError] = useState('');
  const [posterNote, setPosterNote] = useState('');
  const posterRunning = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const currentMedia = useRef(media.data);
  currentMedia.current = media.data;
  const acceptMedia = (result: MediaPayload) => { currentMedia.current = result; media.setData(result); };
  const fetchPosters = async () => {
    if (posterRunning.current || !posters.data?.configured) return;
    posterRunning.current = true; setPosterBusy(true); setPosterCount(0); setPosterError(''); setPosterNote('');
    let checked = 0;
    try {
      while (mounted.current) {
        const result = await api.post<{ updates: PosterPatch[]; has_more: boolean; error: string | null }>('/api/media/netflix/artwork');
        if (!mounted.current) break;
        checked += result.updates.length; setPosterCount(checked);
        const source = currentMedia.current;
        if (source && result.updates.length) {
          const patches = new Map(result.updates.map((update) => [update.query, update.source]));
          const enrich = (event: MediaEvent) => event.provider === 'netflix' && event.source?.artwork_query && patches.has(event.source.artwork_query)
            ? { ...event, source: { ...event.source, ...patches.get(event.source.artwork_query) } } : event;
          acceptMedia({ ...source, events: source.events.map(enrich), recent_by_provider: { ...source.recent_by_provider, netflix: (source.recent_by_provider.netflix || []).map(enrich) } });
        }
        if (result.error) throw new Error(result.error);
        if (!result.has_more) { setPosterNote(checked ? 'Poster lookup complete. Ambiguous or unavailable titles keep a placeholder.' : 'No pending titles. Reimport older Netflix CSV uploads once to enable poster matching.'); break; }
        if (!result.updates.length) throw new Error('Poster fetching stopped making progress. Your history is saved; try again.');
      }
    } catch (err) { if (mounted.current) setPosterError(err instanceof Error ? err.message : 'Poster fetching failed. Your history is saved; try again.'); }
    finally { posterRunning.current = false; if (mounted.current) setPosterBusy(false); }
  };
  const data = media.data;
  const steam = data?.documents.find((document) => document.kind === 'steam_library');
  const games = steam?.payload.games || [];
  const filteredGames = games.filter((game) => game.name.toLowerCase().includes(gameSearch.toLowerCase())).sort((a, b) => gameSort === 'name' ? a.name.localeCompare(b.name) : gameSort === 'last_played' ? (b.last_played || '').localeCompare(a.last_played || '') : b.minutes - a.minutes);
  const music = data?.totals.spotify;
  const viewing = data?.totals.netflix;
  const youtube = data?.totals.youtube;
  const totalGamesMinutes = games.reduce((sum, game) => sum + game.minutes, 0);

  return <div className={'v-media media-world' + (paused ? ' is-motion-paused' : '')}>
    <header className="media-page-header"><span className="eyebrow">Your media journal</span><button className="media-motion-toggle" aria-pressed={paused} onClick={() => setPaused(!paused)}><Icon name={paused ? 'play' : 'pause'} size={13} />{paused ? 'Resume motion' : 'Pause motion'}</button></header>
    <section className="media-hero" aria-labelledby="media-title">
      <div className="media-hero-glow" aria-hidden="true" />
      <MediaLogoBubbles />
      <span className="media-kicker">Soundtracks. Stories. Other worlds.</span>
      <RevealHeading as="h1" id="media-title" paused={paused} lines={['A little more', <em key="you">of your world.</em>]} />
      <p>The songs on repeat. The next episode.<br />The games you come back to. A place for it all.</p>
      <span className="media-optional-note">Start with one source, or just explore. Every connection is optional.</span>
      <nav className="media-jump-links" aria-label="Media sections">{(['spotify', 'netflix', 'youtube', 'steam'] as const).map((provider, index) => <a href={'#media-' + provider} key={provider}><span>0{index + 1}</span><Icon name={icons[provider]} size={17} />{names[provider]}<Icon name="arrow-down" size={14} /></a>)}</nav>
      <a className="media-scroll-hint" href="#media-spotify">Explore your collection <Icon name="arrow-down" size={15} /></a>
    </section>
    {media.loading && <div className="media-load-state" role="status">Loading your collection…</div>}
    {media.error && <div className="media-load-state" role="alert"><p>Couldn’t load your media: {media.error.message}</p><button className="btn" onClick={media.reload}>Try again</button></div>}
    <RevealSection id="media-spotify" className="media-section media-spotify" paused={paused} aria-labelledby="spotify-title">
      <div className="media-section-heading"><span className="media-section-number">01 / Listening</span><RevealHeading id="spotify-title" paused={paused}><span className="media-heading-content"><span className="media-heading-logo" data-provider="spotify" aria-hidden="true" /><span>Your life, on repeat.</span></span></RevealHeading><p>Music for every version of your day.</p></div>
      <div className="media-source-bar"><span><Icon name="music" size={20} /> Spotify</span><span className="media-source-status">{music?.items ? 'Imported listening history' : 'Ready for your first import'}</span></div>
      <div className="media-facts"><div><strong>{media.loading ? '—' : (music?.items || 0).toLocaleString()}</strong><span>listening records</span></div><div><strong>{media.loading ? '—' : hours(music?.minutes || 0)}</strong><span>recorded listening</span></div><div className="media-fact-note"><Icon name="music" size={24} /><p>A familiar song.<br />A different kind of day.</p></div></div>
      <ImportMedia provider="spotify" onImported={media.setData} />
      {!!music?.items && <History provider="spotify" seed={data?.recent_by_provider.spotify || emptyHistory} total={music.items} />}
      {!media.loading && !media.error && !music?.items && <CollectionPlaceholder provider="spotify" title="Your soundtrack starts here." features={['Tracks & podcasts', 'Listening history', 'Library exports']}>Open Import Spotify JSON above when you have an export ready. You don’t need an API key, and you can add Last.fm later.</CollectionPlaceholder>}
      <SpotifyDocuments documents={data?.documents || []} />
      <LastfmPanel data={data} disabled={media.loading || !!media.error} onSynced={media.setData} />
    </RevealSection>
    <RevealSection id="media-netflix" className="media-section media-netflix" paused={paused} aria-labelledby="netflix-title">
      <div className="media-section-heading"><span className="media-section-number">02 / Watching</span><RevealHeading id="netflix-title" paused={paused}><span className="media-heading-content"><span className="media-heading-logo" data-provider="netflix" aria-hidden="true" /><span>Just one more episode.</span></span></RevealHeading><p>The stories that have kept you company.</p></div>
      <div className="media-source-bar"><span><Icon name="screen" size={20} /> Netflix</span><span className="media-source-status">{viewing?.items ? 'Imported viewing activity' : 'CSV import available'}</span></div>
      <div className="media-facts"><div><strong>{media.loading ? '—' : (viewing?.items || 0).toLocaleString()}</strong><span>viewing entries</span></div><div><strong className="media-word-value">By date</strong><span>your viewing journal</span></div><div className="media-fact-note"><Icon name="screen" size={24} /><p>A night in.<br />Somewhere else entirely.</p></div></div>
      <div className="media-poster-tools"><div><strong>Posters are a little extra</strong><p>{posters.loading ? 'Checking poster setup…' : posters.data?.configured ? 'Available posters are added when you import. You can fetch missing ones here, too.' : 'Titles, dates and imports work without posters. If artwork is unavailable, a simple icon takes its place.'}</p></div>{posters.data?.configured && <ActionButton className="btn" disabled={posterBusy || netflixImportBusy || media.loading || !viewing?.items} aria-busy={posterBusy} onClick={fetchPosters}>{posterBusy ? 'Fetching posters…' : 'Fetch missing posters'}</ActionButton>}</div>
      {posterBusy && <p className="media-data-note" role="status">Looking up posters · {posterCount} titles checked. Your viewing history is already saved.</p>}
      {posterNote && <p className="media-data-note" role="status">{posterNote}</p>}
      {posterError && <p className="media-error" role="alert">{posterError}</p>}
      {posters.error && <p className="media-error" role="alert">{posters.error.message} <button className="media-inline-button" onClick={posters.reload}>Retry</button></p>}
      <ImportMedia provider="netflix" onImported={acceptMedia} disabled={posterBusy} onBusyChange={setNetflixImportBusy} afterImport={fetchPosters} />
      {!!viewing?.items && <History provider="netflix" seed={data?.recent_by_provider.netflix || emptyHistory} total={viewing.items} />}
      {!media.loading && !media.error && !viewing?.items && <CollectionPlaceholder provider="netflix" title="A place for your next story." features={['Films & episodes', 'Viewing dates', 'Multiple profiles']}>Open Import Netflix CSV above for a short download guide. Your viewing journal works without a Netflix API key or poster setup.</CollectionPlaceholder>}
      <p className="media-data-note">Netflix’s standard CSV includes titles and dates, but no duration or time of day. Viewing dates are kept as exported; watch time is only shown when supplied.</p>
      <div className="media-tmdb-credit"><a href="https://www.themoviedb.org" target="_blank" rel="noreferrer"><img src="/brands/tmdb.svg" alt="TMDB" width="40" height="40" /></a><p>Posters and catalogue metadata from TMDB.<br />This product uses the TMDB API but is not endorsed or certified by TMDB.</p></div>
    </RevealSection>
    <RevealSection id="media-youtube" className="media-section media-youtube" paused={paused} aria-labelledby="youtube-title">
      <div className="media-section-heading"><span className="media-section-number">03 / Discovering</span><RevealHeading id="youtube-title" paused={paused}><span className="media-heading-content"><span className="media-heading-logo" data-provider="youtube" aria-hidden="true" /><span>One video leads to another.</span></span></RevealHeading><p>The ideas, creators and curiosities you return to.</p></div>
      <div className="media-source-bar"><span><Icon name="play" size={20} /> YouTube</span><span className="media-source-status">{youtube?.items ? 'Imported watch history' : 'Takeout JSON import available'}</span></div>
      <div className="media-facts"><div><strong>{media.loading ? '—' : (youtube?.items || 0).toLocaleString()}</strong><span>viewing entries</span></div><div><strong className="media-word-value">By time</strong><span>timestamps in your local timezone</span></div><div className="media-fact-note"><Icon name="play" size={24} /><p>A new perspective.<br />A familiar creator.</p></div></div>
      <ImportMedia provider="youtube" onImported={media.setData} />
      {!!youtube?.items && <History provider="youtube" seed={data?.recent_by_provider.youtube || emptyHistory} total={youtube.items} />}
      {!media.loading && !media.error && !youtube?.items && <CollectionPlaceholder provider="youtube" title="Follow your curiosity." features={['Videos & creators', 'Viewing timestamps', 'Video links']}>Your YouTube history has a home here. Open Import YouTube JSON above when your Takeout export arrives. No API setup is required.</CollectionPlaceholder>}
      <p className="media-data-note">Takeout records viewing activity, not how long you watched. Timestamps are shown in your browser’s local timezone; no watch-time total is inferred. Thumbnails are loaded from YouTube when available, with a play icon as a fallback. Paused or deleted history may be absent from your export.</p>
    </RevealSection>
    <RevealSection id="media-steam" className="media-section media-steam" paused={paused} aria-labelledby="steam-title">
      <div className="media-section-heading"><span className="media-section-number">04 / Playing</span><RevealHeading id="steam-title" paused={paused}><span className="media-heading-content"><span className="media-heading-logo" data-provider="steam" aria-hidden="true" /><span>A world worth returning to.</span></span></RevealHeading><p>Your library. Your adventures. Your own pace.</p></div>
      <div className="media-source-bar"><span><Icon name="gamepad" size={20} /> Steam</span><span className="media-source-status" role="status">{steam?.payload.snapshot_at ? (steam.payload.origin === 'steam_api' ? 'Last synced ' : 'Snapshot imported ') + new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(steam.payload.snapshot_at)) : 'No snapshot yet'}</span></div>
      <div className="media-facts"><div><strong>{media.loading ? '—' : games.length.toLocaleString()}</strong><span>games in this snapshot</span></div><div><strong>{media.loading ? '—' : hours(totalGamesMinutes)}</strong><span>lifetime playtime in snapshot</span></div><div className="media-fact-note"><Icon name="gamepad" size={24} /><p>Another adventure.<br />Right where you left off.</p></div></div>
      <SteamSync busy={steamBusy} setBusy={setSteamBusy} disabled={media.loading || !!media.error} onSynced={media.setData} />
      <ImportMedia provider="steam" onImported={media.setData} disabled={steamBusy} onBusyChange={setSteamBusy} />
      {games.length > 0 ? <div className="media-game-library"><div className="media-library-tools"><label>Find a game<input className="input" type="search" placeholder="Search your library…" value={gameSearch} onChange={(event) => setGameSearch(event.target.value)} /></label><label>Sort by<select className="input" value={gameSort} onChange={(event) => setGameSort(event.target.value)}><option value="minutes">Most played</option><option value="last_played">Last played</option><option value="name">Name</option></select></label></div><div className="media-game-scroll" role="region" aria-label="Steam library" tabIndex={0}><div className="media-game-grid">{filteredGames.map((game, index) => <article className="media-game" key={game.appid}><SteamCover key={game.appid + (game.artwork_url || '')} game={game} rank={index + 1} /><h3><a href={`https://store.steampowered.com/app/${game.appid}/`} target="_blank" rel="noreferrer">{game.name}</a></h3><strong>{hours(game.minutes)} <span>all time</span></strong><p>{hours(game.recent_minutes)} in the two weeks before this snapshot</p><p>{game.last_played ? 'Last played ' + mediaDate(game.last_played) : 'Last played unavailable'}</p></article>)}</div>{!filteredGames.length && <p className="media-empty">No games match “{gameSearch}”.</p>}</div></div> : !media.loading && !media.error && <CollectionPlaceholder provider="steam" title="Your next adventure can wait." features={['Game library', 'Playtime', 'Search & sorting']}>Steam library sync and JSON imports are supported. Follow the setup guide above whenever you feel ready. Games and playtime stay readable even without cover images.</CollectionPlaceholder>}
      <p className="media-data-note">Sync now refreshes your saved library from Steam. Snapshots contain cumulative playtime, with recent totals and last-played dates when provided. They do not contain individual play sessions. Refreshes run only when you click; scheduled sync is not enabled.</p>
    </RevealSection>
    <footer className="media-footer"><Icon name="lock" size={16} /><p>Your collection, at a glance.<span>Your media records. No AI analysis or health correlations.</span></p></footer>
  </div>;
}
