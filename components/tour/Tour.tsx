'use client';
/* Presenter tour: ten steps in pitch order, spotlighting the [data-tour] anchors the views render (SPEC §9.4). */
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from 'react';
import type { ReplayControls, TourControls } from '../shell/AppContext';

interface Step { title: string; text: string; href: string; anchor: string; onEnter?: () => void }

function buildSteps(today: string, replay: MutableRefObject<ReplayControls | null>): Step[] {
  return [
    { title: 'Your daily brief', text: 'Start with last night’s sleep score, then explore how your day may have shaped your night.', href: '/daily/' + today, anchor: 'watch-card' },
    { title: 'Connect the dots', text: 'Explore patterns from your calendar and heart rate. These are associations from your history, never certainties.', href: '/daily/' + today, anchor: 'causes' },
    { title: 'Confirm your activities', text: 'When the signals disagree, confirm or deny an activity. Your answers update the patterns behind your report.', href: '/daily/' + today + '#reality-check', anchor: 'inbox' },
    { title: 'Your weekly patterns', text: 'Weekly brings your statistics and sleep patterns together. Explore meeting load, recent nights and recurring activities.', href: '/weekly', anchor: 'buckets' },
    { title: 'Connect your world', text: 'Import your media exports or use optional sync. Each source has its own setup guide and works independently.', href: '/connect', anchor: 'connections' },
    { title: 'Your data, your choice', text: 'See what StressLess reads, why it is used, and how to delete your data. Account and appearance controls live in My Account.', href: '/data', anchor: 'privacy' },
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
