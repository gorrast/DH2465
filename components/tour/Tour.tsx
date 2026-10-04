'use client';
/* Presenter tour: ten steps in pitch order, spotlighting the [data-tour] anchors the views render (SPEC §9.4). */
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from 'react';
import { dates } from '@/lib/format';
import type { ReplayControls, TourControls } from '../shell/AppContext';

interface Step { title: string; text: string; href: string; anchor: string; onEnter?: () => void }

function buildSteps(today: string, replay: MutableRefObject<ReplayControls | null>): Step[] {
  return [
    { title: 'A score. No why.', text: 'This is what a wearable gives you this morning: a number and a word. The watch knows how the night went — not what happened yesterday.', href: '/morning/' + today + '?reveal=1', anchor: 'watch-card' },
    { title: 'Why?', text: 'One click. StressLess matches the night to yesterday’s calendar, Maps history and heart rate, and names the three most likely causes — with evidence and a suggestion you can add to the calendar.', href: '/morning/' + today + '?reveal=1', anchor: 'causes', onEnter: () => { const b = document.querySelector<HTMLElement>('[data-tour="reveal"]'); if (b) b.click(); } },
    { title: 'The body rode the meetings', text: 'Watch the evening: after the late meeting the heart rate stays above the dotted line — your usual heart rate at that hour — until well past ten.', href: '/replay/' + dates.addDays(today, -1) + '?t=1020', anchor: 'timeline', onEnter: () => { setTimeout(() => { replay.current?.playRange(17 * 60, 23.5 * 60, 64); }, 400); } },
    { title: 'No logging. Only confirmations.', text: 'The watch saw a workout the calendar did not know about. Answer once, and the pattern updates in front of you.', href: '/reality', anchor: 'inbox' },
    { title: 'Patterns over weeks', text: 'Six weeks in: how meeting load, late finishes and evenings out relate to the sleep score — with sample sizes and intervals, not just averages.', href: '/week', anchor: 'buckets' },
    { title: 'Change tomorrow', text: 'End tonight’s late meeting at 18:00 and the predicted score moves, with a likely range. The block you accepted a minute ago is already in the plan.', href: '/planner/' + today, anchor: 'prediction' },
    { title: 'Same engine, different person', text: 'Open the persona menu and switch to Robin: different life, different first cause. The engine is the same; the person is not.', href: '/morning/' + today, anchor: 'persona' },
    { title: 'Under the hood', text: 'Because this is a simulation, we can check the engine against the truth we planted: rank agreement, out-of-sample skill, and a planted null factor to catch false alarms.', href: '/lab', anchor: 'validation' },
    { title: 'What the calendar can’t see', text: 'Alcohol, caffeine, screens, sleep debt, illness, unworn nights. The honest answer is on the screen, not hidden.', href: '/lab', anchor: 'challenges' },
    { title: 'The watch measures. The calendar explains.', text: 'Back to this morning: a score with a why, and one concrete change already on the calendar for tonight.', href: '/morning/' + today, anchor: 'suggestion' },
  ];
}

interface Props {
  today: string;
  go: (href: string) => void;
  setHistoryDays: (n: number | null) => void;
  replay: MutableRefObject<ReplayControls | null>;
}

