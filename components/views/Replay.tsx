'use client';
/* Replay view: the day as the watch saw it, against the calendar and Maps (SPEC §9.4). */
import Link from 'next/link';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { dates, fmt, minuteLabel, minuteOf } from '@/lib/format';
import { eventIcon } from '@/lib/icons';
import { palette } from '@/lib/palette';
import { Icon } from '../ui/Icon';
import { DayTimeline, valueAt } from '../charts/DayTimeline';
import { useApp } from '../shell/AppContext';
import { DateNav, Skeleton, ViewHead, useLoad } from './common';

export function ReplayView({ date, t }: { date?: string; t?: string }) {
  const { today, meta } = useApp();
  const d = date || dates.addDays(today, -1);
  const load = useLoad(() => api.get('/api/day/' + d), [d]);
  return (
    <>
      <ViewHead eyebrow="Replay" title={fmt.dayLong(d)}>
        <DateNav label={d === dates.addDays(today, -1) ? 'Yesterday' : fmt.day(d)}
          prevHref={'/replay/' + dates.addDays(d, -1)} nextHref={'/replay/' + dates.addDays(d, 1)}
          prevDisabled={!!meta.start && d <= meta.start} nextDisabled={d >= today} />
      </ViewHead>
      <div className="v-replay stack">
        {load.loading ? <Skeleton height={300} />
          : load.error || !load.data ? <div className="card empty"><h2>No data for this day</h2><p>{load.error?.message}</p></div>
          : <ReplayBody day={load.data} date={d} t={t} />}
      </div>
    </>
  );
}

function ReplayBody({ day, date, t }: { day: any; date: string; t?: string }) {
  const { replay } = useApp();
  const attended = useMemo(() => day.events.filter((e: any) => e.attended !== false), [day]);
  const firstEvent = attended.length ? Math.min(...attended.map((e: any) => minuteOf(e.start, date) as number)) : 6 * 60;
  const initial = t ? Math.max(0, Math.min(1439, +t)) : Math.max(0, Math.min(firstEvent - 30, 6 * 60));
  const [cursor, setCursor] = useState(initial);
  const [speed, setSpeedState] = useState(16);
  const [playing, setPlaying] = useState(false);
  const pos = useRef(initial);
  const speedRef = useRef(16);
  const playingRef = useRef(false);
  const raf = useRef<number | null>(null);
  const last = useRef<number | null>(null);
  const stopAt = useRef<number | null>(null);

  const seek = useCallback((m: number) => {
    pos.current = Math.max(0, Math.min(1439, m));
    setCursor(Math.round(pos.current));
  }, []);
  const pause = useCallback(() => {
    playingRef.current = false;
    stopAt.current = null;
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = null;
    setPlaying(false);
  }, []);
  const setSpeed = useCallback((sp: number) => { speedRef.current = sp; setSpeedState(sp); }, []);
  const tick = useCallback((ts: number) => {
    if (!playingRef.current) return;
    if (last.current !== null) {
      const next = pos.current + ((ts - last.current) / 1000) * speedRef.current;
      if (next >= 1439 || (stopAt.current !== null && next >= stopAt.current)) {
        seek(Math.min(1439, stopAt.current !== null ? stopAt.current : 1439));
        pause();
        return;
      }
      seek(next);
    }
    last.current = ts;
    raf.current = requestAnimationFrame(tick);
  }, [seek, pause]);
  const play = useCallback((sp?: number) => {
    if (sp) setSpeed(sp);
    playingRef.current = true;
    last.current = null;
    setPlaying(true);
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(tick);
  }, [setSpeed, tick]);

  useEffect(() => {
    replay.current = { play, pause, seek, playRange: (from, to, sp) => { seek(from); stopAt.current = to; play(sp); } };
    return () => { pause(); replay.current = null; };
  }, [replay, play, pause, seek]);

  const info = valueAt({ date, events: day.events, visits: day.visits, hr: day.hr, norm: day.norm }, cursor);
  const asleepNow = cursor < 6 * 60 || (day.night && day.night.worn && (minuteOf(day.night.in_bed_start, date) as number) <= cursor);
  const chapter = (label: string, fn: () => void) => <button className="btn btn-sm" type="button" onClick={fn}>{label}</button>;

  return (
    <>
      <div className="v-replay-grid">
        <div className={'card v-replay-facecard' + (playing && info.hr !== null && info.hr > 100 ? ' pulse' : '')} data-tour="watchface">
          <div className="v-replay-face">
            <div className="v-replay-face-time">{minuteLabel(cursor)}</div>
            <div className="row" style={{ alignItems: 'baseline', gap: '4px', justifyContent: 'center' }}>
              <Icon name="heart" size={16} className="v-replay-heart" />
              <div className="v-replay-face-hr">{info.hr === null ? '–' : String(info.hr)}</div>
              <span className="tiny muted">bpm</span>
            </div>
            <div className="v-replay-face-norm muted small">
              {info.hr !== null && info.norm !== null ? fmt.signed(info.hr - Math.round(info.norm), 0) + ' vs norm' : info.hr === null ? 'watch not worn' : ''}
            </div>
          </div>
          <div className="v-replay-face-event" style={{ color: info.event ? palette.event(info.event.type) : '' }}>
            {info.event ? <><Icon name={eventIcon(info.event.type)} size={14} /><span>{info.event.title}</span></> : <span className="muted">{asleepNow ? 'Asleep' : 'Free time'}</span>}
          </div>
          <div className="v-replay-face-place muted small">{info.place ? info.place.place_name : ''}</div>
        </div>
        <div className="card v-replay-main" data-tour="timeline">
          <div className="card-title"><h3>The day, minute by minute</h3><span className="row tiny muted">{day.chips.map((c: string, i: number) => <span key={i} className="chip">{c}</span>)}</span></div>
          <DayTimeline className="v-replay-timeline" date={date} events={day.events} visits={day.visits} hr={day.hr} norm={day.norm} night={day.night} nightPrev={day.night_prev} workouts={day.workouts} checks={day.checks} cursorMinute={cursor} onSeek={seek} />
          <div className="v-replay-scrub">
            <input type="range" min={0} max={1439} value={cursor} aria-label="Time of day" onChange={(e) => seek(+e.target.value)} />
          </div>
          <div className="row v-replay-transport" data-tour="transport">
            <button className="btn btn-primary" type="button" onClick={() => (playing ? pause() : play())}>
              <Icon name={playing ? 'pause' : 'play'} size={16} />{playing ? 'Pause' : 'Play'}
            </button>
            <div className="segmented">
              {[4, 16, 64].map((sp) => <button key={sp} type="button" className={sp === speed ? 'active' : ''} data-speed={sp} onClick={() => setSpeed(sp)}>{sp + 'x'}</button>)}
            </div>
            {chapter('Next event', () => { const nxt = attended.map((e: any) => minuteOf(e.start, date) as number).filter((m: number) => m > cursor + 1).sort((a: number, b: number) => a - b)[0]; if (nxt !== undefined) seek(Math.max(0, nxt - 15)); })}
            {chapter('Evening', () => seek(17 * 60))}
            {chapter('Bedtime', () => { const b = day.night && day.night.worn ? (minuteOf(day.night.in_bed_start, date) as number) : 23 * 60; seek(Math.max(0, Math.min(1439, b - 20))); })}
            <span className="tiny muted">minutes per second</span>
          </div>
          <div className="tiny muted">Coral line: heart rate. Dotted: your usual heart rate at that hour on calm evenings. Shaded: above your norm. Blue shading: asleep. Dashed outline: booked but not attended.</div>
        </div>
      </div>
      <DaySide day={day} date={date} seek={seek} />
    </>
  );
}

