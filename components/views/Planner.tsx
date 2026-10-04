'use client';
/* Planner: what-if on today's (or a coming day's) calendar, with a predicted delta and likely range (SPEC §9.4). */
import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { dates, fmt, minuteOf } from '@/lib/format';
import { eventIcon } from '@/lib/icons';
import { palette } from '@/lib/palette';
import { Icon } from '../ui/Icon';
import { toast } from '../ui/overlays';
import { useApp } from '../shell/AppContext';
import { DateNav, Skeleton, ViewHead, useLoad } from './common';

interface Mod { op: string; event_id: string; hour?: number; hours?: number }
const FACTOR_LABEL: Record<string, string> = {
  meetings_over_3: 'meeting load', b2b_over_2: 'back-to-back', late_meeting_hours: 'late meeting', evening_social: 'evening social', workout_morning: 'morning workout',
  workout_late: 'late workout', travel: 'travel', early_start: 'early start', protected_evening: 'protected evening', is_weekend: 'weekend',
};

export function PlannerView({ date: dateParam }: { date?: string }) {
  const { today } = useApp();
  const date = dateParam || today;
  const max = dates.addDays(today, 7);
  const load = useLoad(async () => {
    const day = await api.get('/api/day/' + date);
    let report = null;
    if (date === today) { try { report = await api.get('/api/report/' + today); } catch { report = null; } }
    return { day, report };
  }, [date, today]);
  return (
    <>
      <ViewHead eyebrow="Planner" title={date === today ? 'Tonight' : fmt.dayLong(date)}>
        <DateNav label={fmt.day(date)} prevHref={'/planner/' + dates.addDays(date, -1)} nextHref={'/planner/' + dates.addDays(date, 1)} prevDisabled={date <= today} nextDisabled={date >= max} />
      </ViewHead>
      <div className="v-planner stack">
        {load.loading ? <Skeleton height={220} />
          : load.error || !load.data ? <div className="card empty"><h2>Nothing to plan here</h2><p>{load.error?.message}</p></div>
          : <PlannerBody date={date} today={today} initialDay={load.data.day} initialReport={load.data.report} />}
      </div>
    </>
  );
}

