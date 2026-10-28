'use client';
/* Home: today's AI-written daily report and last week's weekly report (backend: server/reports.py). */
import { useEffect, useState, type ReactNode } from 'react';
import { api, ApiError } from '@/lib/api';
import { fmt } from '@/lib/format';
import { Icon } from '../ui/Icon';
import { toast } from '../ui/overlays';
import { CheckinCard } from './Checkin';
import { ErrorCard, Skeleton, ViewHead, useLoad } from './common';

// ------------------------------------------------------------------ types --
interface SourceStatus {
  key: string; label: string; connected: boolean; data_until: string | null; synced_at: string | null;
  required: boolean; ready: boolean;
}
interface PeriodStatus { period: string; status: 'none' | 'pending' | 'ready' }
export interface Overview {
  today: string; daily: PeriodStatus; weekly: PeriodStatus; sources: SourceStatus[]; ready: boolean;
  consented: boolean; ai: boolean; dev: boolean;   // dev: a test server, where reports can be generated again
}
interface Metric { key: string; label: string; value: number | null; unit: string; baseline: number | null; status: string }
interface Pattern { key: string; title: string; detail: string; sources?: string[] }
interface Finding { title: string; body: string; tone: 'good' | 'neutral' | 'watch'; confidence: string; evidence: string[] }
interface DayHighlight { day: string; reason: string }
interface Content {
  headline: string; summary: string; findings: Finding[]; fun_fact: string | null; suggestion?: string | null;
  caveats: string[]; best_day?: DayHighlight | null; hardest_day?: DayHighlight | null; next_week?: string;
}
export interface Report {
  kind: 'daily' | 'weekly'; period_start: string; period_end: string; generated_at: string; mode: 'claude' | 'rules';
  model: string | null; input: { metrics: Metric[]; patterns: Pattern[] }; content: Content;
}

// ---------------------------------------------------------------- helpers --
const SOURCE_NAMES: Record<string, string> = {
  sleep: 'Sleep', activity: 'Steps', exercise: 'Workouts', calendar: 'Calendar', music: 'Music', streaming: 'Streaming',
  phone: 'Phone', 'check-in': 'Check-in', heart: 'Heart rate',
};
const MODEL_NAMES: Record<string, string> = { 'claude-opus-5-5': 'Claude Opus 5.5', 'claude-sonnet-5-5': 'Claude Sonnet 5.5', 'claude-haiku-5-5': 'Claude Haiku 5.5' };

function value(v: number | null, unit: string): string {
  if (v === null || v === undefined) return '–';
  if (unit === 'min') return fmt.minutes(v);
  if (unit === 'points' || unit === 'count' || unit === 'steps') return Math.round(v).toLocaleString('sv-SE');
  return (Number.isInteger(v) ? String(v) : v.toFixed(1)) + ' ' + unit;
}

function when(iso: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  const today = new Date();
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === today.toDateString()) return 'today ' + time;
  const y = new Date(today); y.setDate(today.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return 'yesterday ' + time;
  return fmt.day(d.toISOString().slice(0, 10)) + ' ' + time;
}

export function sourceLine(s: SourceStatus): string {
  if (!s.connected && !s.data_until) return 'Not connected';
  if (s.data_until) return 'Data available up to ' + when(s.data_until);
  if (s.synced_at) return 'Updated ' + when(s.synced_at);
  return 'Connected, no data yet';
}

// --------------------------------------------------------------- the view --
export function HomeView() {
  const overview = useLoad(() => api.get<Overview>('/api/reports'), []);
  // The weekly report is only generated right after the user generates a daily report, never on page load.
  const [dailyGenerated, setDailyGenerated] = useState(false);
  if (overview.error) return <ErrorCard error={overview.error} onRetry={overview.reload} view="home" />;
  const o = overview.data;
  return (
    <div className="v-home">
      <ViewHead eyebrow={o ? fmt.dayLong(o.today) : 'Today'} title="Your reports" />
      {/* Before the daily report: yesterday's coffee and drinks are part of what explains last night. */}
      <CheckinCard />
      {!o ? <Skeleton height={260} /> : (
        <>
          <DailySection o={o} onGenerated={() => {
            overview.setData({ ...o, consented: true, daily: { ...o.daily, status: 'ready' } });
            setDailyGenerated(true);
          }} />
          <WeeklySection o={o} generate={dailyGenerated} />
        </>
      )}
    </div>
  );
}

