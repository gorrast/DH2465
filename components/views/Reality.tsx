'use client';
/* Reality check inbox: ask only when calendar, Maps and the body disagree (SPEC §9.4). */
import Link from 'next/link';
import { useRef, useState } from 'react';
import { api } from '@/lib/api';
import { fmt } from '@/lib/format';
import { Icon } from '../ui/Icon';
import { toast } from '../ui/overlays';
import { ErrorCard, Skeleton, ViewHead, useLoad } from './common';

const KIND_ICON: Record<string, string> = { calendar: 'calendar', location: 'map', hr: 'watch' };

function HabitLine({ a }: { a: any }) {
  if (!a.habit_before && !a.habit_after) return null;
  const b = a.habit_before || {}, f = a.habit_after || {};
  return (
    <div className="v-reality-shift">
      <Icon name="habits" size={14} />
      <span>{(f.title || b.title) + ': '}</span>
      <strong>{fmt.signed(b.effect, 1) + ' → ' + fmt.signed(f.effect, 1) + ' pts'}</strong>
      <span className="muted">{' (' + (b.n_with || 0) + ' → ' + (f.n_with || 0) + ' nights)'}</span>
    </div>
  );
}

function CheckCard({ c, onAnswer }: { c: any; onAnswer: (c: any, value: string) => Promise<boolean> }) {
  const [pending, setPending] = useState(false);
  const answer = async (v: string) => { setPending(true); if (!(await onAnswer(c, v))) setPending(false); };
  return (
    <div className="card v-reality-card" data-check={c.id}>
      <div className="row between">
        <span className={'badge ' + (c.kind === 'seen_not_booked' ? 'badge-accent' : 'badge-warning')}>{c.kind === 'seen_not_booked' ? 'seen, not booked' : c.kind === 'location_mismatch' ? 'location mismatch' : 'booked, not seen'}</span>
        <span className="tiny muted">{fmt.day(c.date)}</span>
      </div>
      <h3 className="v-reality-question">{c.question}</h3>
      <div className="row v-reality-evidence">{c.evidence.map((e: any, i: number) => <span key={i} className="chip"><Icon name={KIND_ICON[e.kind] || 'info'} size={13} />{e.text}</span>)}</div>
      <div className="row between v-reality-actions">
        <div className="row">
          <button className="btn btn-primary" type="button" disabled={pending} onClick={() => answer('yes')}><Icon name="check" size={16} />Yes</button>
          <button className="btn" type="button" disabled={pending} onClick={() => answer('no')}><Icon name="x" size={16} />No</button>
        </div>
        <span className="tiny muted">{c.consequence || ''}</span>
      </div>
    </div>
  );
}

function ResolvedCard({ c, extra }: { c: any; extra?: any }) {
  return (
    <div className="card soft v-reality-resolved">
      <div className="row between">
        <span className="row"><span className={'badge badge-' + (c.status === 'yes' ? 'good' : 'critical')}>{c.status === 'yes' ? 'yes' : 'no'}</span><span className="small">{c.question}</span></span>
        <span className="tiny muted">{fmt.day(c.date)}</span>
      </div>
      {extra ? (
        <div className="row small"><HabitLine a={extra} /><Link className="btn btn-sm btn-ghost" href={'/replay/' + extra.replay_date}>See that day →</Link></div>
      ) : (
        <div className="row tiny muted">
          {c.consequence ? <span>{c.consequence.replace(/^If (yes|no), /, (m: string, w: string) => (w === c.status ? '' : m))}</span> : null}
          <Link href={'/replay/' + c.date}>See that day →</Link>
        </div>
      )}
    </div>
  );
}

export function RealityView() {
  const recent = useRef<Record<string, any>>({});
  const load = useLoad(() => api.get('/api/reality'), []);
  const data = load.data;

  async function answer(c: any, value: string): Promise<boolean> {
    try {
      const res = await api.post('/api/reality/' + c.id + '/answer', { answer: value });
      recent.current[c.id] = res;
      toast(value === 'yes' ? (c.kind === 'seen_not_booked' ? 'Added to your calendar and patterns' : 'Kept in your patterns') : 'Removed from your patterns', { kind: 'success' });
      load.setData(await api.get('/api/reality'));
      return true;
    } catch (e: any) {
      toast('Could not save: ' + e.message, { kind: 'error' });
      return false;
    }
  }

  return (
    <>
      <ViewHead eyebrow="Reality check" title="Did that actually happen?" />
      <div className="v-reality stack">
        <p className="secondary v-reality-intro"><Icon name="info" size={16} />{' We never ask you to log. We only ask when your calendar, your location and your body disagree.'}</p>
        {load.loading ? <Skeleton height={200} /> : load.error || !data ? <ErrorCard error={load.error!} onRetry={load.reload} view="reality" /> : (
          <>
            <div className="grid grid-3">
              <div className="span-2 stack">
                <h3>Open questions</h3>
                <div className="stack" data-tour="inbox">
                  {!data.open.length ? (
                    <div className="card empty"><Icon name="check" size={26} /><h2>All clear</h2><p>Calendar, Maps and watch agree for the last two weeks.</p></div>
                  ) : data.open.map((c: any) => <CheckCard key={c.id} c={c} onAnswer={answer} />)}
                </div>
              </div>
              <div className="stack">
                <h3>Answered</h3>
                <div className="stack">
                  {!data.resolved.length ? <p className="muted small">Nothing answered yet.</p> : data.resolved.map((c: any) => <ResolvedCard key={c.id} c={c} extra={recent.current[c.id]} />)}
                </div>
              </div>
            </div>
            <div className="stack">
              {data.older.length ? (
                <details className="card soft">
                  <summary>{'Older (' + data.older.length + ') — assumed as booked'}</summary>
                  <div className="stack" style={{ marginTop: '10px' }}>{data.older.map((c: any) => <CheckCard key={c.id} c={c} onAnswer={answer} />)}</div>
                </details>
              ) : null}
            </div>
          </>
        )}
      </div>
    </>
  );
}
