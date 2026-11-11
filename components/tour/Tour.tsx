'use client';
/* Presenter tour: one morning, then one week, then the wider picture. Each step spotlights a [data-tour] anchor that
 * the views render; a step lists fallbacks in order, and the first one on the page wins (so "Generate" turns into
 * "the report" as soon as the visitor presses it). */
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import type { ReplayControls, TourControls } from '../shell/AppContext';

interface Target { anchor: string; title?: string; text?: string }
interface Step {
  chapter: number;              // index into CHAPTERS; -1 for the opening and closing cards
  title: string;
  text: string;
  href: (today: string) => string;
  targets: Target[];
}

const CHAPTERS = ['The morning', 'The week', 'Your world'];
const daily = (today: string) => '/daily/' + today;

const STEPS: Step[] = [
  {
    chapter: -1, href: daily, targets: [],
    title: 'Your watch measures. Your calendar explains.',
    text: 'Wearables tell you how you slept, never why. StressLess lines up each night with the day before it, from meetings and heart rate to phone use and music, and turns what repeats into one change you can make. Follow one morning, then one week.',
  },
  {
    chapter: 0, href: daily, targets: [{ anchor: 'watch-card' }, { anchor: 'hero' }],
    title: 'It starts with a number',
    text: 'Every morning opens with last night’s sleep score from the watch. On its own it says how you slept. Everything that follows explains why.',
  },
  {
    chapter: 0, href: daily,
    targets: [
      { anchor: 'daily-report', title: 'The story behind the score', text: 'Today’s report, written by Claude: what last night looked like, which parts of yesterday most likely shaped it, and the evidence behind each link.' },
      { anchor: 'generate' },
    ],
    title: 'Ask what lies behind it',
    text: 'One press of Generate writes today’s report. Claude reads a summary of the night and the day before and links the score to what happened. Try it now; the tour follows.',
  },
  {
    chapter: 0, href: daily, targets: [{ anchor: 'timeline' }],
    title: 'Heart rate meets the calendar',
    text: 'Yesterday’s heart rate, drawn under the events in the calendar. This is the core idea: the watch measures the strain, the calendar names it.',
  },
  {
    chapter: 0, href: daily, targets: [{ anchor: 'causes' }],
    title: 'Days like this one',
    text: 'StressLess finds earlier days that looked like yesterday and compares the nights that followed. These are associations from your own history, never diagnoses.',
  },
  {
    chapter: 0, href: daily, targets: [{ anchor: 'reality' }, { anchor: 'inbox' }],
    title: 'When the signals disagree',
    text: 'If the calendar says workout but the heart rate stayed flat, StressLess asks whether it really happened. Each answer sharpens the patterns. Answers are not saved in this demo.',
  },
  {
    chapter: 0, href: daily, targets: [{ anchor: 'tonight' }, { anchor: 'suggestion' }],
    title: 'One thing to try',
    text: 'Every report ends with a single, concrete change for tonight, ready to drop into the calendar. One step at a time, not a list of rules.',
  },
  {
    chapter: 1, href: () => '/weekly', targets: [{ anchor: 'weekly-report' }],
    title: 'Zoom out to the week',
    text: 'The weekly report ties seven nights together: the patterns that stood out, the best and hardest days, and one suggestion for the week ahead.',
  },
  {
    chapter: 1, href: () => '/weekly', targets: [{ anchor: 'buckets' }, { anchor: 'patterns' }],
    title: 'What a full calendar costs',
    text: 'Average sleep score by meeting load over recent weeks. The whiskers show how certain each estimate is, so it is clear which differences are real.',
  },
  {
    chapter: 2, href: () => '/social', targets: [{ anchor: 'social' }],
    title: 'Better together, by choice',
    text: 'Opt in to compare sleep, phone use and movement with friends or colleagues. Everyone is measured against their own baseline, not against each other.',
  },
  {
    chapter: 2, href: () => '/connect', targets: [{ anchor: 'connections' }],
    title: 'Everything that shapes a day',
    text: 'Calendar, watch, phone, and the music, shows and games behind the evenings. The demo account comes filled in; in your own account you import or sync them here.',
  },
  {
    chapter: 2, href: () => '/data', targets: [{ anchor: 'privacy' }],
    title: 'Your data, your choice',
    text: 'See exactly what StressLess reads and why it is used, and delete all of it with one action.',
  },
  {
    chapter: -1, href: daily, targets: [],
    title: 'From one number to one change',
    text: 'That is StressLess: the watch measures, the calendar explains, and every morning ends with something you can do about it. The demo is yours to explore. Press T to take the tour again.',
  },
];

const SPOT_PAD = 10;
const EDGE = 16;
const GAP = 20;
const CARD_W = 400;
const OPEN_W = 520;

interface Layout {
  spot: { x: number; y: number; w: number; h: number } | null;
  card: { x: number; y: number };
  docked: boolean;
  target: Target | null;
}

