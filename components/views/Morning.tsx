'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { motion, useScroll, useTransform, useReducedMotion } from 'motion/react';
import { api } from '@/lib/api';
import { dates, fmt, minuteLabel, minuteOf, pointClass } from '@/lib/format';
import { Icon } from '../ui/Icon';
import { SectionNavigation } from '../ui/SectionNavigation';
import { ActionButton, Collapse, RevealHeading, RevealSection, MetricGroup, quietItem, calmTransition } from '../ui/Motion';
import { ScoreChange, ScoreText } from '../ui/ScoreChange';
import { Sparkline, Stages } from '../charts/basic';
import { DayTimeline, valueAt } from '../charts/DayTimeline';
import { useApp } from '../shell/AppContext';
import { toast } from '../ui/overlays';
import { RealityView } from './Reality';
import { DailyGenerationForm, useDailyWrittenReport } from './DailyWrittenReport';
import { DateNav, Skeleton, useLoad } from './common';

const MARKERS = ['hrv_ms', 'resting_hr'];

function DailyReportPrompt({ paused, controller }: { paused: boolean; controller: ReturnType<typeof useDailyWrittenReport> }) {
  const [hintOpen, setHintOpen] = useState(false);
  const id = useId();
  const reduced = useReducedMotion();
  const tooltip = <motion.span className="ah-generate-tooltip" id={id + '-tip'} role="tooltip" initial={false}
    animate={{ opacity: hintOpen ? 1 : 0, y: hintOpen ? 0 : 10, scale: hintOpen ? 1 : 0.88, visibility: hintOpen ? 'visible' : 'hidden' }}
    transition={paused || reduced ? { duration: 0 } : { type: 'spring', duration: 0.5, bounce: 0.3 }}>
    Get today’s report: what last night looked like and what in your day likely shaped it. You can generate it once a day, so make sure last night’s data has synced first.
  </motion.span>;
  return <section className="ah-report-prompt" id="daily-report-prompt" aria-labelledby={id + '-title'}
    onPointerOver={event => { if (event.pointerType === 'mouse' && (event.target as HTMLElement).closest('.ah-generate-action')) setHintOpen(true); }} onPointerLeave={() => setHintOpen(false)}
    onFocus={event => setHintOpen(!!(event.target as HTMLElement).closest('.ah-generate-action'))} onBlur={() => setHintOpen(false)}
    onKeyDown={event => { if (event.key === 'Escape') setHintOpen(false); }} onClick={() => setHintOpen(false)}>
    <RevealHeading id={id + '-title'} paused={paused}>What lies behind the score?</RevealHeading>
    {/* the check-in is there from the start: one click on Generate writes the report */}
    <DailyGenerationForm controller={controller} checkinOpen tooltip={tooltip} tooltipId={id + '-tip'} />
  </section>;
}

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

// The day a free-text suggestion is about, counted from the app's today: a weekday it names ("next Monday", "on
// Thursday"), tomorrow, or else tonight.
const WEEKDAYS = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
function suggestionDay(text: string, today: string): string {
  const t = text.toLowerCase();
  if (/\btomorrow\b/.test(t)) return dates.addDays(today, 1);
  const named = WEEKDAYS.findIndex((d) => new RegExp('\\b' + d + '\\b').test(t));
  if (named >= 0) {
    const ahead = (named - dates.parse(today).getDay() + 7) % 7;
    return dates.addDays(today, ahead === 0 ? 7 : ahead);   // "Monday" said on a Monday means next week's
  }
  return today;
}
const SUGGESTION_HOURS = [18, 21];   // an evening block: the suggestions are about how an evening goes

/** A calendar file (.ics) for the suggestion, made in the browser: nothing is sent or saved, so the read-only demo
 * can use it too. Floating local times, so it lands at 18:00 wherever it is opened. */