/** Events with the body's response, and the night after. Memoized: playback only moves the cursor. */
const DaySide = memo(function DaySide({ day, date, seek }: { day: any; date: string; seek: (m: number) => void }) {
  const checksByEvent: Record<string, any> = {};
  day.checks.forEach((c: any) => { if (c.event_id) checksByEvent[c.event_id] = c; });
  const n = day.night;
  const evening = day.evening;
  return (
    <div className="grid grid-3">
      <div className="card span-2">
        <div className="card-title"><h3>Calendar vs body</h3><span className="tiny muted">click an event to jump there</span></div>
        <ul className="list v-replay-events">
          {day.events.map((ev: any) => {
            const r = day.responses[ev.id];
            const chk = checksByEvent[ev.id];
            return (
              <li key={ev.id} className={'list-item v-replay-event' + (ev.attended === false ? ' unattended' : '')} onClick={() => seek(Math.max(0, (minuteOf(ev.start, date) as number) - 5))}>
                <span className="v-replay-evt-swatch" style={{ background: palette.event(ev.type) }}><Icon name={eventIcon(ev.type)} size={14} /></span>
                <div className="body">
                  <div className="row between"><span className="title">{ev.title}</span><span className="tiny muted tabular">{fmt.hm(ev.start) + '–' + fmt.hm(ev.end)}</span></div>
                  <div className="row tiny">
                    {ev.attended === false ? <span className="badge badge-critical">not attended</span> : null}
                    {ev.source === 'user' ? <span className="badge badge-accent">added by you</span> : null}
                    {r && r.delta_during !== null && r.delta_during !== undefined ? <span className="chip">{fmt.signed(r.delta_during, 0) + ' bpm during'}</span> : null}
                    {r && r.elevated_until ? <span className="chip">{'elevated until ' + fmt.hm(r.elevated_until)}</span> : null}
                    {chk ? <Link className={'badge badge-' + (chk.status === 'open' ? 'warning' : chk.status === 'no' ? 'critical' : 'good')} href="/reality" onClick={(e) => e.stopPropagation()}>{chk.status === 'open' ? 'reality check' : 'checked: ' + chk.status}</Link> : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
      <div className="stack">
        <div className="card v-replay-night">
          <div className="card-title"><h3>The night after</h3><Link className="small" href={'/morning/' + dates.addDays(date, 1)}>Explain this night →</Link></div>
          {n && n.worn ? (
            <div className="row">
              <span className="chip">{'Score ' + n.score}</span>
              <span className="chip">{'In bed ' + fmt.hm(n.in_bed_start)}</span>
              <span className="chip">{'Asleep ' + fmt.minutes(n.duration_min)}</span>
              <span className="chip">{'HRV ' + fmt.num(n.hrv_ms, 0) + ' ms'}</span>
              <span className="chip">{'RHR ' + n.resting_hr + ' bpm'}</span>
            </div>
          ) : <p className="muted small">{day.is_today ? 'Tonight has not happened yet.' : 'The watch was not worn this night.'}</p>}
        </div>
        {evening && evening.delta !== null && evening.delta !== undefined ? (
          <div className="card soft">
            <h4>Evening, 20:00–23:00</h4>
            <p className="small">{'Heart rate ' + fmt.signed(evening.delta, 0) + ' bpm vs your calm-evening norm' + (evening.elevated_until ? ', elevated until ' + fmt.hm(evening.elevated_until) : '') + '.'}</p>
          </div>
        ) : null}
      </div>
    </div>
  );
});