export function useTour({ today, go, setHistoryDays, replay }: Props): { controls: TourControls; element: ReactNode } {
  const [idx, setIdx] = useState(-1);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [, setFrame] = useState(0);
  const activeRef = useRef(false);
  const idxRef = useRef(-1);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);
  const propsRef = useRef({ today, go, setHistoryDays, replay });
  propsRef.current = { today, go, setHistoryDays, replay };
  const steps = useCallback(() => buildSteps(propsRef.current.today, propsRef.current.replay), []);

  const paint = useCallback(() => {
    if (!activeRef.current) return;
    const s = steps()[idxRef.current];
    const target = s ? document.querySelector('[data-tour="' + s.anchor + '"]') : null;
    setRect(target ? target.getBoundingClientRect() : null);
    setFrame((f) => f + 1);
  }, [steps]);

  const goto = useCallback((i: number) => {
    const list = steps();
    const n = Math.max(0, Math.min(list.length - 1, i));
    idxRef.current = n;
    setIdx(n);
    const s = list[n];
    propsRef.current.setHistoryDays(null);
    if (location.pathname + location.search !== s.href) propsRef.current.go(s.href);
    if (poll.current) clearInterval(poll.current);
    let tries = 0;
    paint();
    poll.current = setInterval(() => {
      tries++;
      const target = document.querySelector('[data-tour="' + s.anchor + '"]');
      if (target || tries > 30) {
        if (poll.current) clearInterval(poll.current);
        poll.current = null;
        paint();
        if (target) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        setTimeout(paint, 450);
        if (s.onEnter) setTimeout(s.onEnter, 300);
      }
    }, 100);
  }, [steps, paint]);

  const stop = useCallback(() => {
    activeRef.current = false;
    idxRef.current = -1;
    setIdx(-1);
    if (poll.current) clearInterval(poll.current);
  }, []);
  const next = useCallback(() => { if (idxRef.current >= steps().length - 1) stop(); else goto(idxRef.current + 1); }, [steps, stop, goto]);
  const prev = useCallback(() => goto(idxRef.current - 1), [goto]);
  const start = useCallback(() => { if (activeRef.current) return; activeRef.current = true; goto(0); }, [goto]);

  useEffect(() => {
    if (idx < 0) return;
    const onKey = (e: KeyboardEvent) => {
      if (!activeRef.current) return;
      if (e.key === 'Escape') { e.preventDefault(); stop(); }
      else if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'Enter') { e.preventDefault(); next(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); prev(); }
    };
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('resize', paint);
    window.addEventListener('scroll', paint, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      window.removeEventListener('resize', paint);
      window.removeEventListener('scroll', paint, true);
    };
  }, [idx, stop, next, prev, paint]);

  useEffect(() => () => { if (poll.current) clearInterval(poll.current); }, []);

  const controls = useMemo<TourControls>(() => ({
    start, stop, toggle: () => (activeRef.current ? stop() : start()), active: () => activeRef.current,
  }), [start, stop]);

  let element: ReactNode = <div id="tour-root" />;
  if (idx >= 0) {
    const list = steps();
    const s = list[idx];
    const spotStyle = rect ? { left: rect.left - 8, top: rect.top - 8, width: rect.width + 16, height: rect.height + 16 } : undefined;
    let cardStyle: React.CSSProperties = { right: 24, bottom: 24 };
    if (rect) {
      const below = rect.bottom + 24;
      const left = Math.min(Math.max(16, rect.left), window.innerWidth - 440);
      if (below + 200 < window.innerHeight) cardStyle = { top: below, left };
      else if (rect.top - 220 > 0) cardStyle = { top: rect.top - 220, left };
    }
    element = (
      <div id="tour-root">
        <div className="tour-backdrop" />
        <div className={'tour-spot' + (rect ? '' : ' nospot')} style={spotStyle} />
        <div className="tour-card card raised" role="dialog" aria-label="Presenter tour" style={cardStyle}>
          <div className="eyebrow">{'Step ' + (idx + 1) + ' of ' + list.length}</div>
          <h3>{s.title}</h3>
          <p>{s.text}</p>
          <div className="row between">
            <div className="tour-dots">{list.map((_, i) => <span key={i} className={'tour-dot' + (i === idx ? ' on' : i < idx ? ' done' : '')} />)}</div>
            <div className="row">
              <button className="btn btn-sm btn-ghost" type="button" onClick={stop}>Exit</button>
              <button className="btn btn-sm" type="button" disabled={idx === 0} onClick={prev}>←</button>
              <button className="btn btn-sm btn-primary" type="button" onClick={next}>{idx === list.length - 1 ? 'Done' : 'Next →'}</button>
            </div>
          </div>
        </div>
      </div>
    );
  }
  return { controls, element };
}
