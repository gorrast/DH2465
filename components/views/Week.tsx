'use client';

import Link from 'next/link';
import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { gsap } from 'gsap';
import { RevealHeading } from '../ui/Motion';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { EXAMPLE_APP_BRANDS, featuredAppBrands } from '@/lib/app-brands';
import { useAppStatistics } from './useAppStatistics';
import { WeeklyAppLogos } from './WeeklyAppLogos';
import { FunStatisticsView } from './FunStatistics';
import { WeeklyWrittenReport } from './WeeklyWrittenReport';
import { HabitsView } from './Habits';
import { WeeklyMotionContext, WeeklyNumber, WeeklyReveal, useWeeklyMotion } from './WeeklyMotion';
import { ScoreText } from '../ui/ScoreChange';
import { Icon } from '../ui/Icon';
import { api } from '@/lib/api';
import { dates, fmt } from '@/lib/format';
import { Bars } from '../charts/basic';
import { EffectBars, type HeatDay } from '../charts/analysis';
import { useApp } from '../shell/AppContext';
import { ErrorCard, Skeleton, useLoad } from './common';

/** A continuous red → amber → green scale, shared by the calendar and nightly scores. */
function sleepColor(score: number) {
  const stops = [[207, 90, 87], [225, 181, 90], [93, 173, 133]];
  const t = Math.max(0, Math.min(1, score / 100)) * 2;
  const from = stops[Math.min(1, Math.floor(t))], to = stops[Math.min(2, Math.floor(t) + 1)];
  return `rgb(${from.map((value, i) => Math.round(value + (to[i] - value) * (t >= 2 ? 1 : t % 1))).join(', ')})`;
}

function SleepCalendar({ days, end, weeks }: { days: HeatDay[]; end: string; weeks: number }) {
  const paused = useWeeklyMotion();
  const grid = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (paused || !grid.current) return;
    const node = grid.current;
    const tiles = Array.from(node.querySelectorAll<HTMLAnchorElement>('.weekly-calendar-cell > a'));
    const context = gsap.context(() => {
      // Animate links so the outer cells can independently animate calendar layout changes.
      const setters = tiles.map(tile => ({
        x: gsap.quickTo(tile, 'scaleX', { duration: 0.42, ease: 'power3.out' }),
        y: gsap.quickTo(tile, 'scaleY', { duration: 0.42, ease: 'power3.out' }),
      }));
      const reset = () => setters.forEach(set => { set.x(1); set.y(1); });
      const respond = (x: number, y: number) => {
        const activeTile = tiles.find(tile => tile.isConnected);
        const radius = (activeTile?.parentElement?.clientWidth || 60) * 2.5;
        tiles.forEach((tile, i) => {
          // AnimatePresence can retain old cells briefly while a date range changes.
          const cell = tile.parentElement;
          if (!cell?.isConnected) return;
          const box = cell.getBoundingClientRect();
          const distance = Math.hypot(x - box.left - box.width / 2, y - box.top - box.height / 2);
          const scale = 1 + 0.3 * Math.pow(Math.max(0, 1 - distance / radius), 2);
          setters[i].x(scale); setters[i].y(scale);
        });
      };
      const move = (event: PointerEvent) => { if (event.pointerType === 'mouse') respond(event.clientX, event.clientY); };
      const focus = (event: FocusEvent) => {
        const tile = (event.target as Element).closest('.weekly-calendar-cell');
        if (!tile) return;
        const box = tile.getBoundingClientRect();
        respond(box.left + box.width / 2, box.top + box.height / 2);
      };
      const blur = (event: FocusEvent) => { if (!node.contains(event.relatedTarget as Node)) reset(); };
      node.addEventListener('pointermove', move);
      node.addEventListener('pointerleave', reset);
      node.addEventListener('focusin', focus);
      node.addEventListener('focusout', blur);
      return () => {
        node.removeEventListener('pointermove', move);
        node.removeEventListener('pointerleave', reset);
        node.removeEventListener('focusin', focus);
        node.removeEventListener('focusout', blur);
      };
    }, node);
    return () => context.revert();
  }, [paused, weeks, end, days]);
  const start = dates.addDays(end, -weeks * 7);
  const byDate = new Map(days.map(day => [day.date, day]));
  const nights = Array.from({ length: weeks * 7 }, (_, i) => {
    const date = dates.addDays(start, i);
    return byDate.get(date) || { date, worn: false, score: null };
  });
  const offset = (dates.parse(start).getDay() + 6) % 7;
  const recorded = nights.filter(day => day.worn && day.score != null);
  const average = recorded.length ? recorded.reduce((sum, day) => sum + day.score!, 0) / recorded.length : null;
  return <>
    <div className="weekly-calendar-summary"><div><span className="eyebrow">Average sleep score</span><strong>{average == null ? '—' : <WeeklyNumber value={average} />}</strong><span className="small muted"> / 100</span></div><p>{fmt.day(start)} — {fmt.day(dates.addDays(end, -1))}<span>{recorded.length} of {nights.length} nights recorded</span></p></div>
    <div ref={grid} className="weekly-calendar" role="group" aria-label={`Sleep scores for the last ${weeks} ${weeks === 1 ? 'week' : 'weeks'}`}>
      {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(day => <span className="weekly-calendar-weekday" key={day}>{day}</span>)}
      {Array.from({ length: offset }, (_, i) => <span key={'blank-' + i} aria-hidden="true" />)}
      <AnimatePresence initial={false}>
        {nights.map(day => {
          const hasScore = day.worn && day.score != null;
          return <motion.div className="weekly-calendar-cell" key={day.date} layout={paused ? false : 'position'}
            initial={paused ? false : { opacity: 0, scale: 0.85 }} animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: paused ? 1 : 0.85 }} transition={{ duration: paused ? 0 : 0.28, layout: { duration: 0.4 } }}
            style={{ '--night-color': hasScore ? sleepColor(day.score!) : 'var(--card-3)' } as CSSProperties}>
            <Link className={hasScore ? '' : 'is-missing'} href={'/daily/' + dates.addDays(day.date, 1)}
              aria-label={`${fmt.dayLong(day.date)}, ${hasScore ? 'sleep score ' + day.score : 'no watch score'}. Open daily report.`}>
              <span>{dates.parse(day.date).getDate()}</span><strong>{hasScore ? fmt.score(day.score) : '—'}</strong>
            </Link>
          </motion.div>;
        })}
      </AnimatePresence>
    </div>
    <div className="weekly-sleep-legend"><span>0 · Lower</span><i aria-hidden="true" /><span>100 · Higher</span></div>
    <p className="weekly-calendar-note"><span className="weekly-missing-key" />Striped tiles: no watch score. Select a night to explore its daily report.</p>
  </>;
}

