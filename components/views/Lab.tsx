'use client';
/* Under the hood: pipeline, model card, validation against planted truth, cold start, open challenges (SPEC §9.4). */
import Link from 'next/link';
import type { ReactNode } from 'react';
import { api } from '@/lib/api';
import { dates, fmt } from '@/lib/format';
import { Icon } from '../ui/Icon';
import { EffectBars, Scatter } from '../charts/analysis';
import { useApp } from '../shell/AppContext';
import { ErrorCard, Skeleton, ViewHead, useLoad } from './common';

const HISTORY_STOPS: (number | null)[] = [7, 14, 28, null];
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '–' : Math.round(v * 100) + ' %');
const num = (v: number | null | undefined, d?: number) => (v === null || v === undefined ? '–' : fmt.num(v, d === undefined ? 2 : d));

function Stat({ label, value, caption }: { label: string; value: ReactNode; caption?: string }) {
  return (
    <div className="stat-tile v-lab-stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {caption ? <div className="tiny muted">{caption}</div> : null}
    </div>
  );
}

function Step({ icon, title, sub }: { icon: string; title: string; sub: string }) {
  return (
    <div className="v-lab-step">
      <span className="v-lab-step-icon"><Icon name={icon} size={18} /></span>
      <div><strong>{title}</strong><div className="tiny muted">{sub}</div></div>
    </div>
  );
}

const CHALLENGES: [string, string][] = [
  ['Correlation is not causation, especially with one person’s data', 'Every number carries n, an interval and a confidence badge; the text says "was followed by", never "caused"; the footer reports out-of-sample fit.'],
  ['The calendar misses coffee, alcohol, screens and unbooked stress', 'Nights the calendar cannot explain are flagged; body signals (resting heart rate, wrist temperature) hint at alcohol or illness; unbooked activities are detected from Maps and the watch.'],
  ['Cold start: value shows up only after weeks', 'The watch view works from night one; explanations start at ten nights; the slider above shows confidence firming up.'],
  ['Health plus calendar data is a sensitive combination', 'Only your own answers are stored, in your account and visible to no one else; the Data view lists every field and why; the optional AI narrative receives only a de-identified summary.'],
  ['The watch must be worn as much as possible', 'Charging gaps and unworn nights are handled gracefully, and the Lab shows that missingness is not random.'],
];

export function LabView() {
  const { today, historyDays: hd, setHistoryDays } = useApp();
  const q = hd ? '?history_days=' + hd : '';
  const load = useLoad(() => Promise.all([
    api.get('/api/model' + q), api.get('/api/validation'), api.get('/api/report/' + today).catch(() => null), api.get('/api/habits' + q),
  ]), [hd, today]);
  return (
    <>
      <ViewHead eyebrow="Under the hood" title="How the engine explains a night"><span className="badge badge-accent">Simulator ground truth — demo only</span></ViewHead>
      <div className="v-lab stack">
        {load.loading ? <Skeleton height={200} /> : load.error || !load.data ? <ErrorCard error={load.error!} onRetry={load.reload} view="lab" /> : <LabBody data={load.data} hd={hd} setHistoryDays={setHistoryDays} />}
      </div>
    </>
  );
}

