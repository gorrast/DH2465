'use client';
/* Morning report view (SPEC §9.4). */
import Link from 'next/link';
import { useState, type ReactNode } from 'react';
import { api } from '@/lib/api';
import { bandFor, dates, fmt } from '@/lib/format';
import { Icon } from '../ui/Icon';
import { toast } from '../ui/overlays';
import { Ring, Sparkline, Stages } from '../charts/basic';
import { DayTimeline } from '../charts/DayTimeline';
import { useApp } from '../shell/AppContext';
import { Chip, DateNav, Skeleton, ViewHead, useLoad } from './common';

let revealed = false; // once "Why?" is clicked, the veil stays off for the session

const EVIDENCE_ICON: Record<string, string> = { hr: 'pulse', hrv: 'heart', rhr: 'heart', bedtime: 'bed', duration: 'moon', interruptions: 'bed', temp: 'thermometer', location: 'map', calendar: 'calendar', resp: 'lungs', spo2: 'drop' };

function Badge({ conf }: { conf: string }) {
  return <span className={'badge badge-' + conf}>{conf}</span>;
}

function Pts({ v, lo, hi }: { v: number; lo?: number | null; hi?: number | null }) {
  return (
    <span className={'chip pts ' + (v < 0 ? 'pts-neg' : 'pts-pos')} title={lo !== null && lo !== undefined ? 'likely ' + fmt.signed(lo, 0) + ' to ' + fmt.signed(hi, 0) + ' points' : ''}>
      {fmt.signed(v, 1) + ' pts'}
    </span>
  );
}

function CauseItem({ c, expandedDefault }: { c: any; expandedDefault: boolean }) {
  const [expanded, setExpanded] = useState(expandedDefault);
  return (
    <li className="list-item v-morning-cause" data-factor={c.factor}>
      <span className="num">{String(c.rank)}</span>
      <div className="body">
        <div className="row between"><span className="title">{c.title}</span><span className="row"><Pts v={c.points} lo={c.points_low} hi={c.points_high} /><Badge conf={c.confidence} /></span></div>
        <div className="detail">{c.detail}</div>
        <div className="row tiny muted">
          {c.n_similar ? <span>{c.n_similar + ' similar nights in your history'}</span> : null}
          {c.evidence && c.evidence.length ? (
            <button className="btn btn-ghost btn-sm v-morning-toggle" type="button" onClick={() => setExpanded(!expanded)}>{expanded ? 'Hide evidence' : 'Show evidence'}</button>
          ) : null}
        </div>
        <div className="v-morning-evidence">
          {expanded ? c.evidence.map((ev: any, i: number) => (
            <EvidenceRow key={i} ev={ev} />
          )) : null}
        </div>
      </div>
    </li>
  );
}

function EvidenceRow({ ev }: { ev: any }) {
  return (
    <>
      <div className="v-morning-evidence-row"><Icon name={EVIDENCE_ICON[ev.kind] || 'info'} size={14} /><span>{ev.text}</span></div>
      {ev.series && ev.series.length ? (
        <>
          <Sparkline className="v-morning-spark" values={ev.series} norm={ev.series_baseline || null} start={ev.series_start} stepMin={ev.series_step_min || 5} height={64} unit={ev.unit || ''} label={ev.kind === 'hr' ? 'heart rate' : ev.kind} digits={0} />
          {ev.series_baseline ? <div className="tiny muted">Solid: last night · dotted: your usual at that hour · shaded: above your norm</div> : null}
        </>
      ) : null}
    </>
  );
}

function SuggestionCard({ s, morning, style, className }: { s: any; morning: string; style?: React.CSSProperties; className?: string }) {
  const [accepted, setAccepted] = useState(!!s.accepted);
  const [pending, setPending] = useState(false);
  const range = s.gain_low !== null && s.gain_low !== undefined ? ' · likely ' + fmt.signed(s.gain_low, 0) + ' to ' + fmt.signed(s.gain_high, 0) + ' points' : '';
  let actions: ReactNode;
  if (accepted) {
    actions = (
      <>
        <span className="row v-morning-added"><Icon name="check" size={16} />Added to your calendar</span>
        <button className="btn btn-sm" type="button" onClick={() => api.download('/api/suggestions/' + morning + '/' + s.id + '.ics', 'stressless-' + s.id + '.ics').catch((e) => toast('Could not download: ' + e.message, { kind: 'error' }))}>
          <Icon name="download" size={14} />Download .ics
        </button>
        <Link className="btn btn-sm btn-ghost" href={'/planner/' + morning}>See it in the Planner</Link>
      </>
    );
  } else if (s.proposed_event) {
    actions = (
      <button className="btn btn-primary" type="button" disabled={pending} onClick={async () => {
        setPending(true);
        try {
          await api.post('/api/suggestions/' + morning + '/' + s.id + '/accept');
          setAccepted(true);
          toast('Added "' + s.proposed_event.title + '" to tonight', { kind: 'success' });
        } catch (e: any) {
          setPending(false);
          toast('Could not add: ' + e.message, { kind: 'error' });
        }
      }}>
        <Icon name="calendar" size={16} />Add to calendar
      </button>
    );
  } else {
    actions = <Link className="btn" href={'/planner/' + (s.for_date || morning)}><Icon name="planner" size={16} />Try it in the Planner</Link>;
  }
  return (
    <div className={'card accent v-morning-sugg' + (className ? ' ' + className : '')} data-tour="suggestion" style={style}>
      <div className="eyebrow">{'Suggestion' + range}</div>
      <h3>{s.title}</h3>
      <p className="small">{s.body}</p>
      <div className="row v-morning-sugg-actions">{actions}</div>
    </div>
  );
}