function PlannerBody({ date, today, initialDay, initialReport }: { date: string; today: string; initialDay: any; initialReport: any }) {
  const [day, setDay] = useState(initialDay);
  const [report, setReport] = useState(initialReport);
  const [mods, setMods] = useState<Mod[]>([]);
  const [w, setW] = useState<any>(null);   // the latest what-if result, with the number of changes it was computed for
  const seq = useRef(0);
  const [werr, setWerr] = useState<string | null>(null);
  const [dim, setDim] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [recomputeTick, setRecomputeTick] = useState(0);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const id = ++seq.current;
      setDim(true);
      try {
        const res = await api.post('/api/whatif', { date, mods });
        if (id !== seq.current) return;   // a newer request is in flight; its answer wins
        setW({ ...res, nMods: mods.length });
        setWerr(null);
      } catch (e: any) {
        if (id !== seq.current) return;
        setWerr(e.message);
      }
      setDim(false);
    }, 250);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [date, mods, recomputeTick]);

  const hourOf = (iso: string) => (minuteOf(iso, date) as number) / 60;
  const has = (id: string, op: string) => mods.some((m) => m.event_id === id && m.op === op);
  const toggleMod = (id: string, op: string, extra?: Partial<Mod>) => {
    setMods((cur) => (cur.some((m) => m.event_id === id && m.op === op) ? cur.filter((m) => !(m.event_id === id && m.op === op)) : [...cur.filter((m) => m.event_id !== id), { op, event_id: id, ...(extra || {}) }]));
  };
  const controlsFor = (ev: any) => {
    const ctl: React.ReactNode[] = [];
    const b = (label: string, op: string, extra?: Partial<Mod>) => ctl.push(
      <button key={op} className={'btn btn-sm' + (has(ev.id, op) ? ' active btn-primary' : '')} type="button" onClick={() => toggleMod(ev.id, op, extra)}>{label}</button>,
    );
    if (ev.type === 'meeting') { if (hourOf(ev.end) > 18) b('End at 18:00', 'end_at', { hour: 18 }); b('−2 h', 'shift', { hours: -2 }); b('→ Protected', 'to_protected'); }
    else if (ev.type === 'focus') { b('→ Protected', 'to_protected'); }
    else if (ev.type === 'workout') { if (hourOf(ev.start) >= 10) b('Move to 07:00', 'shift', { hours: 7 - hourOf(ev.start) }); }
    b('Remove', 'remove');
    return ctl;
  };
  const evs = day.events.filter((e: any) => e.attended !== false).slice().sort((a: any, b: any) => (a.start < b.start ? -1 : 1));

  const acceptSuggestion = async (s: any) => {
    try {
      await api.post('/api/suggestions/' + today + '/' + s.id + '/accept');
      setDay(await api.get('/api/day/' + date));
      setReport(await api.get('/api/report/' + today));
      setRecomputeTick((t) => t + 1);
      toast('Added to your calendar', { kind: 'success' });
    } catch (err: any) {
      toast(err.message, { kind: 'error' });
    }
  };

  return (
    <div className="v-planner-grid">
      <div className="stack">
        <div className={'card v-planner-hero' + (dim ? ' loading-dim' : '')} data-tour="prediction">
          <div className="eyebrow">Predicted change for this night</div>
          <div className={'v-planner-delta ' + (w && w.delta > 0 ? 'pts-pos' : w && w.delta < 0 ? 'pts-neg' : '')}>{!w ? '–' : w.nMods ? fmt.signed(w.delta, 0) : '±0'}</div>
          <div className="small secondary">
            {werr ? werr : !w ? '' : w.nMods && w.delta_low !== null ? 'likely ' + fmt.signed(w.delta_low, 0) + ' to ' + fmt.signed(w.delta_high, 0) + ' points' : 'Change the plan to see the effect'}
          </div>
          <div className="v-planner-pred">
            {w ? (
              <>
                <span className="muted small">Predicted sleep score </span>
                <strong>{fmt.score(w.baseline_pred)}</strong>
                {w.nMods ? <><span className="muted small"> → </span><strong>{fmt.score(w.modified_pred)}</strong></> : null}
                <span className="muted small">{' · typical error ±' + fmt.num(w.rmse, 0)}</span>
              </>
            ) : null}
          </div>
          <div className="row">{(w?.changed_factors || []).map((k: string) => <span key={k} className="chip">{FACTOR_LABEL[k] || k}</span>)}</div>
          <div className="tiny muted">From your own within-person model. Ranges come from resampling your nights; correlation, not proof.</div>
        </div>
        <div className="stack">
          {report && report.suggestions.length ? (
            <>
              <h4>Suggestions for tonight</h4>
              {report.suggestions.map((s: any) => (
                <div key={s.id} className="card soft v-planner-sugg">
                  <div className="row between"><strong>{s.title}</strong>{s.gain_low !== null && s.gain_low !== undefined ? <span className="chip pts pts-pos">{fmt.signed(s.gain_low, 0) + ' to ' + fmt.signed(s.gain_high, 0)}</span> : null}</div>
                  <p className="small secondary">{s.body}</p>
                  <div className="row">
                    {s.accepted ? <span className="row small v-planner-added"><Icon name="check" size={14} />Added</span>
                      : s.proposed_event ? <AcceptButton onAccept={() => acceptSuggestion(s)} />
                      : s.kind === 'move_meeting' ? (
                        <button className="btn btn-sm" type="button" onClick={() => {
                          const late = day.events.filter((e: any) => e.type === 'meeting' && hourOf(e.end) >= 19.5).sort((a: any, b: any) => (a.end < b.end ? 1 : -1))[0];
                          if (late) toggleMod(late.id, 'end_at', { hour: 18 });
                        }}>Try it</button>
                      ) : null}
                  </div>
                </div>
              ))}
            </>
          ) : null}
        </div>
      </div>
      <div className="card">
        <div className="card-title">
          <h3>{'The plan for ' + fmt.day(date)}</h3>
          <button className="btn btn-sm" type="button" disabled={!mods.length} onClick={() => setMods([])}><Icon name="refresh" size={14} />Undo changes</button>
        </div>
        <div className="stack" data-tour="events">
          {!evs.length ? <p className="muted">An empty day. Add nothing and sleep well.</p> : evs.map((ev: any) => (
            <div key={ev.id} className={'v-planner-event' + (has(ev.id, 'remove') ? ' removed' : '')}>
              <span className="v-planner-swatch" style={{ background: palette.event(ev.type) }}><Icon name={eventIcon(ev.type)} size={14} /></span>
              <div className="v-planner-event-body">
                <div className="row between">
                  <span className="v-planner-title">{ev.title}{ev.source === 'user' ? <span className="badge badge-accent" style={{ marginLeft: '8px' }}>added by you</span> : null}</span>
                  <span className="tiny muted tabular">{fmt.hm(ev.start) + '–' + fmt.hm(ev.end)}</span>
                </div>
                <div className="row v-planner-controls">{controlsFor(ev)}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="tiny muted" style={{ marginTop: '10px' }}>Change a block and watch the prediction move. Nothing here edits your real calendar until you accept a suggestion.</div>
      </div>
    </div>
  );
}

function AcceptButton({ onAccept }: { onAccept: () => Promise<void> }) {
  const [pending, setPending] = useState(false);
  return <button className="btn btn-sm btn-primary" type="button" disabled={pending} onClick={async () => { setPending(true); await onAccept(); setPending(false); }}>Add to calendar</button>;
}