function DailySection({ o, onGenerated }: { o: Overview; onGenerated: () => void }) {
  const [report, setReport] = useState<Report | null>(null);
  const [dialog, setDialog] = useState(false);
  const [loading, setLoading] = useState(o.daily.status === 'ready');

  useEffect(() => {
    if (o.daily.status !== 'ready') return;
    api.get<{ report: Report }>('/api/reports/daily/' + o.daily.period)
      .then((r) => setReport(r.report), (e) => toast('Could not load the report: ' + e.message, { kind: 'error' }))
      .finally(() => setLoading(false));
  }, [o.daily.period, o.daily.status]);

  if (loading) return <Skeleton height={260} />;
  if (report) return <ReportCard report={report} onRegenerate={o.dev ? setReport : undefined} />;
  return (
    <div className="card v-home-empty">
      <div className="eyebrow">Daily report</div>
      <h2>How did you sleep?</h2>
      <p className="secondary">
        {o.daily.status === 'pending'
          ? 'Your report for today is being written. Check back in a minute.'
          : 'Get today’s report: what last night looked like and what in your day likely shaped it. You can generate it once a day, so make sure last night’s data has synced first.'}
      </p>
      <button className="btn btn-primary" type="button" disabled={o.daily.status === 'pending'} onClick={() => setDialog(true)}>
        <Icon name="brain" size={16} />Generate today&rsquo;s report
      </button>
      {dialog ? (
        <GenerateDialog o={o} onClose={() => setDialog(false)} onDone={(r) => { setDialog(false); setReport(r); onGenerated(); }} />
      ) : null}
    </div>
  );
}

function WeeklySection({ o, generate }: { o: Overview; generate: boolean }) {
  const [report, setReport] = useState<Report | null>(null);
  const [writing, setWriting] = useState(false);
  const path = '/api/reports/weekly/' + o.weekly.period;

  // A stored weekly report is just shown.
  useEffect(() => {
    if (o.weekly.status !== 'ready') return;
    api.get<{ report: Report }>(path).then((r) => setReport(r.report), (e) => toast('Weekly report: ' + e.message, { kind: 'error' }));
  }, [path, o.weekly.status]);

  // A finished week's report is generated once the user has generated a daily report; "no data" simply shows nothing.
  useEffect(() => {
    if (!generate || o.weekly.status !== 'none') return;
    setWriting(true);
    api.post<{ report: Report }>(path)
      .then((r) => setReport(r.report), (e) => { if (!(e instanceof ApiError && e.status === 400)) toast('Weekly report: ' + e.message, { kind: 'error' }); })
      .finally(() => setWriting(false));
  }, [generate, path, o.weekly.status]);

  if (report) return <ReportCard report={report} onRegenerate={o.dev ? setReport : undefined} />;
  return writing ? <div className="card row small secondary"><span className="spinner" />Writing last week&rsquo;s report…</div> : null;
}

