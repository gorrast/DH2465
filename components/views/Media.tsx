'use client';
import { useRef, useState } from 'react';
import { api } from '@/lib/api';
import { Icon } from '../ui/Icon';
import { ScoreText } from '../ui/ScoreChange';
import { toast } from '../ui/overlays';
import { ViewHead, useLoad } from './common';

type MediaEvent = { id: string; provider: string; occurred_at: string; title: string; creator?: string | null; minutes: number; source?: { media_kind?: string } };
type MediaDocument = { id: string; filename: string; kind: string; payload: { taste?: Record<string, string>; albums?: { artist: string; album: string }[]; shows?: { name: string; publisher: string }[]; saved_track_count?: number; followed_artist_count?: number; listening_age?: { listeningAge?: number }; party?: { percentListenedNight?: number }; top_artists?: { numUniqueArtists?: number }; top_tracks?: { numUniqueTracks?: number }; top_genres?: { totalNumGenres?: number } } };
type MediaPayload = { events: MediaEvent[]; total: number; totals: Record<string, { items: number; minutes: number }>; documents?: MediaDocument[] };
type MediaInsight = { title: string; detail: string; sample: number; confidence: string; kind: string };
type MediaChartPoint = { date: string; media_minutes: number; music_minutes: number; podcast_minutes: number; sleep_score: number; meetings: number; workouts: number };
type MediaInsights = { available: boolean; overlap_days: number; media_days: number; health_calendar_days: number; insights: MediaInsight[]; headline?: { title: string; detail: string; sample: number }; chart: MediaChartPoint[]; note: string };

function mediaDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));
}

function formattedTaste(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith('**') && part.endsWith('**')
    ? <strong key={index}>{part.slice(2, -2)}</strong>
    : <span key={index}>{part}</span>);
}

function MediaTimeline({ points }: { points: MediaChartPoint[] }) {
  if (!points.length) return null;
  const width = 720, height = 190, left = 34, right = 12, top = 14, bottom = 30;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const maxMinutes = Math.max(60, ...points.map((point) => point.media_minutes));
  const x = (index: number) => left + (points.length === 1 ? plotWidth / 2 : index * plotWidth / (points.length - 1));
  const yScore = (score: number) => top + plotHeight - (score / 100) * plotHeight;
  const yMinutes = (minutes: number) => top + plotHeight - (minutes / maxMinutes) * plotHeight;
  const line = points.map((point, index) => (index ? 'L' : 'M') + x(index) + ' ' + yScore(point.sleep_score)).join(' ');
  return <div className="v-media-chart-wrap"><svg className="v-media-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Media minutes and sleep score by day">
    <line x1={left} x2={width - right} y1={yScore(50)} y2={yScore(50)} stroke="var(--grid)" />
    <text x={left - 6} y={yScore(100) + 4} textAnchor="end" className="c-axis">100</text><text x={left - 6} y={yScore(0) + 4} textAnchor="end" className="c-axis">0</text>
    {points.map((point, index) => <g key={point.date}><rect x={x(index) - Math.max(2, plotWidth / points.length * 0.28)} y={yMinutes(point.media_minutes)} width={Math.max(4, plotWidth / points.length * 0.56)} height={Math.max(2, top + plotHeight - yMinutes(point.media_minutes))} rx="3" fill="var(--accent-soft)" /><circle cx={x(index)} cy={yScore(point.sleep_score)} r="3.5" fill="var(--series-2)" /><title>{point.date}: {Math.round(point.media_minutes)} media minutes, sleep {Math.round(point.sleep_score)}, {point.meetings} meetings, {point.workouts} workouts</title>{index % Math.max(1, Math.ceil(points.length / 8)) === 0 ? <text x={x(index)} y={height - 8} textAnchor="middle" className="c-axis">{point.date.slice(5)}</text> : null}</g>)}
    <path d={line} fill="none" stroke="var(--series-2)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg><div className="row tiny muted"><span><i className="v-media-legend media" />media minutes</span><span><i className="v-media-legend sleep" />sleep score</span><span>hover a day for calendar context</span></div></div>;
}

