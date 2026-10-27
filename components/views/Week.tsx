'use client';
/* Week view: heat strip, meeting load vs sleep, strongest pattern, last seven days, top habits. */
import Link from 'next/link';
import { useState } from 'react';
import { FunStatisticsView } from './FunStatistics';
import { HabitsView } from './Habits';
import { ScoreText } from '../ui/ScoreChange';
import { api } from '@/lib/api';
import { bandFor, dates, fmt } from '@/lib/format';
import { Bars } from '../charts/basic';
import { EffectBars, HeatStrip } from '../charts/analysis';
import { useApp } from '../shell/AppContext';
import { ErrorCard, Skeleton, ViewHead, useLoad } from './common';

export function WeekView({ end: endParam }: { end?: string }) {
  const { today, historyDays: hd, go } = useApp();
  const end = endParam || today;
  const [patternsOpen, setPatternsOpen] = useState(false);
  const openPatterns = () => {
    setPatternsOpen(true);
    document.getElementById('weekly-patterns')?.scrollIntoView({ behavior: 'smooth' });
  };
  const load = useLoad(() => api.get('/api/week?end=' + end + (hd ? '&history_days=' + hd : '')), [end, hd]);
  const w = load.data;
  return (
    <>
      <ViewHead eyebrow="Weekly Tab" title="Your week, at a glance">
        <span className="small muted">{'up to ' + fmt.day(dates.addDays(end, -1))}</span>
      </ViewHead>
      <div className="stack weekly-statistics"><FunStatisticsView embedded /></div>
      <h2 className="section-heading">Sleep and weekly patterns</h2>
      <div className="v-week stack">
        {load.loading ? <Skeleton height={200} /> : load.error || !w ? <ErrorCard error={load.error!} onRetry={load.reload} view="week" /> : (
          <>
            <div className="card" data-tour="heat">
              <div className="card-title"><h3>{'Every night, ' + w.heat.length + ' of them'}</h3><span className="tiny muted">click a night to open its morning report</span></div>
              <HeatStrip className="v-week-heat" days={w.heat} onSelect={(d) => go('/daily/' + dates.addDays(d.date, 1))} />
            </div>
            <div className="grid grid-3">
              <div className="card span-2" data-tour="buckets">
                <div className="card-title"><h3>{'Average sleep score by meeting load, last ' + w.weeks + ' weeks'}</h3><span className="tiny muted">work nights only · whiskers: 95 % range</span></div>
                <Bars className="v-week-buckets" items={w.buckets.map((b: any) => ({ label: b.label, value: b.mean_score, n: b.n, lo: b.lo, hi: b.hi }))} unit="sleep score" height={260} ariaLabel="Average sleep score by meeting load" />
                <p className="secondary v-week-headline"><ScoreText text={w.headline} /></p>
              </div>
              <div className="card accent" data-tour="strongest">
                <div className="eyebrow small">Strongest pattern</div>
                <p className="v-week-strongest"><ScoreText text={w.strongest_pattern || 'No pattern clears the confidence bar yet.'} /></p>
                <Link className="small" href="#weekly-patterns" onClick={() => setPatternsOpen(true)} style={{ color: 'inherit', textDecoration: 'underline' }}>Explore your patterns ↓</Link>
              </div>
            </div>
            <div className="card">
              <div className="card-title"><h3>The last seven nights</h3></div>
              <div className="v-week-last7">
                {w.last7.map((d: any) => (
                  <Link key={d.date} className={'v-week-day' + (d.worn ? '' : ' unworn')} href={'/daily/' + dates.addDays(d.date, 1)}>
                    <div className="v-week-day-name">{fmt.day(d.date)}</div>
                    <div className="v-week-day-score" style={{ color: d.worn ? 'var(--status-' + bandFor(d.score) + ')' : 'var(--ink-muted)' }}>{d.worn ? String(d.score) : '–'}</div>
                    <div className="v-week-day-chips">{d.chips.slice(0, 3).map((c: string, i: number) => <span key={i} className="chip">{c}</span>)}</div>
                  </Link>
                ))}
              </div>
            </div>
            <div className="card">
              <div className="card-title"><h3>Top patterns</h3><Link className="small" href="#weekly-patterns" onClick={() => setPatternsOpen(true)}>See all →</Link></div>
              <EffectBars items={w.top_habits.map((h: any) => ({ label: h.title, effect: h.effect, lo: h.ci_low, hi: h.ci_high, confidence: h.confidence, direction: h.direction, adjusted: h.adjusted_effect, n: h.n_with, key: h.key }))} onSelect={openPatterns} />
              <div className="tiny muted">Difference in sleep score on nights with the pattern vs without, weekday and weekend nights compared separately. Diamonds: model-adjusted effect.</div>
            </div>
          </>
        )}
      </div>
      <details id="weekly-patterns" className="card weekly-patterns" open={patternsOpen} onToggle={(event) => setPatternsOpen(event.currentTarget.open)}><summary>Your recurring patterns</summary><div className="stack"><p className="secondary">Explore patterns by activity and compare their effect on your sleep.</p>{patternsOpen ? <HabitsView /> : null}</div></details>
    </>
  );
}
