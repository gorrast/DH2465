'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { motion, useScroll, useTransform, useReducedMotion } from 'motion/react';
import { api } from '@/lib/api';
import { dates, fmt, minuteLabel, minuteOf, pointClass } from '@/lib/format';
import { Icon } from '../ui/Icon';
import { ActionButton, Collapse, RevealHeading, RevealSection, MetricGroup, quietItem, calmTransition } from '../ui/Motion';
import { ScoreChange, ScoreText } from '../ui/ScoreChange';
import { Sparkline, Stages } from '../charts/basic';
import { DayTimeline, valueAt } from '../charts/DayTimeline';
import { useApp } from '../shell/AppContext';
import { RealityView } from './Reality';
import { DateNav, Skeleton, useLoad } from './common';

const MARKERS = ['hrv_ms', 'resting_hr', 'wrist_temp_dev'];

function SleepScore({ report }: { report: any }) {
  const score = report.score;
  const length = score == null ? 0 : Math.max(0, Math.min(100, score));
  const id = useId();
  return <div className="ah-score" data-tour="watch-card">
    <div className="ah-score-orbit" aria-hidden="true" />
    <div className="ah-score-visual">
    <svg className="ah-score-ring" viewBox="0 0 280 280" role="img" aria-label={`Sleep score ${fmt.score(score)} out of 100. ${report.rating || 'Watch data unavailable'}`}>
      <defs><linearGradient id={id} x1="0" y1="1" x2="1" y2="0"><stop stopColor="var(--sleep)" /><stop offset="1" stopColor="var(--recovery)" /></linearGradient></defs>
      <circle cx="140" cy="140" r="116" fill="none" stroke="var(--card-3)" strokeWidth="6" />
      {score != null ? <circle className="ah-score-arc" cx="140" cy="140" r="116" pathLength="100" fill="none" stroke={`url(#${id})`} strokeWidth="6" strokeLinecap="round" strokeDasharray={`${length} 100`} transform="rotate(-90 140 140)" /> : null}
    </svg>
    <svg className="ah-score-readout" viewBox="0 0 280 280" aria-hidden="true">
      <text x="140" y="151" textAnchor="middle" className="ah-score-value">{fmt.score(score)}</text>
      <text x="140" y="182" textAnchor="middle" className="ah-score-label">Sleep score / 100</text>
    </svg>
    </div>
  </div>;
}

function TonightAction({ suggestion: s, morning, paused }: { suggestion: any; morning: string; paused: boolean }) {
  const [saved, setSaved] = useState(!!s.accepted);
  const [pending, setPending] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');
  const errorId = useId();
  const save = async () => {
    if (pending || saved) return;
    setPending(true); setError('');
    try { await api.post(`/api/suggestions/${morning}/${s.id}/accept`); setSaved(true); }
    catch (e) { setError(e instanceof Error ? e.message : "We couldn't save this block. Try again."); }
    finally { setPending(false); }
  };
  const download = async () => {
    if (downloading) return;
    setDownloading(true); setError('');
    try { await api.download(`/api/suggestions/${morning}/${s.id}.ics`, `stressless-${s.id}.ics`); }
    catch { setError("We couldn't prepare the calendar file. Try again."); }
    finally { setDownloading(false); }
  };
  return <section className={'ah-tonight' + (saved ? ' is-saved' : '')} data-tour="suggestion" aria-label="One change for tonight">
    <div className="ah-tonight-icon"><Icon name={saved ? 'check' : 'moon'} size={22} /></div>
    <div className="ah-tonight-copy"><span className="ah-eyebrow">{saved ? 'A little space, protected' : 'One change for tonight'}</span><RevealHeading as="h3" paused={paused}>{s.title}</RevealHeading>
      <p><ScoreText text={s.body.replace(/\s*Likely[^.]*points\.?$/i, '')} /></p>{!saved && s.gain_low != null && s.gain_high != null ? <span className="ah-estimate">Estimated change <ScoreChange value={s.gain_low} digits={0} /> to <ScoreChange value={s.gain_high} digits={0} /> points</span> : null}
      <div className="ah-actions">
        {saved ? <><span className="ah-saved" role="status">Saved for tonight</span><button className="btn btn-sm" aria-disabled={downloading} aria-busy={downloading} onClick={download}>{downloading ? 'Preparing…' : 'Download .ics'}<Icon name="download" size={14} /></button></>
          : s.proposed_event ? <ActionButton className="btn btn-primary" aria-disabled={pending} aria-busy={pending} aria-describedby={error ? errorId : undefined} onClick={save}>{pending ? 'Saving your evening…' : error ? 'Try saving again' : 'Protect this time'}<Icon name={pending ? 'refresh' : 'chevron-right'} size={16} /></ActionButton>
          : <a className="btn btn-primary" href="#reality-check">Review your activities<Icon name="chevron-right" size={16} /></a>}
      </div>
      {error ? <p className="ah-error" id={errorId} role="alert">{error}</p> : null}
    </div>
  </section>;
}