const TILE_ICON: Record<string, string> = { hrv_ms: 'heart', resting_hr: 'pulse', wrist_temp_dev: 'thermometer', resp_rate: 'lungs', spo2: 'drop' };
function StatTile({ m }: { m: any }) {
  const fmtValue = (v: number | null) => (v === null || v === undefined ? '–' : m.key === 'wrist_temp_dev' ? fmt.signed(v, 1) : m.key === 'spo2' ? fmt.num(v, 1) : m.key === 'hrv_ms' ? fmt.num(v, 0) : m.key === 'resp_rate' ? fmt.num(v, 1) : fmt.num(v, 0));
  const delta = m.delta === null || m.delta === undefined ? null
    : m.key === 'hrv_ms' && m.delta_pct !== null && m.delta_pct !== undefined ? fmt.pct(m.delta_pct, 0)
    : fmt.signed(m.delta, m.key === 'wrist_temp_dev' || m.key === 'resp_rate' || m.key === 'spo2' ? 1 : 0) + ' ' + m.unit;
  const hasSeries = m.series && m.series.some((v: number | null) => v !== null);
  return (
    <div className="stat-tile v-morning-tile">
      <div className="label"><Icon name={TILE_ICON[m.key] || 'info'} size={14} />{m.label}</div>
      <div className="value">{fmtValue(m.value)}<small>{m.unit}</small></div>
      <div className="delta">{delta === null ? <span className="muted">no baseline yet</span> : <span>{delta + ' vs baseline'}</span>}<span className={'badge badge-' + m.status}>{m.status}</span></div>
      {hasSeries ? (
        <Sparkline className="trend" values={m.series} baseline={m.baseline} height={32} label={m.label} unit={m.unit} digits={m.key === 'wrist_temp_dev' ? 2 : 1}
          xLabels={m.series.map((_: unknown, i: number) => (13 - i === 0 ? 'last night' : 13 - i + ' nights ago'))} />
      ) : <div className="trend" />}
    </div>
  );
}

function HistorySelect() {
  const { historyDays: cur, setHistoryDays } = useApp();
  return (
    <label className="row small muted">History used
      <select className="select" aria-label="Nights of history used" value={cur === null ? 'all' : String(cur)} onChange={(e) => setHistoryDays(e.target.value === 'all' ? null : +e.target.value)}>
        {[7, 14, 28].map((n) => <option key={n} value={String(n)}>{n + ' nights'}</option>)}
        <option value="all">All nights</option>
      </select>
    </label>
  );
}

