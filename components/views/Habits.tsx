'use client';
/* Habits view: every recurring pattern ranked by effect, with intervals and the adjusted effect. */
import Link from 'next/link';
import { useState } from 'react';
import { api } from '@/lib/api';
import { dates, fmt } from '@/lib/format';
import { DataTable } from '../charts/basic';
import { EffectBars } from '../charts/analysis';
import { useApp } from '../shell/AppContext';
import { ErrorCard, Skeleton, ViewHead, useLoad } from './common';

const GROUPS = ['all', 'good', 'bad', 'calendar', 'workout', 'social', 'travel', 'routine'];
let filterMemo = 'all'; // the filter survives navigating away and back, as before

export function HabitsView() {
  const { historyDays: hd } = useApp();
  const [filter, setFilterState] = useState(filterMemo);
  const [showTable, setShowTable] = useState(false);
  const setFilter = (g: string) => { filterMemo = g; setFilterState(g); };
  const load = useLoad(() => api.get('/api/habits' + (hd ? '?history_days=' + hd : '')), [hd]);
  const data = load.data;
  const items = data ? data.habits.filter((h: any) => filter === 'all' || h.direction === filter || h.group === filter) : [];
  return (
    <>
      <ViewHead eyebrow="Habits" title="Your patterns, ranked by effect" />
      <div className="v-habits stack">
        {load.loading ? <Skeleton height={200} /> : load.error || !data ? <ErrorCard error={load.error!} onRetry={load.reload} view="habits" /> : (
          <>
            <div className="row between">
              <div className="row v-habits-filters">
                {GROUPS.map((g) => <button key={g} className={'btn btn-sm ' + (filter === g ? 'btn-primary' : '')} type="button" onClick={() => setFilter(g)}>{g === 'all' ? 'All' : g[0].toUpperCase() + g.slice(1)}</button>)}
              </div>
              <button className="btn btn-sm" type="button" onClick={() => setShowTable(!showTable)}>{showTable ? 'Hide table' : 'Table view'}</button>
            </div>
            <div className="card" data-tour="effects">
              <div className="card-title"><h3>Effect on sleep score</h3><span className="tiny muted">{'model: ' + data.model.n_nights + ' nights · out-of-sample R² ' + fmt.num((data.model.r2_loo || 0) * 100, 0) + ' %'}</span></div>
              <EffectBars items={items.map((h: any) => ({ label: h.title, effect: h.effect, lo: h.ci_low, hi: h.ci_high, confidence: h.confidence, direction: h.direction, adjusted: h.adjusted_effect, n: h.n_with }))} rowH={36} />
              <div hidden={!showTable}>
                {showTable ? (
                  <DataTable
                    columns={[{ key: 'title', label: 'Pattern' }, { key: 'n', label: 'Nights with / without' }, { key: 'effect', label: 'Effect (pts)', num: true }, { key: 'ci', label: '95 % interval' }, { key: 'adjusted', label: 'Adjusted', num: true }, { key: 'confidence', label: 'Confidence' }]}
                    rows={items.map((h: any) => ({
                      title: h.title, n: h.n_with + ' / ' + h.n_without, effect: fmt.signed(h.effect, 1),
                      ci: h.ci_low === null || h.ci_low === undefined ? '–' : fmt.signed(h.ci_low, 1) + ' to ' + fmt.signed(h.ci_high, 1),
                      adjusted: h.adjusted_effect === null || h.adjusted_effect === undefined ? '–' : fmt.signed(h.adjusted_effect, 1), confidence: h.confidence,
                    }))} />
                ) : null}
              </div>
            </div>
            <div className="grid grid-3 v-habits-cards">
              {items.map((h: any) => {
                const adj = h.adjusted_effect !== null && h.adjusted_effect !== undefined;
                const v = adj ? h.adjusted_effect : h.effect || 0;
                return (
                  <div key={h.key} className="card v-habits-card">
                    <div className="row between"><h3>{h.title}</h3><span className={'badge badge-' + h.confidence}>{h.confidence}</span></div>
                    <p className="small secondary">{h.description}</p>
                    <div className="v-habits-effect">
                      <div>
                        <span className={'pts ' + (v < 0 ? 'pts-neg' : 'pts-pos')} style={{ fontSize: '24px' }}>{fmt.signed(adj ? h.adjusted_effect : h.effect, 1)}</span>
                        <span className="small muted">{adj ? ' pts, adjusted' : ' pts'}</span>
                      </div>
                      <div className="small secondary">{'Simple comparison: ' + fmt.signed(h.effect, 1) + (h.ci_low !== null && h.ci_low !== undefined ? ' (95 % ' + fmt.signed(h.ci_low, 1) + ' to ' + fmt.signed(h.ci_high, 1) + ')' : '')}</div>
                    </div>
                    <div className="row tiny muted">
                      <span>{'n = ' + h.n_with + ' vs ' + h.n_without + ' nights'}</span>
                      {h.metric_effects && h.metric_effects.hrv_ms_pct !== null && h.metric_effects.hrv_ms_pct !== undefined ? <span>{'HRV ' + fmt.pct(h.metric_effects.hrv_ms_pct, 0)}</span> : null}
                      {h.metric_effects && h.metric_effects.resting_hr !== null && h.metric_effects.resting_hr !== undefined ? <span>{'RHR ' + fmt.signed(h.metric_effects.resting_hr, 1) + ' bpm'}</span> : null}
                    </div>
                    {h.example_dates && h.example_dates.length ? (
                      <div className="row tiny">
                        <span className="muted">Recent:</span>
                        {h.example_dates.slice(-4).map((d: string) => <Link key={d} href={'/morning/' + dates.addDays(d, 1)}>{fmt.day(d)}</Link>)}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </>
  );
}