function findTarget(step: Step): { target: Target; el: Element } | null {
  for (const target of step.targets) {
    const el = document.querySelector('[data-tour="' + target.anchor + '"]');
    if (el) return { target, el };
  }
  return null;
}

// Where the spotlight and the card go: the card sits beside the spotlight if there is room, else below or above it,
// else it docks in the bottom corner (big sections fill the screen). Phones always dock it along the bottom.
function layout(step: Step, cardH: number): Layout {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const opener = step.chapter < 0;
  const w = Math.min(opener ? OPEN_W : CARD_W, vw - EDGE * 2);
  const centered = { x: (vw - w) / 2, y: Math.max(EDGE, (vh - cardH) / 2) };
  if (opener) return { spot: null, card: centered, docked: false, target: null };

  const found = findTarget(step);
  const r = found?.el.getBoundingClientRect();
  const top = Math.max(r ? r.top - SPOT_PAD : 0, 8);
  const bottom = Math.min(r ? r.bottom + SPOT_PAD : 0, vh - 8);
  const spot = r && r.width > 0 && bottom - top > 24
    ? { x: r.left - SPOT_PAD, y: top, w: r.width + SPOT_PAD * 2, h: bottom - top }
    : null;
  const target = found?.target ?? null;
  const dock = { x: vw - w - 24, y: vh - cardH - 24 };
  if (vw < 640) return { spot, card: { x: EDGE, y: vh - cardH - 12 }, docked: true, target };
  if (!spot) return { spot, card: found ? dock : centered, docked: !!found, target };

  const clampY = (y: number) => Math.min(Math.max(EDGE, y), vh - cardH - EDGE);
  const clampX = (x: number) => Math.min(Math.max(EDGE, x), vw - w - EDGE);
  if (spot.x + spot.w + GAP + w <= vw - EDGE) return { spot, card: { x: spot.x + spot.w + GAP, y: clampY(spot.y) }, docked: false, target };
  if (spot.x - GAP - w >= EDGE) return { spot, card: { x: spot.x - GAP - w, y: clampY(spot.y) }, docked: false, target };
  if (spot.y + spot.h + GAP + cardH <= vh - EDGE) return { spot, card: { x: clampX(spot.x), y: spot.y + spot.h + GAP }, docked: false, target };
  if (spot.y - GAP - cardH >= EDGE) return { spot, card: { x: clampX(spot.x), y: spot.y - GAP - cardH }, docked: false, target };
  return { spot, card: dock, docked: true, target };
}

interface Props {
  today: string;
  go: (href: string) => void;
  setHistoryDays: (n: number | null) => void;
  replay: MutableRefObject<ReplayControls | null>;
}