export function MorningView({ date, reveal }: { date?: string; reveal?: boolean }) {
  const { today, meta, historyDays: hd, go } = useApp();
  const morning = date || today;
  const [veiled, setVeiled] = useState(!!reveal && !revealed);
  const [moreOpen, setMoreOpen] = useState(false);
  const load = useLoad(async () => {
    const report = await api.get('/api/report/' + morning + (hd ? '?history_days=' + hd : ''));
    let day = null;
    try { day = await api.get('/api/day/' + report.night_date); } catch { day = null; }
    return { report, day };
  }, [morning, hd]);

  const head = (
    <ViewHead eyebrow="Morning report" title={fmt.dayLong(morning)}>
      <DateNav label={morning === today ? 'This morning' : fmt.day(morning)}
        prevHref={'/morning/' + dates.addDays(morning, -1)} nextHref={'/morning/' + dates.addDays(morning, 1)}
        prevDisabled={!!meta.start && morning <= dates.addDays(meta.start, 1)} nextDisabled={morning >= today}
        extra={morning !== today ? <button className="btn btn-sm btn-ghost" type="button" onClick={() => go('/morning/' + today)}>Today</button> : null} />
    </ViewHead>
  );

  if (load.loading) return <>{head}<div className="v-morning"><Skeleton height={220} /></div></>;
  if (load.error || !load.data) {
    const msg = load.error ? load.error.message : '';
    return (
      <>{head}
        <div className="v-morning">
          <div className="card empty">
            <Icon name="moon" size={28} />
            <h2>{/No report yet/.test(msg) ? 'No report yet' : 'No report'}</h2>
            <p>{msg}</p>
            <button className="btn" onClick={() => go('/morning/' + today)}>Go to this morning</button>
          </div>
        </div>
      </>
    );
  }

  const { report, day } = load.data;
  const src = report.sources || {};
  const night = report.night;
  const asleep = night && night.worn ? fmt.minutes(night.duration_min) : '–';

  const causeBlocks: ReactNode[] = [];
  const stagger = () => ({ className: ' v-morning-stagger', style: { animationDelay: causeBlocks.length * 0.18 + 's' } });
  let st = stagger();
  if (report.missing_data) {
    causeBlocks.push(<div key="missing" className={"card" + st.className} style={st.style}><h3>No watch data</h3><p className="secondary">{report.missing_data}</p><p className="small muted">Yesterday still counts for your patterns; the day strip below shows what it looked like.</p></div>);
  } else if (report.model && report.model.insufficient) {
    causeBlocks.push(<div key="baseline" className={"card" + st.className} style={st.style}><h3>Building your baseline</h3><p className="secondary">{report.confidence_note}</p></div>);
  } else if (!report.causes.length) {
    causeBlocks.push(<div key="calm" className={"card" + st.className} style={st.style}><h3>Nothing in your calendar stands out</h3><p className="secondary">{'A calm day. ' + (report.unexplained_note || '')}</p></div>);
  } else {
    causeBlocks.push(
      <div key="causes" className={"card v-morning-causes-card" + st.className} style={st.style}>
        <div className="card-title"><h3>{report.causes.length === 1 ? 'The likely cause' : report.causes.length === 2 ? 'Two likely causes' : 'Three likely causes'}</h3><span className="tiny muted">calendar · Maps · watch</span></div>
        <ol className="list v-morning-cause-list">
          {report.causes.map((c: any, i: number) => <CauseItem key={c.factor + i} c={c} expandedDefault={i === 0 || c.evidence.some((e: any) => e.kind === 'hr' && e.series)} />)}
        </ol>
      </div>,
    );
  }
  st = stagger();
  if (report.helpers && report.helpers.length) {
    causeBlocks.push(
      <div key="helpers" className={"card soft" + st.className} style={st.style}>
        <h4>What helped</h4>
        <ul className="list">
          {report.helpers.map((h: any, i: number) => (
            <li key={i} className="row between small"><span><strong>{h.title}</strong>{' — '}{h.detail}</span><Pts v={h.points} lo={h.points_low} hi={h.points_high} /></li>
          ))}
        </ul>
      </div>,
    );
  }

  const primary = (report.recovery || []).filter((m: any) => ['hrv_ms', 'resting_hr', 'wrist_temp_dev'].includes(m.key));
  const more = (report.recovery || []).filter((m: any) => !['hrv_ms', 'resting_hr', 'wrist_temp_dev'].includes(m.key));

  return (
    <>
      {head}
      <div className="v-morning">
        <div className="row v-morning-sources" data-tour="sources">
          <Chip icon="calendar">{'Calendar · ' + (src.calendar_events || 0) + ' events'}</Chip>
          <Chip icon="map">{'Maps · ' + (src.maps_places || 0) + ' places'}</Chip>
          <Chip icon="watch">{'Watch · ' + (src.watch_minutes || 0).toLocaleString('en') + ' min'}</Chip>
          <span className="tiny muted">{'yesterday, ' + fmt.day(report.night_date)}</span>
        </div>

        <div className="v-morning-hero" data-tour="hero">
          <div className="card soft v-morning-watch" data-tour="watch-card">
            <div className="eyebrow">What your watch says</div>
            <div className="v-morning-watch-face">
              <div className="v-morning-watch-score">{fmt.score(report.score)}</div>
              <div className="v-morning-watch-meta"><div className="v-morning-watch-rating">{report.rating || 'No data'}</div><div className="muted small">Sleep score</div></div>
            </div>
            <div className="row v-morning-watch-rows small">
              <span><Icon name="moon" size={14} />{' Asleep ' + asleep}</span>
              {night && night.worn ? <span><Icon name="bed" size={14} />{' ' + fmt.hm(night.in_bed_start) + ' → ' + fmt.hm(night.wake_time)}</span> : null}
            </div>
            <p className="v-morning-watch-quote">{report.score === null ? 'No data for last night.' : 'That’s all your watch tells you.'}</p>
          </div>
          <div className="card v-morning-ring">
            <div className="v-morning-ringbox"><Ring value={report.score} label="sleep score" sublabel={report.rating} band={bandFor(report.score)} size={190} /></div>
            <div className="v-morning-delta">
              {report.delta_vs_baseline === null || report.delta_vs_baseline === undefined
                ? <span className="muted">{report.baseline_score ? 'Usual ' + fmt.score(report.baseline_score) : 'Building your baseline'}</span>
                : <span className={report.delta_vs_baseline < 0 ? 'pts-neg' : 'pts-pos'}>{fmt.signed(report.delta_vs_baseline, 0) + ' vs your usual ' + fmt.score(report.baseline_score)}</span>}
            </div>
          </div>
          <div className={'v-morning-causes' + (veiled ? ' veiled' : '')} data-tour="causes">
            {veiled ? (
              <div className="card v-morning-why">
                <p className="v-morning-why-text">A number. No explanation.</p>
                <button className="btn btn-primary v-morning-why-btn" type="button" data-tour="reveal" onClick={() => { revealed = true; setVeiled(false); }}>Why?</button>
              </div>
            ) : (
              <>
                {causeBlocks}
                {report.suggestions && report.suggestions.length ? (
                  <SuggestionCard s={report.suggestions[0]} morning={morning} className="v-morning-stagger" style={{ animationDelay: causeBlocks.length * 0.18 + 's' }} />
                ) : null}
              </>
            )}
          </div>
        </div>

        <div className="card v-morning-narrative" data-tour="narrative">
          <div className="card-title"><h3>In plain words</h3><span className="chip"><Icon name="brain" size={13} />{report.reasoning_mode === 'claude' ? 'Written by Claude' : 'On-device rules'}</span></div>
          <p>{report.narrative || '—'}</p>
        </div>

        {day && day.hr ? (
          <div className="card">
            <div className="card-title"><h3>Yesterday at a glance</h3><Link className="small" href={'/replay/' + report.night_date}>Open the full replay →</Link></div>
            <DayTimeline className="v-morning-strip" date={day.date} events={day.events} visits={day.visits} hr={day.hr} norm={day.norm} night={day.night} nightPrev={day.night_prev} workouts={day.workouts} checks={day.checks} compact
              onSeek={(m) => go('/replay/' + report.night_date + '?t=' + m)} />
            <div className="tiny muted">Calendar blocks above, heart rate below. Dotted: your usual heart rate at that hour; shaded: above it. Click to jump into the replay.</div>
          </div>
        ) : null}

        {night && night.worn ? (
          <div className="card" data-tour="recovery">
            <div className="card-title"><h3>Last night in numbers</h3><button className="btn btn-ghost btn-sm" type="button" onClick={() => setMoreOpen(!moreOpen)}>{moreOpen ? 'Fewer markers' : 'More markers'}</button></div>
            <div className="grid grid-3">{primary.map((m: any) => <StatTile key={m.key} m={m} />)}</div>
            <div className="grid grid-3 v-morning-more" hidden={!moreOpen}>{more.map((m: any) => <StatTile key={m.key} m={m} />)}</div>
            <div className="divider" />
            <div className="grid grid-2">
              <div>
                <h4>The night</h4>
                <div className="row v-morning-nightfacts">
                  <Chip icon="bed">{'In bed ' + fmt.hm(night.in_bed_start)}</Chip>
                  <Chip icon="moon">{'Asleep ' + fmt.hm(night.sleep_onset)}</Chip>
                  <Chip icon="sun">{'Woke ' + fmt.hm(night.wake_time)}</Chip>
                  <Chip>{fmt.minutes(night.duration_min) + ' asleep'}</Chip>
                  <Chip>{night.interruptions + ' interruption' + (night.interruptions === 1 ? '' : 's') + ', ' + fmt.minutes(night.awake_min) + ' awake'}</Chip>
                </div>
                <Stages className="v-morning-stages" night={night} />
              </div>
              <div>
                <h4>Facts from the night</h4>
                <div className="row">{report.proximal.map((e: any, i: number) => <Chip key={i}>{e.text}</Chip>)}</div>
              </div>
            </div>
            {night.score_parts ? (
              <div className="tiny muted" style={{ marginTop: '8px' }}>
                {'Score parts — duration ' + night.score_parts.duration + '/50 · consistency ' + night.score_parts.consistency + '/30 · interruptions ' + night.score_parts.interruptions + '/20'}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="card soft row between v-morning-footer" data-tour="confidence">
          <span className="small secondary row"><Icon name="info" size={14} />{report.confidence_note}</span>
          <HistorySelect />
        </div>
      </div>
    </>
  );
}
