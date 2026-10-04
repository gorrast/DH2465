'use client';
import { useCallback, useEffect, useRef, useState, type DependencyList, type ReactNode } from 'react';
import { logClient } from '@/lib/api';
import { Icon } from '../ui/Icon';
import { useApp } from '../shell/AppContext';

/** Load data for a view; reruns when ``deps`` change. Stale responses are ignored. */
export function useLoad<T>(fn: () => Promise<T>, deps: DependencyList) {
  const [state, setState] = useState<{ data: T | null; error: Error | null; loading: boolean }>({ data: null, error: null, loading: true });
  const seq = useRef(0);
  const run = useCallback(() => {
    const id = ++seq.current;
    setState({ data: null, error: null, loading: true });
    fn().then(
      (data) => { if (id === seq.current) setState({ data, error: null, loading: false }); },
      (error) => { if (id === seq.current) setState({ data: null, error, loading: false }); },
    );
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { run(); }, [run]);
  return { ...state, reload: run, setData: (data: T) => setState({ data, error: null, loading: false }) };
}

export function ViewHead({ eyebrow, title, children }: { eyebrow: string; title: ReactNode; children?: ReactNode }) {
  return (
    <div className="view-head">
      <div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1></div>
      {children}
    </div>
  );
}

export function Skeleton({ height }: { height: number }) {
  return <div className="skeleton" style={{ height: height + 'px' }} />;
}

/** The generic failure card the original router showed when a view threw. */
export function ErrorCard({ error, onRetry, view }: { error: Error; onRetry: () => void; view: string }) {
  useEffect(() => { logClient('error', 'render ' + view + ': ' + (error && error.message), error); }, [error, view]);
  return (
    <div className="card error-card">
      <h2>Something went wrong</h2>
      <p>{String((error && error.message) || error)}</p>
      <button className="btn" onClick={onRetry}>Retry</button>
    </div>
  );
}

export function Chip({ children, icon }: { children: ReactNode; icon?: string }) {
  return <span className="chip">{icon ? <Icon name={icon} size={13} /> : null}{children}</span>;
}

export function DateNav({ label, prevHref, nextHref, prevDisabled, nextDisabled, extra }: {
  label: string; prevHref: string; nextHref: string; prevDisabled?: boolean; nextDisabled?: boolean; extra?: ReactNode;
}) {
  const { go } = useApp();
  return (
    <div className="date-nav">
      <button className="btn btn-icon btn-ghost" type="button" aria-label="Previous day" disabled={!!prevDisabled} onClick={() => go(prevHref)}><Icon name="chevron-left" /></button>
      <span className="date-label">{label}</span>
      <button className="btn btn-icon btn-ghost" type="button" aria-label="Next day" disabled={!!nextDisabled} onClick={() => go(nextHref)}><Icon name="chevron-right" /></button>
      {extra}
    </div>
  );
}