function LabBody({ data, hd, setHistoryDays }: { data: any[]; hd: number | null; setHistoryDays: (n: number | null) => void }) {
  const [model, val, report] = data;
  const src = (report && report.sources) || {};
  const nullRow = val.available ? val.coefficients.find((c: any) => c.null_planted) : null;
  return (
    <>
      <div className="card" data-tour="pipeline">
        <div className="card-title"><h3>The pipeline</h3></div>
        <div className="v-lab-pipeline">
          <Step icon="calendar" title="Calendar" sub={(src.calendar_events || '–') + ' events yesterday'} /><span className="v-lab-arrow">→</span>
          <Step icon="map" title="Maps" sub={(src.maps_places || '–') + ' places'} /><span className="v-lab-arrow">→</span>
          <Step icon="watch" title="Watch" sub={(src.watch_minutes || 0).toLocaleString('en') + ' minutes'} /><span className="v-lab-arrow">→</span>
          <Step icon="habits" title="Features" sub="10 numbers per day" /><span className="v-lab-arrow">→</span>
          <Step icon="heart" title="Personal baselines" sub="your own medians" /><span className="v-lab-arrow">→</span>
          <Step icon="lab" title="Within-person model" sub={model.n_nights + ' nights, ridge λ ' + num(model.ridge_lambda, 0)} /><span className="v-lab-arrow">→</span>
          <Step icon="brain" title="Attribution" sub="only factors present that day" /><span className="v-lab-arrow">→</span>
          <Step icon="sparkles" title="Suggestions" sub="calendar-ready blocks" />
        </div>
      </div>

      <div className="card" data-tour="model">
        <div className="card-title"><h3>Model card</h3><span className="tiny muted">ridge regression across your nights, penalty chosen by leave-one-out cross-validation</span></div>
        <div className="grid grid-5">
          <Stat label="Nights in the fit" value={String(model.n_nights)} caption={model.n_unworn ? model.n_unworn + ' unworn nights excluded' : 'all nights worn'} />
          <Stat label="In-sample R²" value={pct(model.r2)} caption="how much the fit explains on the nights it saw" />
          <Stat label="Out-of-sample R²" value={pct(model.r2_loo)} caption="honest number: each night predicted without itself" />
          <Stat label="Typical error" value={'±' + num(model.rmse_loo, 0)} caption="sleep-score points, out of sample" />
          <Stat label="Calm-day prediction" value={num(model.calm_day_pred, 0)} caption="a day with none of the factors" />
        </div>
        {model.insufficient ? <p className="secondary">Fewer than ten nights: the model waits. Causes are not shown until it has enough to learn from.</p> : null}
        <h4 style={{ marginTop: '14px' }}>Effect per unit of each factor</h4>
        <EffectBars rowH={30} items={model.coefficients.filter((c: any) => c.n_active > 0).map((c: any) => ({ label: c.label, effect: c.value, lo: c.ci_low, hi: c.ci_high, n: c.n_active, direction: Math.abs(c.value) < 0.3 ? 'neutral' : c.value > 0 ? 'good' : 'bad' }))} />
        <p className="tiny muted">95 % intervals per factor from a moving-block bootstrap; with ten factors expect roughly one false alarm in a null world.</p>
      </div>

      <div className="card soft" data-tour="coldstart">
        <div className="card-title"><h3>Cold start: how much history does it need?</h3><span className="chip">{hd ? hd + ' nights' : 'all nights'}</span></div>
        <div className="row" style={{ gap: '14px' }}>
          <span className="small muted">7</span>
          <input type="range" min={0} max={3} step={1} defaultValue={String(HISTORY_STOPS.indexOf(hd))} aria-label="Nights of history" onChange={(e) => setHistoryDays(HISTORY_STOPS[+e.target.value])} />
          <span className="small muted">all</span>
        </div>
        <p className="small secondary">Slide left and watch the intervals widen and the badges drop. The app shows what your watch measured from night one; explanations start at ten nights and firm up over weeks. A pill in the top bar reminds you while a shorter history is in use.</p>
      </div>

      {val.available ? (
        <>
          <div className="card" data-tour="validation">
            <div className="card-title"><h3>Checked against the planted truth</h3><span className="badge badge-accent">Simulator ground truth — demo only</span></div>
            <div className="grid grid-3">
              <div className="span-2">
                <Scatter height={320} identity xLabel="planted effect (points per unit)" yLabel="estimated effect"
                  points={val.coefficients.filter((c: any) => c.planted_total !== null).map((c: any) => ({ x: c.planted_total, y: c.estimated, lo: c.ci_low, hi: c.ci_high, label: c.label }))
                    .concat(val.coefficients.filter((c: any) => c.planted_direct !== null).map((c: any) => ({ x: c.planted_direct, y: c.estimated, label: c.label + ' (direct)', hollow: true })))} />
                <p className="tiny muted">Each dot is one factor: what the simulator planted (horizontal) vs what the engine estimated (vertical); bars are the engine’s 95 % intervals; on the diagonal means perfect. Filled dots: the total effect including correlated hidden factors. Hollow dots: the direct effect alone — the calendar sees the dinner, not the wine.</p>
              </div>
              <div className="stack">
                <Stat label="Rank agreement" value={num(val.spearman_total, 2)} caption={'Spearman between planted and estimated effects — ' + (val.spearman_total >= 0.8 ? 'the engine ordered the real causes correctly' : val.spearman_total >= 0.6 ? 'mostly the right order' : 'weak ordering')} />
                <Stat label="Night-by-night agreement" value={num(val.pooled_spearman, 2)} caption={'over every (night, factor) pair that was active (' + val.pooled_n + ' pairs)'} />
                {val.holdout ? <Stat label="Prediction skill" value={pct(val.holdout.skill)} caption={'predicts the last ' + val.holdout.n_test + ' nights ' + Math.round((val.holdout.skill || 0) * 100) + ' % better than assuming your median (error ±' + num(val.holdout.rmse_holdout, 0) + ' vs ±' + num(val.holdout.rmse_naive, 0) + ')'} /> : null}
                {nullRow ? <Stat label="Planted null" value={fmt.signed(nullRow.estimated, 1)} caption={nullRow.label + ' was planted as no effect for this persona — engine says ' + fmt.signed(nullRow.estimated, 1) + ' (interval ' + fmt.signed(nullRow.ci_low, 1) + ' to ' + fmt.signed(nullRow.ci_high, 1) + ')' + (nullRow.ci_covers_zero ? ': correctly covers zero' : ': a false alarm')} /> : null}
                {val.spearman_before_answers !== null && val.spearman_before_answers !== undefined ? <Stat label="After your answers" value={num(val.spearman_before_answers, 2) + ' → ' + num(val.spearman_after_answers, 2)} caption="rank agreement before vs after applying your reality-check answers" /> : null}
              </div>
            </div>
          </div>
          <ValidationDetails val={val} />
        </>
      ) : (
        <div className="card soft"><h3>No planted truth</h3><p className="secondary">{val.reason || 'This dataset was imported from real sources; there is nothing to validate against.'}</p></div>
      )}

      <div className="card" data-tour="challenges">
        <div className="card-title"><h3>Open challenges from the pitch, and what this demo does about them</h3></div>
        <div className="grid grid-2">
          {CHALLENGES.map(([c, a]) => <div key={c} className="card soft"><strong>{c}</strong><p className="small secondary" style={{ marginTop: '6px' }}>{a}</p></div>)}
        </div>
        {val.available && val.limitations ? (
          <div style={{ marginTop: '12px' }}><h4>Known limitations</h4><ul className="small secondary v-lab-list">{val.limitations.map((l: string) => <li key={l}>{l}</li>)}</ul></div>
        ) : null}
      </div>
    </>
  );
}