const evidenceKey = (text: string) => text.trim().replace(/\s+/g, ' ').replace(/[.!?]+$/, '').toLowerCase();

function EvidenceText({ text, evidence }: { text: string; evidence?: any }) {
  if (evidence?.kind !== 'duration') return <ScoreText text={text} />;
  const delta = evidence.value != null && evidence.baseline != null ? Math.round(evidence.value) - Math.round(evidence.baseline) : null;
  return <>Slept <strong className={pointClass(delta)}>{fmt.minutes(evidence.value)}</strong> vs your usual <strong className={pointClass(delta == null ? null : -delta)}>{fmt.minutes(evidence.baseline)}</strong></>;
}

function Finding({ cause: c, date, expanded, onSelect }: { cause: any; date: string; expanded: boolean; onSelect: () => void }) {
  const id = useId();
  const tone = pointClass(c.points);
  const direction = tone === 'pts-pos' ? 'positive' : tone === 'pts-neg' ? 'negative' : 'neutral';
  const seen = new Set([evidenceKey(c.detail || '')]);
  const evidence = (c.evidence || []).map((ev: any) => {
    const key = evidenceKey(ev.text || '');
    const showText = !!key && !seen.has(key);
    seen.add(key);
    return { ...ev, showText };
  });
  const detailEvidence = evidence.find((ev: any) => evidenceKey(ev.text || '') === evidenceKey(c.detail || ''));
  return <li className={'ah-finding' + (expanded ? ' is-open' : '')} data-factor={c.factor}>
    <button className="ah-finding-trigger" aria-expanded={expanded} aria-controls={id} onClick={onSelect}>
      <span className="ah-finding-rank">{String(c.rank).padStart(2, '0')}</span>
      <span className="ah-finding-title">{c.title}<span>{c.n_similar ? `${c.n_similar} similar nights` : 'Your recent history'} · {c.confidence} confidence</span></span>
      <span className="ah-finding-points" data-direction={direction}>{direction !== 'neutral' ? <Icon name={direction === 'positive' ? 'arrow-up' : 'arrow-down'} size={18} /> : null}{fmt.signed(c.points, 1)}<small>pts</small></span><Icon name="chevron-right" size={18} className="ah-disclosure-icon" />
    </button>
    <Collapse id={id} open={expanded}><div className="ah-evidence">
      <p><EvidenceText text={c.detail || ''} evidence={detailEvidence} /></p>
      {c.points_low != null && c.points_high != null ? <p className="ah-evidence-range">Estimated association: <ScoreChange value={c.points_low} /> to <ScoreChange value={c.points_high} /> points.</p> : null}
      {evidence.map((ev: any, i: number) => ev.showText || ev.series?.length ? <div className="ah-evidence-item" key={i}>{ev.showText ? <p><EvidenceText text={ev.text} evidence={ev} /></p> : null}
        {ev.series?.length ? <><Sparkline className="ah-evidence-spark" values={ev.series} norm={ev.series_baseline} height={64} unit={ev.unit} label={ev.kind} start={ev.series_start} stepMin={ev.series_step_min || 5} />
          <details className="ah-data-details"><summary>Read chart values</summary><div className="ah-data-scroll"><table className="data"><thead><tr><th>Time</th><th>Measured {ev.unit}</th><th>Your usual</th></tr></thead><tbody>{ev.series.map((v: number | null, j: number) => <tr key={j}><td>{minuteLabel((minuteOf(ev.series_start, date) ?? 0) + j * (ev.series_step_min || 5))}</td><td>{fmt.num(v, 0)}</td><td>{fmt.num(ev.series_baseline?.[j], 0)}</td></tr>)}</tbody></table></div></details></> : null}
      </div> : null)}
      <a className="ah-text-link" href="#day-story">See the day behind this finding <span aria-hidden="true">↓</span></a>
    </div></Collapse>
  </li>;
}