export function MediaView() {
  const [provider, setProvider] = useState('spotify');
  const [files, setFiles] = useState<File[]>([]);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const media = useLoad(() => api.get<MediaPayload>('/api/media'), []);
  const insights = useLoad(() => api.get<MediaInsights>('/api/media/insights'), []);

  const importMedia = async () => {
    if (!files.length || importing) return;
    setImporting(true);
    try {
      const result = await api.upload<MediaPayload & { imported: number }>('/api/media/import?provider=' + provider, files);
      media.setData(result);
      insights.reload();
      setFiles([]);
      if (fileRef.current) fileRef.current.value = '';
      toast('Imported ' + result.imported + ' ' + provider + ' records.', { kind: 'success' });
    } catch (e: any) {
      toast(e.message, { kind: 'error' });
    } finally {
      setImporting(false);
    }
  };

  return (
    <>
      <ViewHead eyebrow="Media lab" title="Your listening world" />
      <div className="v-media stack">
        <div className="grid grid-2">
          <div className="card">
            <div className="card-title"><h3>Import media</h3><span className="badge badge-good">prototype</span></div>
            <p className="small secondary">Import a personal export to build your media timeline. Files are parsed on the server, then discarded; only normalized records are stored.</p>
            <div className="row" style={{ marginTop: '12px' }}>
              <label className="small">Source
                <select className="input" disabled={importing} value={provider} onChange={(e) => { setProvider(e.target.value); setFiles([]); if (fileRef.current) fileRef.current.value = ''; }}>
                  <option value="spotify">Spotify JSON</option>
                  <option value="netflix">Netflix CSV</option>
                </select>
              </label>
              <label className="small">Export files
                <input ref={fileRef} disabled={importing} className="input" type="file" multiple={provider === 'spotify'} accept={provider === 'spotify' ? '.json,application/json' : '.csv,text/csv'} onChange={(e) => setFiles(Array.from(e.target.files || []))} />
              </label>
            </div>
            <button className="btn btn-primary" type="button" disabled={!files.length || importing} onClick={importMedia}><Icon name="upload" size={16} />{importing ? 'Importing…' : 'Import media'}</button>
            <p className="tiny muted" style={{ marginTop: '10px' }}>Select both music files and any podcast file together. Spotify account files are ignored.</p>
          </div>
          <div className="card">
            <div className="card-title"><h3>Collection snapshot</h3><span className="tiny muted">{media.data ? media.data.total + ' records' : 'loading'}</span></div>
            {media.data ? <div className="grid grid-2 v-data-media-totals">
              {['spotify', 'netflix'].map((name) => <div key={name} className="soft"><strong>{media.data?.totals[name]?.items || 0}</strong><span className="small secondary">{name} items</span><span className="tiny muted">{Math.round(media.data?.totals[name]?.minutes || 0).toLocaleString()} minutes</span></div>)}
            </div> : <div className="skeleton" style={{ height: '64px' }} />}
            <p className="small secondary" style={{ marginTop: '12px' }}>This view is deliberately media-only. Health and sleep correlations can be added later without changing these records.</p>
          </div>
        </div>
        <div className="card">
          <div className="card-title"><h3>Recent media</h3><span className="tiny muted">latest {Math.min(media.data?.events.length || 0, 100)} records</span></div>
          {media.data?.events.length ? <div className="v-media-recent-scroll"><table className="data"><thead><tr><th>When</th><th>Title</th><th>Source</th><th>Minutes</th></tr></thead><tbody>{media.data.events.map((event) => <tr key={event.id}><td>{mediaDate(event.occurred_at)}</td><td><span className="v-media-title"><span className="v-media-art"><Icon name={event.source?.media_kind === 'podcast' ? 'podcast' : 'music'} size={17} /></span><span><strong>{event.title}</strong>{event.creator ? <span className="tiny muted">{event.creator}</span> : null}</span></span></td><td><span className="badge badge-accent">{event.source?.media_kind || event.provider}</span></td><td>{Math.round(event.minutes)}</td></tr>)}</tbody></table></div> : <p className="small secondary">No media imported yet. Choose an export above to see your collection take shape.</p>}
        </div>
        <div className="card v-media-insights">
          <div className="card-title"><h3>Crossed signals</h3><span className="badge badge-accent">exploratory</span></div>
          <p className="small secondary">Imported listening is compared with the health and calendar dataset currently selected. In demo mode, those health and calendar records are simulated; these exploratory patterns do not establish cause and effect.</p>
          {insights.data?.headline ? <div className="v-media-headline"><div className="eyebrow">{insights.data.headline.title}</div><p><ScoreText text={insights.data.headline.detail} /></p><span className="tiny muted">Built from {insights.data.headline.sample} overlapping nights</span></div> : null}
          {insights.data?.chart.length ? <MediaTimeline points={insights.data.chart} /> : null}
          {insights.loading ? <div className="skeleton" style={{ height: '100px' }} /> : insights.data?.insights.length ? <div className="grid grid-2">{insights.data.insights.map((insight, index) => <div className="soft v-media-insight" key={insight.kind + '-' + insight.title + '-' + index}><div className="row between"><strong>{insight.title}</strong><span className={'badge badge-' + insight.confidence}>{insight.confidence}</span></div><p className="small secondary"><ScoreText text={insight.detail} /></p><span className="tiny muted">{insight.sample} overlapping nights · {insight.kind}</span></div>)}</div> : <p className="small secondary">{insights.data?.note || 'Import media that overlaps your available health and calendar history to reveal patterns.'}</p>}
          {insights.data?.note ? <p className="tiny muted v-media-insights-note">{insights.data.note}</p> : null}
        </div>
        {media.data?.documents?.map((document) => {
          const p = document.payload;
          if (document.kind === 'taste_profile') return <div className="card" key={document.id}><div className="card-title"><h3>Taste profile</h3><span className="tiny muted">{document.filename}</span></div><div className="stack">{Object.entries(p.taste || {}).map(([label, text]) => <div key={label}><strong>{label.replace(/[A-Z]/g, (letter) => ' ' + letter).replace(/^./, (letter) => letter.toUpperCase())}</strong><p className="small secondary v-data-document-text">{formattedTaste(text)}</p></div>)}</div></div>;
          if (document.kind === 'library') return <div className="card" key={document.id}><div className="card-title"><h3>Your library</h3><span className="tiny muted">{document.filename}</span></div><div className="row"><span className="chip">{p.saved_track_count || 0} saved tracks</span><span className="chip">{p.albums?.length || 0} albums</span><span className="chip">{p.shows?.length || 0} shows</span><span className="chip">{p.followed_artist_count || 0} followed artists</span></div><div className="grid grid-2 v-data-library-list"><div><strong>Saved albums</strong>{(p.albums || []).slice(0, 8).map((album) => <div className="small secondary" key={album.album + album.artist}>{album.album} · {album.artist}</div>)}</div><div><strong>Saved shows</strong>{(p.shows || []).slice(0, 8).map((show) => <div className="small secondary" key={show.name}>{show.name} · {show.publisher}</div>)}</div></div></div>;
          if (document.kind === 'wrapped') return <div className="card" key={document.id}><div className="card-title"><h3>Wrapped 2025</h3><span className="tiny muted">{document.filename}</span></div><div className="row"><span className="chip">{p.top_artists?.numUniqueArtists || 0} unique artists</span><span className="chip">{p.top_tracks?.numUniqueTracks || 0} unique tracks</span><span className="chip">{p.top_genres?.totalNumGenres || 0} genres</span><span className="chip">{p.listening_age?.listeningAge || '–'} listening age</span><span className="chip">{Math.round(p.party?.percentListenedNight || 0)}% listened at night</span></div></div>;
          return null;
        })}
      </div>
    </>
  );
}