function ValidationDetails({ val }: { val: any }) {
  const r = val.reality, h = val.hidden, s = val.stressors;
  return (
    <div className="grid grid-3">
      <div className="card">
        <div className="card-title"><h3>Reality checks: right, wrong, missed</h3></div>
        <table className="data"><tbody>
          <tr><td>Booked, not attended — caught</td><td className="num">{String(r.booked_not_seen.tp)}</td></tr>
          <tr><td>Asked although it happened</td><td className="num">{String(r.booked_not_seen.fp)}</td></tr>
          <tr><td>Missed skips</td><td className="num">{String(r.booked_not_seen.fn)}</td></tr>
          <tr><td>Precision / recall</td><td className="num">{pct(r.booked_not_seen.precision) + ' / ' + pct(r.booked_not_seen.recall)}</td></tr>
          <tr><td>Unbooked activities found</td><td className="num">{r.seen_not_booked.tp + ' of ' + (r.seen_not_booked.tp + r.seen_not_booked.fn)}</td></tr>
        </tbody></table>
        <p className="tiny muted">Meetings attended from home never trigger a question: location cannot tell a video call from a skipped one, so we do not ask.</p>
      </div>
      <div className="card">
        <div className="card-title"><h3>What the calendar cannot see</h3></div>
        <ul className="small secondary v-lab-list">
          <li>{h.alcohol_nights + ' nights with alcohol, mostly after social evenings'}</li>
          <li>{h.caffeine_days + ' late-coffee days, ' + h.screens_nights + ' late-screen nights'}</li>
          <li>{(h.illness_nights || []).length + ' illness nights' + (h.illness_nights && h.illness_nights.length ? ' (' + fmt.day(h.illness_nights[0]) + ' onwards)' : '')}</li>
          <li>{'Sleep debt carried night to night (average ' + num(h.sleep_debt_mean, 0) + ' min)'}</li>
          <li>{(h.unworn_nights || []).length + ' unworn nights, ' + h.unworn_social_nights + ' of them after social evenings — missing data is not random'}</li>
        </ul>
        <p className="small">{'The engine flagged ' + h.flagged + ' nights as "not explained by your calendar": precision ' + pct(h.precision) + ', recall ' + pct(h.recall) + '.'}</p>
        {h.illness_nights && h.illness_nights.length ? <Link className="btn btn-sm" href={'/morning/' + dates.addDays(h.illness_nights[h.illness_nights.length - 1], 1)}>Show me a night the calendar can’t explain →</Link> : null}
      </div>
      <div className="card">
        <div className="card-title"><h3>Why this is not circular</h3></div>
        <p className="small secondary">The engine uses the same day features as the simulator, so recovering coefficients alone would prove little. What makes it a real test:</p>
        <ul className="small v-lab-list">
          <li>{pct((s.pct_booked_not_attended || 0) / 100) + ' of booked events were never attended — the calendar lies, and the engine only learns the truth through reality checks'}</li>
          <li>{pct((s.pct_nights_hidden || 0) / 100) + ' of nights carry a hidden factor the calendar cannot see'}</li>
          <li>{pct((s.pct_unworn || 0) / 100) + ' of nights have no watch data'}</li>
          <li>{'The score is non-linear and the fit is judged out of sample: in-sample R² minus out-of-sample R² = ' + num(s.r2_gap, 2)}</li>
          <li>A planted null factor checks for false alarms</li>
        </ul>
      </div>
    </div>
  );
}