function MorningReport({ report, day, morning, veiled, onReveal }: { report: any; day: any; morning: string; veiled: boolean; onReveal: () => void }) {
  const { meta, historyDays, setHistoryDays } = useApp();
  const [motionPaused, setMotionPaused] = useState(false);
  const heroRef = useRef<HTMLElement>(null);
  const reducedMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ['start start', 'end -35%'] });
  const glowScale = useTransform(scrollYProgress, [0, 1], [1, 1.28]);
  const glowOpacity = useTransform(scrollYProgress, [0, 1], [1, 0.15]);
  const [selected, setSelected] = useState<number | null>(null);
  const [cursor, setCursor] = useState(18 * 60);
  const [moreOpen, setMoreOpen] = useState(false);
  const night = report.night;
  const causes = report.causes || [];
  const selectCause = (index: number) => {
    setSelected(selected === index ? null : index);
    const evidence = causes[index].evidence?.find((ev: any) => ev.series_start);
    if (evidence) setCursor(Math.max(0, Math.min(1439, (minuteOf(evidence.series_start, report.night_date) ?? 0) + 30)));
  };
  const chosenEvidence = selected == null ? null : causes[selected]?.evidence?.find((ev: any) => ev.series_start);
  const rangeStart = chosenEvidence ? minuteOf(chosenEvidence.series_start, report.night_date) : null;
  const info = day ? valueAt(day, cursor) : null;
  const summary = report.missing_data || (report.model?.insufficient ? report.confidence_note : report.narrative?.split(/(?<=[.!?])\s+/).slice(0, 2).join(' ')) || 'Explore your recent nights to understand the patterns in your day.';
  const recovery = report.recovery || [];
  return <div className="ah-report">
    <section ref={heroRef} className={'ah-hero' + (motionPaused ? ' is-motion-paused' : '')} data-tour="hero" aria-labelledby="morning-title">
      <motion.div className="ah-hero-glow" aria-hidden="true" style={{ scale: reducedMotion || motionPaused ? 1 : glowScale, opacity: reducedMotion || motionPaused ? 1 : glowOpacity }} />
      <p className="ah-night-date">Last night · {fmt.day(report.night_date)}</p>
      <div className="ah-hero-main">
        <RevealHeading as="h1" id="morning-title" paused={motionPaused} lines={['Your night,', <em key="light">in a new light.</em>]} />
        <div className="ah-score-stage"><SleepScore report={report} /></div>
      </div>
      <div className="ah-hero-controls"><a className="ah-text-link" href="#night-explanation">Explore your night <span aria-hidden="true">↓</span></a><button className="ah-text-link ah-motion-toggle" type="button" aria-pressed={motionPaused} onClick={() => setMotionPaused(paused => !paused)}>Pause motion</button></div>
    </section>

    <RevealSection paused={motionPaused} className="ah-section ah-sleep-summary" id="night-explanation" tabIndex={-1}>
      <header className="ah-section-heading"><RevealHeading paused={motionPaused}>A moment to understand.</RevealHeading></header>
      <dl className="ah-sleep-facts">
        <div><dt>Sleep rating</dt><dd className="ah-summary-rating">{report.rating || 'Unavailable'}<span className="ah-summary-baseline">{report.score == null ? 'No score for this night' : report.delta_vs_baseline == null ? 'Building your personal baseline' : <><strong><ScoreChange value={report.delta_vs_baseline} digits={0} /> points</strong> · your usual {fmt.score(report.baseline_score)}</>}</span></dd></div>
        <div><dt>Time asleep</dt><dd>{night?.worn ? fmt.minutes(night.duration_min) : 'Unavailable'}</dd></div>
        <div><dt>Wake time</dt><dd>{night?.worn ? fmt.hm(night.wake_time) : 'Unavailable'}</dd></div>
      </dl>
      <p className="ah-lead" data-tour="narrative">{veiled ? 'A score tells you how the night went. Your day can help explain why.' : <ScoreText text={summary} />}</p>
      {veiled ? <ActionButton className="btn btn-primary" data-tour="reveal" onClick={onReveal}>Explore the explanation<Icon name="chevron-right" size={16} /></ActionButton> : null}
    </RevealSection>

    {!veiled ? <RevealSection paused={motionPaused} className="ah-section ah-plan">
      <header className="ah-section-heading"><div><span className="ah-eyebrow">One change for tonight</span><RevealHeading paused={motionPaused}>Protect space for yourself.</RevealHeading></div></header>
      {report.suggestions?.[0] ? <TonightAction key={report.suggestions[0].id} suggestion={report.suggestions[0]} morning={morning} paused={motionPaused} /> : <p className="secondary">No suggestion for tonight yet. Review your activities below to keep your patterns up to date.</p>}
    </RevealSection> : null}

    {!veiled ? <RevealSection paused={motionPaused} className="ah-section ah-findings" data-tour="causes">
      <header className="ah-section-heading"><div><span className="ah-eyebrow">Connect the dots</span><RevealHeading paused={motionPaused}>The day behind your night.</RevealHeading></div><p>Patterns from your own history.<br />Associations, never certainties.</p></header>
      {report.missing_data ? <div className="ah-empty"><RevealHeading as="h3" paused={motionPaused}>Watch data unavailable</RevealHeading><p>{report.missing_data}</p></div> : report.model?.insufficient ? <div className="ah-empty"><RevealHeading as="h3" paused={motionPaused}>Building your baseline</RevealHeading><p>{report.confidence_note}</p></div> : causes.length ? <ol className="ah-finding-list">{causes.map((c: any, i: number) => <Finding key={c.factor} cause={c} date={report.night_date} expanded={selected === i} onSelect={() => selectCause(i)} />)}</ol> : <div className="ah-empty"><RevealHeading as="h3" paused={motionPaused}>No calendar pattern stands out</RevealHeading><p>{report.unexplained_note || 'Some nights have no clear explanation in the available data.'}</p></div>}
      {report.helpers?.length ? <p className="ah-helpers"><Icon name="sun" size={16} /><span>What helped: {report.helpers.map((h: any) => h.title).join(' · ')}</span></p> : null}
    </RevealSection> : null}

    {day ? <RevealSection paused={motionPaused} className="ah-section ah-day" id="day-story" tabIndex={-1}>
      <header className="ah-section-heading"><div><span className="ah-eyebrow">Follow the rhythm</span><RevealHeading paused={motionPaused}>A day. A body. A connection.</RevealHeading></div></header>
      <div className="ah-timeline-frame" data-tour="timeline">
        <div className="ah-trace-header"><span><i className="ah-live-dot" />{fmt.day(report.night_date)}<span className="ah-trace-subtitle">Calendar meets body</span></span><span className="ah-trace-legend"><i />Heart rate <b />Your usual</span></div>
        <div className="ah-timeline-scroll"><DayTimeline className="ah-timeline" date={day.date} events={day.events} visits={day.visits} hr={day.hr} norm={day.norm} night={day.night} nightPrev={day.night_prev} workouts={day.workouts} checks={day.checks} cursorMinute={cursor} highlightRange={rangeStart == null ? undefined : [rangeStart, Math.min(1440, rangeStart + (chosenEvidence.series?.length || 0) * (chosenEvidence.series_step_min || 5))]} onSeek={setCursor} /></div>
        <div className="ah-inspection"><div><strong>{minuteLabel(cursor)}</strong><span>{info?.event?.title || info?.place?.place_name || 'A moment in your day'}</span></div><p><strong>{fmt.num(info?.hr, 0)} <small>bpm</small></strong><span>{info?.norm == null ? 'No personal baseline' : `Your usual ${fmt.num(info.norm, 0)} bpm`}</span></p></div>
        <label className="ah-scrubber"><span className="sr-only">Inspect time of day</span><input type="range" min={0} max={1439} value={cursor} aria-valuetext={`${minuteLabel(cursor)}, ${info?.hr == null ? 'heart rate unavailable' : info.hr + ' beats per minute'}, ${info?.event?.title || 'no calendar event'}`} onChange={(e) => setCursor(+e.target.value)} /></label>
        <p className="ah-chart-note">Select an event or move through the day. The dotted line is your personal baseline; the shaded area shows readings above it.</p>
      </div>
    </RevealSection> : null}

    {night?.worn ? <RevealSection paused={motionPaused} className="ah-section ah-recovery" data-tour="recovery">
      <header className="ah-section-heading"><div><span className="ah-eyebrow">The quieter signals</span><RevealHeading paused={motionPaused}>More than a number.</RevealHeading></div><p>Last night's recovery markers,<br />compared with your usual.</p></header>
      <MetricGroup paused={motionPaused}>{recovery.filter((m: any) => MARKERS.includes(m.key)).map((m: any) => <Metric key={m.key} marker={m} paused={motionPaused} />)}</MetricGroup>
      <button className="ah-text-link ah-more" aria-expanded={moreOpen} aria-controls="ah-night-details" onClick={() => setMoreOpen(!moreOpen)}>{moreOpen ? 'Close night details' : 'A closer look at the night'}<Icon name={moreOpen ? 'x' : 'chevron-right'} size={16} /></button>
      <Collapse id="ah-night-details" open={moreOpen}><div className="ah-night-details"><div className="ah-metric-grid">{recovery.filter((m: any) => !MARKERS.includes(m.key)).map((m: any) => <Metric key={m.key} marker={m} />)}</div><RevealHeading as="h3" paused={motionPaused}>Your sleep, in stages</RevealHeading><p>{fmt.hm(night.sleep_onset)} asleep · {fmt.hm(night.wake_time)} awake · {night.interruptions} interruptions</p><Stages night={night} /><details className="ah-data-details"><summary>Read sleep-stage times</summary><div className="ah-data-scroll"><table className="data"><thead><tr><th>Stage</th><th>Start</th><th>End</th></tr></thead><tbody>{night.stages?.map((stage: any, i: number) => <tr key={i}><td>{stage.kind}</td><td>{fmt.hm(stage.start)}</td><td>{fmt.hm(stage.end)}</td></tr>)}</tbody></table></div></details></div></Collapse>
    </RevealSection> : null}

    <footer className="ah-report-footer" data-tour="confidence"><div><Icon name="shield" size={18} /><p>{report.confidence_note}<span>{meta.source === 'demo' ? 'Simulated health & calendar data' : 'Imported health & calendar data'} · {report.reasoning_mode === 'claude' ? 'AI-assisted narrative' : 'Rule-based narrative'}</span></p></div><label>History used<select className="select" aria-label="Nights of history used" value={historyDays ?? 'all'} onChange={(e) => setHistoryDays(e.target.value === 'all' ? null : +e.target.value)}>{[7, 14, 28].map((n) => <option key={n} value={n}>{n} nights</option>)}<option value="all">All nights</option></select></label></footer>
  </div>;
}