export function WeekView({ end: endParam }: { end?: string }) {
  const { today, historyDays: hd, meta } = useApp();
  const end = endParam || today;
  const reduced = useReducedMotion();
  const [motionPaused, setMotionPaused] = useState(false);
  const paused = !!reduced || motionPaused;
  const [weeks, setWeeks] = useState(4);
  const [patternsOpen, setPatternsOpen] = useState(false);
  const openPatterns = () => {
    setPatternsOpen(true);
    document.getElementById('weekly-patterns')?.scrollIntoView({ behavior: paused ? 'instant' : 'smooth' });
  };
  const load = useLoad(() => api.get('/api/week?end=' + end + (hd ? '&history_days=' + hd : '')), [end, hd, meta.persona.key]);
  const appStatistics = useAppStatistics();
  const floatingApps = featuredAppBrands(appStatistics.apps.data || [], (appStatistics.appHR.data || []).map(app => ({ packageName: app.package_name, appName: app.app_name })));
  const appKeys = new Set(floatingApps.map(app => app.key));
  const headerApps = [...floatingApps, ...EXAMPLE_APP_BRANDS.filter(app => !appKeys.has(app.key))].slice(0, 7);
  const w = load.data;
  const topPatterns = w ? [...w.top_habits].sort((a, b) => (a.effect ?? Infinity) - (b.effect ?? Infinity)) : [];
  return <WeeklyMotionContext.Provider value={paused}>
    <div className={'v-week weekly-dashboard' + (paused ? ' is-motion-paused' : '')}>
      <header className="weekly-page-heading view-head"><WeeklyAppLogos apps={headerApps} paused={paused} /><div><span className="eyebrow">Weekly Tab · A little perspective</span><RevealHeading as="h1" paused={paused} duration={1.7}>Your week, at a glance.</RevealHeading><p>See what lifts you up. Make space for more of it.</p></div><div className="weekly-page-tools"><span className="small muted">Through {fmt.day(dates.addDays(end, -1))}</span><button className="btn btn-sm btn-ghost" aria-pressed={paused} disabled={!!reduced} onClick={() => setMotionPaused(value => !value)}><Icon name={paused ? 'play' : 'pause'} size={14} />{reduced ? 'Reduced motion' : motionPaused ? 'Resume motion' : 'Pause motion'}</button></div>{floatingApps.length < 7 ? <span className="weekly-logo-example-note">{floatingApps.length ? 'Includes example app logos' : 'Example app logos · add app data to personalize'}</span> : null}</header>
      <FunStatisticsView embedded appStatistics={appStatistics} />
      <WeeklyWrittenReport key={`${end}-${meta.persona.key}`} end={end} paused={paused} />
      <header className="weekly-section-heading"><div><span className="eyebrow">Find your rhythm</span><h2>Sleep and weekly patterns</h2></div><p>Small moments in your day.<br />A bigger picture of your nights.</p></header>
      {load.loading ? <Skeleton height={460} /> : load.error || !w ? <ErrorCard error={load.error!} onRetry={load.reload} view="week" /> : <>
        <div className="weekly-overview-grid">
          <WeeklyReveal className="weekly-calendar-panel card" >
            <section data-tour="heat" aria-labelledby="sleep-history-title"><div className="weekly-panel-heading"><div><span className="eyebrow">Your nights, in color</span><h3 id="sleep-history-title">A little more perspective.</h3></div><Icon name="moon" size={24} /></div>
              <div className="weekly-range" role="group" aria-label="Sleep history range">{[1, 2, 3, 4].map(count => <button key={count} type="button" aria-pressed={weeks === count} onClick={() => setWeeks(count)}>{weeks === count ? <motion.span className="weekly-range-indicator" layoutId="weekly-range" transition={paused ? { duration: 0 } : { type: 'spring', stiffness: 400, damping: 32 }} /> : null}<span>{count} {count === 1 ? 'week' : 'weeks'}</span></button>)}</div>
              <SleepCalendar days={w.heat} end={end} weeks={weeks} />
            </section>
          </WeeklyReveal>
          <div className="weekly-overview-right">
            <WeeklyReveal className="card weekly-meetings" delay={0.08}><section data-tour="buckets" aria-labelledby="meeting-load-title"><div className="weekly-panel-heading"><div><span className="eyebrow">The space in your schedule</span><h3 id="meeting-load-title">Average sleep score by meeting load, last {w.weeks} weeks</h3></div></div><p className="weekly-chart-caption">Work nights · whiskers show the 95% range</p>
              <Bars className="v-week-buckets" items={w.buckets.map((b: any) => ({ label: b.label.replace(' to ', '–'), value: b.mean_score, n: b.n, lo: b.lo, hi: b.hi }))} unit="sleep score" height={235} ariaLabel={`Average sleep score by meeting load over ${w.weeks} weeks`} />
              <p className="secondary v-week-headline"><ScoreText text={w.headline} /></p>
            </section></WeeklyReveal>
            <WeeklyReveal className="card weekly-strongest" delay={0.14}><section data-tour="strongest"><div className="weekly-panel-heading"><span className="eyebrow">Strongest pattern</span><Icon name="sparkles" size={20} /></div><p className="v-week-strongest"><ScoreText text={w.strongest_pattern || 'Your patterns are still taking shape. More recorded nights will help.'} /></p><Link href="#weekly-patterns" onClick={() => setPatternsOpen(true)}>Explore your patterns <span aria-hidden="true">↗</span></Link></section></WeeklyReveal>
          </div>
        </div>
        <WeeklyReveal className="weekly-seven-section"><header className="weekly-section-heading"><div><span className="eyebrow">The day behind each score</span><h2>The last seven nights</h2></div><p>Your activities deserve a closer look.</p></header>
          <div className="v-week-last7">{w.last7.map((day: any) => <motion.div key={day.date} whileHover={paused ? undefined : { y: -6 }} transition={{ type: 'spring', stiffness: 300, damping: 22 }}><Link className={'v-week-day' + (day.worn ? '' : ' unworn')} href={'/daily/' + dates.addDays(day.date, 1)}><div className="v-week-day-name"><span>{dates.parse(day.date).toLocaleDateString(undefined, { weekday: 'short' })}</span><span>{dates.parse(day.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span></div><div className="v-week-day-score" style={{ color: day.worn && day.score != null ? sleepColor(day.score) : 'var(--ink-muted)' }}>{day.worn && day.score != null ? <WeeklyNumber value={day.score} /> : '—'}<small>/ 100</small></div><div className="v-week-day-chips">{day.chips.length ? day.chips.map((chip: string, j: number) => <span key={j} className="weekly-factor"><Icon name={/meeting/i.test(chip) ? 'calendar' : /workout|run/i.test(chip) ? 'run' : /social/i.test(chip) ? 'users' : /travel/i.test(chip) ? 'plane' : 'sun'} size={15} />{chip}</span>) : <span className="weekly-factor muted">No recorded factors</span>}</div><span className="weekly-day-open">Explore day <Icon name="chevron-right" size={14} /></span></Link></motion.div>)}</div>
        </WeeklyReveal>
        <WeeklyReveal className="card weekly-top-patterns"><div className="weekly-panel-heading"><div><span className="eyebrow">From what drains to what restores</span><h2>Top patterns</h2></div><Link href="#weekly-patterns" onClick={() => setPatternsOpen(true)}>See all patterns ↗</Link></div><p className="secondary small">Ordered by sleep-score impact: most negative to most positive.</p>
          <EffectBars items={topPatterns.map((h: any) => ({ label: h.title, effect: h.effect, lo: h.ci_low, hi: h.ci_high, confidence: h.confidence, direction: h.direction, adjusted: h.adjusted_effect, n: h.n_with, key: h.key }))} rowH={46} onSelect={openPatterns} />
          <p className="weekly-chart-caption">Nights with each pattern vs nights without, comparing weekdays and weekends separately. Diamonds show the model-adjusted effect. Associations, never certainties.</p>
        </WeeklyReveal>
      </>}
      <details id="weekly-patterns" className="card weekly-patterns" open={patternsOpen} onToggle={event => setPatternsOpen(event.currentTarget.open)}><summary>Your recurring patterns</summary><div className="stack"><p className="secondary">Explore patterns by activity and compare their effect on your sleep.</p>{patternsOpen ? <HabitsView /> : null}</div></details>
    </div>
  </WeeklyMotionContext.Provider>;
}