// ----------------------------------------------------------------- dialog --
function GenerateDialog({ o, onClose, onDone }: { o: Overview; onClose: () => void; onDone: (r: Report) => void }) {
  const [agree, setAgree] = useState(o.consented);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !working) onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, working]);

  async function generate() {
    setWorking(true);
    setError(null);
    try {
      if (!o.consented) await api.post('/api/reports/consent');
      const r = await api.post<{ report: Report }>('/api/reports/daily/' + o.daily.period);
      onDone(r.report);
    } catch (e: any) {
      setError(e.message);
      setWorking(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget && !working) onClose(); }}>
      <div className="modal card raised v-home-dialog" role="dialog" aria-modal="true" aria-label="Generate today's report">
        <h3>Ready to generate?</h3>
        <p className="secondary small">The report uses the data below. You get one daily report per day, so wait until last night has synced.</p>
        <ul className="v-home-sources">
          {o.sources.map((s) => (
            <li key={s.key}>
              <Icon name={s.ready ? 'check' : s.required ? 'alert' : 'info'} size={16} className={s.ready ? 'ok' : s.required ? 'bad' : ''} />
              <div>
                <div className="title">{s.label}{s.required ? <span className="muted tiny"> · required</span> : null}</div>
                <div className="tiny muted">{sourceLine(s)}{s.required && !s.ready ? ' · last night has not arrived yet' : ''}</div>
              </div>
            </li>
          ))}
        </ul>
        {!o.consented && o.ai ? (
          <label className="v-home-consent small">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} disabled={working} />
            <span>I agree that a summary of my data (numbers, short labels and the artists and shows you play; no people&rsquo;s names, calendar titles or places) is sent to Anthropic&rsquo;s Claude to write my reports.</span>
          </label>
        ) : null}
        {error ? <p className="v-home-error small">{error}</p> : null}
        {working ? <div className="row small secondary"><span className="spinner" />Writing your report. This can take up to a minute.</div> : null}
        <div className="row modal-actions">
          <button className="btn btn-ghost" type="button" disabled={working} onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" type="button" disabled={working || !o.ready || (o.ai && !agree)} onClick={generate}>Generate</button>
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------- report --
export function ReportCard({ report, onRegenerate, insights, summaryAside }: { report: Report; onRegenerate?: (r: Report) => void; insights?: ReactNode; summaryAside?: ReactNode }) {
  const [regenerating, setRegenerating] = useState(false);
  const c = report.content;
  const weekly = report.kind === 'weekly';

  // Dev servers only: throw the stored report away and write it again.
  function regenerate() {
    setRegenerating(true);
    api.post<{ report: Report }>('/api/reports/' + report.kind + '/' + report.period_start + '?regenerate=true')
      .then((r) => onRegenerate!(r.report), (e) => toast('Could not regenerate: ' + e.message, { kind: 'error' }))
      .finally(() => setRegenerating(false));
  }

  return (
    <article className="card v-home-report">
      <header className={summaryAside ? 'daily-report-intro' : undefined}>
        <div className="daily-report-copy">
          <div className="eyebrow">{weekly ? 'Week of ' + fmt.day(report.period_start) + ' – ' + fmt.day(report.period_end) : 'Daily report · ' + fmt.day(report.period_start)}</div>
          <h2>{c.headline}</h2>
          <p className="v-home-summary">{c.summary}</p>
        </div>
        {summaryAside ? <div className="daily-report-sleep" aria-label="Your sleep summary">{summaryAside}</div> : null}
      </header>

      {insights ?? <ul className="v-home-findings">{c.findings.map((_, index) => <ReportFinding key={index} report={report} index={index} />)}</ul>}

      {weekly && (c.best_day || c.hardest_day) ? (
        <div className="grid grid-2 v-home-days">
          {c.best_day ? <div className="card soft"><div className="eyebrow">Best day · {fmt.day(c.best_day.day)}</div><p className="small">{c.best_day.reason}</p></div> : null}
          {c.hardest_day ? <div className="card soft"><div className="eyebrow">Hardest day · {fmt.day(c.hardest_day.day)}</div><p className="small">{c.hardest_day.reason}</p></div> : null}
        </div>
      ) : null}
      {c.fun_fact ? <p className="v-home-fun small"><Icon name="info" size={14} />{c.fun_fact}</p> : null}
      {c.suggestion || (weekly && c.next_week) ? (
        <div className="card accent v-home-sugg">
          <div className="eyebrow">{weekly ? 'Next week' : 'Suggestion'}</div>
          <p>{weekly ? c.next_week : c.suggestion}</p>
        </div>
      ) : null}
      {c.caveats.length ? <ul className="v-home-caveats tiny muted">{c.caveats.map((x, i) => <li key={i}>{x}</li>)}</ul> : null}
      <div className="tiny muted v-home-foot">
        <span>
          {report.mode === 'claude' ? 'Written by ' + (MODEL_NAMES[report.model || ''] || report.model) : 'Written without AI'}
          {' · ' + when(report.generated_at)} · correlation, not proof
        </span>
        {onRegenerate ? (
          <button className="btn btn-ghost btn-sm" type="button" disabled={regenerating} onClick={regenerate}>
            {regenerating ? <span className="spinner" /> : null}Regenerate (dev)
          </button>
        ) : null}
      </div>
    </article>
  );
}

export function ReportFinding({ report, index }: { report: Report; index: number }) {
  const f = report.content.findings[index];
  const metrics = new Map(report.input.metrics.map(m => [m.key, m]));
  const patterns = new Map(report.input.patterns.map(p => [p.key, p]));
  const link = f.evidence.map(k => patterns.get(k)).find(p => p?.sources?.length);
  return (
          <li className={'tone-' + f.tone}>
            {link ? <div className="eyebrow">{link.sources!.map((s) => SOURCE_NAMES[s] || s).join(' × ')}</div> : null}
            <div className="row between"><span className="title">{f.title}</span><span className={'badge badge-' + f.confidence}>{f.confidence}</span></div>
            <p className="small">{f.body}</p>
            <div className="row">
              {f.evidence.map((k) => {
                const m = metrics.get(k);
                if (m) return <span key={k} className="chip" title={m.baseline !== null ? 'Your usual: ' + value(m.baseline, m.unit) : ''}>{m.label}: {value(m.value, m.unit)}</span>;
                const p = patterns.get(k);
                return p ? <span key={k} className="chip" title={p.detail}>{p.title}</span> : null;
              })}
            </div>
          </li>
  );
}