export function useTour({ today, go, setHistoryDays }: Props): { controls: TourControls; element: ReactNode } {
  const [idx, setIdx] = useState(-1);
  const [view, setView] = useState<Layout | null>(null);
  const reduced = !!useReducedMotion();
  const activeRef = useRef(false);
  const idxRef = useRef(-1);
  const cardRef = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const scrolledTo = useRef<string | null>(null);
  const propsRef = useRef({ today, go, setHistoryDays });
  propsRef.current = { today, go, setHistoryDays };

  // Measure and place, at most once a frame. When a step's target first appears (or changes), bring it into view.
  const paint = useCallback(() => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      if (!activeRef.current) return;
      const step = STEPS[idxRef.current];
      if (!step) return;
      const found = findTarget(step);
      const key = idxRef.current + ':' + (found?.target.anchor ?? '');
      if (found && scrolledTo.current !== key) {
        scrolledTo.current = key;
        const r = found.el.getBoundingClientRect();
        const tall = r.height > window.innerHeight * 0.6;
        found.el.scrollIntoView({ block: tall ? 'start' : 'center', behavior: reduced ? 'auto' : 'smooth' });
      }
      setView(layout(step, cardRef.current?.offsetHeight ?? 240));
    });
  }, [reduced]);

  const goto = useCallback((i: number) => {
    const n = Math.max(0, Math.min(STEPS.length - 1, i));
    idxRef.current = n;
    scrolledTo.current = null;
    setIdx(n);
    const href = STEPS[n].href(propsRef.current.today);
    propsRef.current.setHistoryDays(null);
    if (location.pathname !== href) propsRef.current.go(href);
    else if (STEPS[n].chapter < 0) window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' });
    paint();
  }, [paint, reduced]);

  const stop = useCallback(() => {
    activeRef.current = false;
    idxRef.current = -1;
    setIdx(-1);
    setView(null);
  }, []);
  const next = useCallback(() => { if (idxRef.current >= STEPS.length - 1) stop(); else goto(idxRef.current + 1); }, [stop, goto]);
  const prev = useCallback(() => goto(idxRef.current - 1), [goto]);
  const start = useCallback(() => { if (activeRef.current) return; activeRef.current = true; goto(0); }, [goto]);

  useEffect(() => {
    if (idx < 0) return;
    const onKey = (e: KeyboardEvent) => {
      if (!activeRef.current) return;
      const typing = (e.target as HTMLElement | null)?.closest('input, textarea, select, [contenteditable="true"]');
      if (e.key === 'Escape') { e.preventDefault(); stop(); }
      else if (typing) return;
      else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); next(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); prev(); }
    };
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('resize', paint);
    window.addEventListener('scroll', paint, true);
    // pages load their data after navigating, and sections grow as they reveal: keep re-measuring while open
    const tick = setInterval(paint, 250);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      window.removeEventListener('resize', paint);
      window.removeEventListener('scroll', paint, true);
      clearInterval(tick);
    };
  }, [idx, stop, next, prev, paint]);

  useEffect(() => () => { if (frame.current) cancelAnimationFrame(frame.current); }, []);

  const controls = useMemo<TourControls>(() => ({
    start, stop, toggle: () => (activeRef.current ? stop() : start()), active: () => activeRef.current,
  }), [start, stop]);

  if (idx < 0) return { controls, element: <div id="tour-root" /> };

  const step = STEPS[idx];
  const opener = step.chapter < 0;
  const title = view?.target?.title ?? step.title;
  const text = view?.target?.text ?? step.text;
  const spot = view?.spot ?? null;
  const card = view?.card ?? { x: (window.innerWidth - CARD_W) / 2, y: window.innerHeight / 3 };
  const glide = reduced ? { duration: 0 } : { type: 'spring' as const, stiffness: 210, damping: 30, mass: 0.9 };
  const fade = reduced ? { duration: 0 } : { duration: 0.28, ease: [0.22, 1, 0.36, 1] as const };
  // the spotlight shrinks to a point at the middle of the screen when there is nothing to show
  const hole = spot ?? { x: window.innerWidth / 2, y: window.innerHeight / 2, w: 0, h: 0 };
  const total = STEPS.length - 2;

  const element = (
    <div id="tour-root">
      <motion.div
        className={'tour-spot' + (spot ? '' : ' is-empty')}
        initial={false}
        animate={{ x: hole.x, y: hole.y, width: hole.w, height: hole.h, opacity: 1 }}
        transition={glide}
        aria-hidden="true"
      />
      <motion.div
        ref={cardRef}
        className={'tour-card' + (opener ? ' is-opener' : '') + (view?.docked ? ' is-docked' : '')}
        role="dialog"
        aria-modal="false"
        aria-labelledby="tour-title"
        aria-describedby="tour-text"
        initial={{ x: card.x, y: card.y + 12, opacity: 0 }}
        animate={{ x: card.x, y: card.y, opacity: 1 }}
        transition={glide}
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={idx + ':' + title}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={fade}
          >
            {opener ? (
              <div className="tour-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6" /></svg>
              </div>
            ) : null}
            <div className="tour-meta">
              <span className="tour-chapter">
                {opener ? (idx === 0 ? 'A two-minute tour' : 'The end of the tour') : 'Chapter ' + (step.chapter + 1) + ' · ' + CHAPTERS[step.chapter]}
              </span>
              {opener ? null : <span className="tour-count">{idx + ' / ' + total}</span>}
            </div>
            <h3 id="tour-title">{title}</h3>
            <p id="tour-text">{text}</p>
          </motion.div>
        </AnimatePresence>
        {opener ? null : (
          <div className="tour-progress" aria-hidden="true">
            {CHAPTERS.map((name, c) => (
              <div className="tour-progress-chapter" key={name}>
                {STEPS.map((s, i) => s.chapter === c ? (
                  <span key={i} className={'tour-progress-step' + (i <= idx ? ' is-done' : '')} />
                ) : null)}
              </div>
            ))}
          </div>
        )}
        <div className="tour-actions">
          {idx === 0 ? (
            <button className="btn btn-sm btn-ghost" type="button" onClick={stop}>Not now</button>
          ) : idx === STEPS.length - 1 ? (
            <button className="btn btn-sm btn-ghost" type="button" onClick={() => goto(0)}>Start over</button>
          ) : (
            <span className="tour-keys"><kbd>←</kbd><kbd>→</kbd> to move · <kbd>Esc</kbd> to close</span>
          )}
          <div className="tour-buttons">
            {idx > 0 && idx < STEPS.length - 1 ? (
              <button className="btn btn-sm btn-ghost" type="button" onClick={prev} aria-label="Previous step">Back</button>
            ) : null}
            <button className="btn btn-sm btn-primary" type="button" onClick={next} autoFocus>
              {idx === 0 ? 'Start the tour' : idx === STEPS.length - 1 ? 'Explore the demo' : 'Next'}
            </button>
          </div>
        </div>
        {opener || idx === STEPS.length - 1 ? null : (
          <button className="tour-close" type="button" onClick={stop} aria-label="Close the tour">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        )}
      </motion.div>
    </div>
  );
  return { controls, element };
}