function downloadSuggestion(text: string, day: string) {
  const esc = (v: string) => v.replace(/\\/g, '\\\\').replace(/[,;]/g, (c) => '\\' + c).replace(/\n/g, '\\n');
  const stamp = (h: number) => day.replace(/-/g, '') + 'T' + String(h).padStart(2, '0') + '0000';
  const now = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  const ics = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//StressLess//Suggestion//EN', 'BEGIN:VEVENT',
    'UID:suggestion-' + day + '-' + Date.now() + '@stressless', 'DTSTAMP:' + now,
    'DTSTART:' + stamp(SUGGESTION_HOURS[0]), 'DTEND:' + stamp(SUGGESTION_HOURS[1]),
    'SUMMARY:' + esc('StressLess: ' + text), 'DESCRIPTION:' + esc(text + '\n\nFrom your StressLess daily report.'),
    'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
  const url = URL.createObjectURL(new Blob([ics], { type: 'text/calendar;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'stressless-suggestion-' + day + '.ics';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The written report's suggestion, repeated where the page ends (same card style as the suggestion for tonight). */
function ReportSuggestion({ text, today, paused }: { text: string; today: string; paused: boolean }) {
  const { meta } = useApp();
  const day = suggestionDay(text, today);
  // StressLess adds the suggestion to your calendar itself; the read-only demo can only say so
  const addToCalendar = () => meta.read_only
    ? toast('This would have added the item to your calendar automatically, but this demo is read-only.', { kind: 'info', duration: 6000 })
    : downloadSuggestion(text, day);
  const when = (day === today ? 'Tonight' : fmt.day(day)) + ', ' + SUGGESTION_HOURS.map((h) => h + ':00').join('–');
  return <section className="ah-tonight" data-tour="suggestion" aria-label="One thing to try">
    <div className="ah-tonight-icon"><Icon name="sparkles" size={22} /></div>
    <div className="ah-tonight-copy"><span className="ah-eyebrow">Suggestion</span><RevealHeading as="h3" paused={paused}>{text}</RevealHeading>
      <div className="ah-actions">
        <button className="btn btn-primary" type="button" onClick={addToCalendar}>Add to calendar<Icon name="calendar" size={16} /></button>
        <a className="btn" href="#night-explanation">Read the report<Icon name="chevron-right" size={16} /></a>
      </div>
      <p className="ah-estimate">{when}</p>
    </div>
  </section>;
}

/** Until the written report is there, its suggestion is a promise: the page never shows one the report won't repeat. */
function SuggestionPending({ paused }: { paused: boolean }) {
  return <section className="ah-tonight" aria-label="Your suggestion">
    <div className="ah-tonight-icon"><Icon name="sparkles" size={22} /></div>
    <div className="ah-tonight-copy"><span className="ah-eyebrow">Suggestion</span><RevealHeading as="h3" paused={paused}>Your suggestion comes with today&rsquo;s report</RevealHeading>
      <p>Generate the daily report, and the one thing worth trying shows up here, ready to add to your calendar.</p>
      <div className="ah-actions"><a className="btn btn-primary" href="#daily-report-prompt">Generate today&rsquo;s report<Icon name="arrow-up" size={16} /></a></div>
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

function MorningReport({ report, day, veiled, onReveal, motionPaused, morning, onSuggestion }: { morning: string; report: any; day: any; veiled: boolean; onReveal: () => void; motionPaused: boolean; onSuggestion: (text: string | null) => void }) {
  const heroRef = useRef<HTMLElement>(null);
  const reducedMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ['start start', 'end -35%'] });
  const glowScale = useTransform(scrollYProgress, [0, 1], [1, 1.28]);
  const glowOpacity = useTransform(scrollYProgress, [0, 1], [1, 0.15]);
  const [selected, setSelected] = useState<number | null>(null);
  const [cursor, setCursor] = useState(18 * 60);
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
  const recovery = (report.recovery || []).filter((m: any) => MARKERS.includes(m.key));
  const sleepSummary = <>
      <dl className="ah-sleep-facts">
        <div><dt>Sleep rating</dt><dd className="ah-summary-rating">{report.rating || 'Unavailable'}<span className="ah-summary-baseline">{report.score == null ? 'No score for this night' : report.delta_vs_baseline == null ? 'Building your personal baseline' : <><strong><ScoreChange value={report.delta_vs_baseline} digits={0} /> points</strong> · your usual {fmt.score(report.baseline_score)}</>}</span></dd></div>
        <div><dt>Time asleep</dt><dd>{night?.worn ? fmt.minutes(night.duration_min) : 'Unavailable'}</dd></div>
        <div><dt>Wake time</dt><dd>{night?.worn ? fmt.hm(night.wake_time) : 'Unavailable'}</dd></div>
      </dl>
      {veiled ? <ActionButton className="btn btn-primary" data-tour="reveal" onClick={onReveal}>Explore the explanation<Icon name="chevron-right" size={16} /></ActionButton> : null}
  </>;
  const written = useDailyWrittenReport(morning, motionPaused || !!reducedMotion, sleepSummary);
  // the written report's suggestion, for the suggestion at the bottom of the page (they must not disagree)
  const writtenSuggestion = written.report?.content.suggestion ?? null;
  useEffect(() => onSuggestion(writtenSuggestion), [writtenSuggestion, onSuggestion]);
  return <div className="ah-report">
    <section ref={heroRef} className={'ah-hero' + (motionPaused ? ' is-motion-paused' : '')} data-page-section="Your night" data-tour="hero" aria-labelledby="morning-title">
      <motion.div className="ah-hero-glow" aria-hidden="true" style={{ scale: reducedMotion || motionPaused ? 1 : glowScale, opacity: reducedMotion || motionPaused ? 1 : glowOpacity }} />
      <p className="ah-night-date">Last night · {fmt.day(report.night_date)}</p>
      <div className="ah-hero-main">
        <div className="ah-hero-night">
          <RevealHeading as="h1" id="morning-title" paused={motionPaused} lines={["This night's", <em key="score">sleep score</em>]} />
          <div className="ah-score-stage"><SleepScore report={report} /></div>
        </div>
        <DailyReportPrompt paused={motionPaused} controller={written} />
      </div>
      <div className="ah-hero-controls"><a className="ah-text-link" href="#night-explanation">Explore your night <span aria-hidden="true">↓</span></a></div>
    </section>

    {written.output}

    {!written.report ? <RevealSection paused={motionPaused} data-page-section="Sleep summary" className="ah-section ah-sleep-summary" id="night-explanation" tabIndex={-1}>
      <header className="ah-section-heading"><RevealHeading paused={motionPaused}>A moment to understand.</RevealHeading></header>
      {sleepSummary}
    </RevealSection> : null}


    {!veiled || night?.worn ? <RevealSection paused={motionPaused} data-page-section="Findings and recovery" className={'ah-section daily-insights-grid' + (veiled || !night?.worn ? ' is-single' : '')}>
    <section className="ah-findings">
    {!veiled ? <div data-tour="causes">
      <header className="ah-section-heading"><RevealHeading paused={motionPaused}>Similar day patterns</RevealHeading></header>
      {report.missing_data ? <div className="ah-empty"><RevealHeading as="h3" paused={motionPaused}>Watch data unavailable</RevealHeading><p>{report.missing_data}</p></div> : report.model?.insufficient ? <div className="ah-empty"><RevealHeading as="h3" paused={motionPaused}>Building your baseline</RevealHeading><p>{report.confidence_note}</p></div> : causes.length ? <ol className="ah-finding-list">{causes.map((c: any, i: number) => <Finding key={c.factor} cause={c} date={report.night_date} expanded={selected === i} onSelect={() => selectCause(i)} />)}</ol> : <div className="ah-empty"><RevealHeading as="h3" paused={motionPaused}>No calendar pattern stands out</RevealHeading><p>{report.unexplained_note || 'Some nights have no clear explanation in the available data.'}</p></div>}
      {report.helpers?.length ? <p className="ah-helpers"><Icon name="sun" size={16} /><span>What helped: {report.helpers.map((h: any) => h.title).join(' · ')}</span></p> : null}
    </div> : null}
    {night?.worn ? <section className="ah-night-details" aria-labelledby="sleep-stages-title">
      <RevealHeading as="h3" id="sleep-stages-title" paused={motionPaused}>Your sleep, in stages</RevealHeading>
      <p>{fmt.hm(night.sleep_onset)} asleep · {fmt.hm(night.wake_time)} awake · {night.interruptions} interruptions</p>
      <Stages night={night} />
    </section> : null}
    </section>

    {night?.worn ? <section className="ah-recovery" data-tour="recovery">
      <header className="ah-section-heading"><RevealHeading paused={motionPaused}>Last night's recovery markers</RevealHeading></header>
      <MetricGroup paused={motionPaused}>{recovery.map((m: any) => <Metric key={m.key} marker={m} paused={motionPaused} />)}</MetricGroup>
    </section> : null}
    </RevealSection> : null}

    {day ? <RevealSection paused={motionPaused} data-page-section="Your day" className="ah-section ah-day" id="day-story" tabIndex={-1}>
      <header className="ah-section-heading"><RevealHeading paused={motionPaused}>BPM and Calendar events: Overview</RevealHeading></header>
      <div className="ah-timeline-frame" data-tour="timeline">
        <div className="ah-trace-header"><span><i className="ah-live-dot" />{fmt.day(report.night_date)}</span><span className="ah-trace-legend"><i />Heart rate <b />Your usual</span></div>
        <div className="ah-timeline-scroll"><DayTimeline className="ah-timeline" date={day.date} events={day.events} visits={day.visits} hr={day.hr} norm={day.norm} night={day.night} nightPrev={day.night_prev} workouts={day.workouts} checks={day.checks} cursorMinute={cursor} highlightRange={rangeStart == null ? undefined : [rangeStart, Math.min(1440, rangeStart + (chosenEvidence.series?.length || 0) * (chosenEvidence.series_step_min || 5))]} onSeek={setCursor} /></div>
        <div className="ah-inspection"><div><strong>{minuteLabel(cursor)}</strong><span>{info?.event?.title || info?.place?.place_name || 'A moment in your day'}</span></div><p><strong>{fmt.num(info?.hr, 0)} <small>bpm</small></strong><span>{info?.norm == null ? 'No personal baseline' : `Your usual ${fmt.num(info.norm, 0)} bpm`}</span></p></div>
        <label className="ah-scrubber"><span className="sr-only">Inspect time of day</span><input type="range" min={0} max={1439} value={cursor} aria-valuetext={`${minuteLabel(cursor)}, ${info?.hr == null ? 'heart rate unavailable' : info.hr + ' beats per minute'}, ${info?.event?.title || 'no calendar event'}`} onChange={(e) => setCursor(+e.target.value)} /></label>
        <p className="ah-chart-note">Select an event or move through the day. The dotted line is your personal baseline; the shaded area shows readings above it.</p>
      </div>
    </RevealSection> : null}



    <hr className="ah-report-divider" />
  </div>;
}

function Metric({ marker: m, paused = false }: { marker: any; paused?: boolean }) {
  const reduced = useReducedMotion();
  const value = fmt.num(m.value, 0);
  return <motion.article className="ah-metric" variants={quietItem} transition={{ ...calmTransition, duration: reduced || paused ? 0 : 0.65 }}><span className="ah-eyebrow">{m.label}</span><p className="ah-metric-value">{value}<span>{m.unit}</span></p><p>{m.delta == null ? 'Building your baseline' : m.key === 'hrv_ms' && m.delta_pct != null ? fmt.pct(m.delta_pct) + ' vs your usual' : fmt.signed(m.delta, 1) + ' ' + m.unit + ' vs your usual'}</p><span className="ah-marker-status">{m.status}</span></motion.article>;
}

export function MorningView({ date, reveal }: { date?: string; reveal?: boolean }) {
  const { today, meta, go } = useApp();
  const morning = date || today;
  const pageRef = useRef<HTMLDivElement>(null);
  const [veiled, setVeiled] = useState(!!reveal);
  const [reportSuggestion, setReportSuggestion] = useState<string | null>(null);
  const motionPaused = !!useReducedMotion();
  useEffect(() => setVeiled(!!reveal), [reveal]);
  const load = useLoad(async () => {
    const report = await api.get('/api/report/' + morning);
    const day = await api.get('/api/day/' + report.night_date).catch(() => null);
    return { report, day };
  }, [morning, meta.persona.key]);
  return <div ref={pageRef} className="after-hours">
    <header className="ah-page-header view-head"><div><span className="ah-eyebrow">Daily Tab</span><p>{fmt.dayLong(morning)}<span className="ah-demo-label">{meta.source === 'demo' ? 'Simulated example' : 'Your data'}</span></p></div><DateNav label={morning === today ? 'This morning' : fmt.day(morning)} prevHref={'/daily/' + dates.addDays(morning, -1)} nextHref={'/daily/' + dates.addDays(morning, 1)} prevDisabled={!!meta.start && morning <= dates.addDays(meta.start, 1)} nextDisabled={morning >= today} extra={morning !== today ? <button className="btn btn-sm" onClick={() => go('/daily/' + today)}>Today</button> : null} /></header>
    {load.loading ? <div className="ah-loading" aria-busy="true"><Skeleton height={400} /><p>Preparing your daily brief…</p></div> : load.error || !load.data ? <section className="ah-empty" role="alert"><span className="ah-eyebrow">Your daily brief</span><RevealHeading as="h1">A moment out of reach.</RevealHeading><p>{load.error?.message || 'We could not load this report.'}</p><ActionButton className="btn btn-primary" onClick={load.reload}>Try again</ActionButton></section> : <MorningReport morning={morning} key={`${morning}-${meta.persona.key}`} report={load.data.report} day={load.data.day} veiled={veiled} onReveal={() => setVeiled(false)} motionPaused={motionPaused} onSuggestion={setReportSuggestion} />}
    <div data-page-section="Reality check and tonight" className={'ah-section daily-actions-grid' + (veiled ? ' is-single' : '')}>
      <section id="reality-check" className="daily-reality-check" aria-label="Reality check"><RealityView embedded onAnswered={load.reload} /></section>
      {!veiled && reportSuggestion ? <section className="daily-protect-space" aria-labelledby="protect-space-title">
        <header className="view-head"><div><div className="eyebrow">From your daily report</div><RevealHeading id="protect-space-title" paused={motionPaused}>One thing to try</RevealHeading></div></header>
        <ReportSuggestion text={reportSuggestion} today={today} paused={motionPaused} />
      </section> : !veiled ? <section className="daily-protect-space" aria-labelledby="protect-space-title">
        <header className="view-head"><div><div className="eyebrow">From your daily report</div><RevealHeading id="protect-space-title" paused={motionPaused}>One thing to try</RevealHeading></div></header>
        <SuggestionPending paused={motionPaused} />
      </section> : null}
    </div>
    <SectionNavigation root={pageRef} paused={motionPaused} />
  </div>;
}