function Metric({ marker: m, paused = false }: { marker: any; paused?: boolean }) {
  const reduced = useReducedMotion();
  const value = m.key === 'wrist_temp_dev' ? fmt.signed(m.value, 1) : fmt.num(m.value, m.key === 'resp_rate' || m.key === 'spo2' ? 1 : 0);
  return <motion.article className="ah-metric" variants={quietItem} transition={{ ...calmTransition, duration: reduced || paused ? 0 : 0.65 }}><span className="ah-eyebrow">{m.label}</span><p className="ah-metric-value">{value}<span>{m.unit}</span></p><p>{m.delta == null ? 'Building your baseline' : m.key === 'hrv_ms' && m.delta_pct != null ? fmt.pct(m.delta_pct) + ' vs your usual' : fmt.signed(m.delta, 1) + ' ' + m.unit + ' vs your usual'}</p><span className="ah-marker-status">{m.status}</span></motion.article>;
}

export function MorningView({ date, reveal }: { date?: string; reveal?: boolean }) {
  const { today, meta, go, historyDays } = useApp();
  const morning = date || today;
  const [veiled, setVeiled] = useState(!!reveal);
  useEffect(() => setVeiled(!!reveal), [reveal]);
  const load = useLoad(async () => {
    const report = await api.get('/api/report/' + morning + (historyDays ? '?history_days=' + historyDays : ''));
    const day = await api.get('/api/day/' + report.night_date).catch(() => null);
    return { report, day };
  }, [morning, historyDays, meta.persona.key]);
  return <div className="after-hours">
    <header className="ah-page-header view-head"><div><span className="ah-eyebrow">Daily Tab</span><p>{fmt.dayLong(morning)}<span className="ah-demo-label">{meta.source === 'demo' ? 'Simulated example' : 'Your data'}</span></p></div><DateNav label={morning === today ? 'This morning' : fmt.day(morning)} prevHref={'/daily/' + dates.addDays(morning, -1)} nextHref={'/daily/' + dates.addDays(morning, 1)} prevDisabled={!!meta.start && morning <= dates.addDays(meta.start, 1)} nextDisabled={morning >= today} extra={morning !== today ? <button className="btn btn-sm" onClick={() => go('/daily/' + today)}>Today</button> : null} /></header>
    {load.loading ? <div className="ah-loading" aria-busy="true"><Skeleton height={400} /><p>Preparing your daily brief…</p></div> : load.error || !load.data ? <section className="ah-empty" role="alert"><span className="ah-eyebrow">Your daily brief</span><RevealHeading as="h1">A moment out of reach.</RevealHeading><p>{load.error?.message || 'We could not load this report.'}</p><ActionButton className="btn btn-primary" onClick={load.reload}>Try again</ActionButton></section> : <MorningReport key={`${morning}-${historyDays}-${meta.persona.key}`} report={load.data.report} day={load.data.day} morning={morning} veiled={veiled} onReveal={() => setVeiled(false)} />}
    <section id="reality-check" className="ah-section"><RealityView embedded onAnswered={load.reload} /></section>
  </div>;
}
