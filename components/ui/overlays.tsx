'use client';
/* App-wide overlays: chart tooltip, toasts, confirm modal and the busy stepper.
 * Each is driven by a tiny external store so callers (charts, views) can trigger them without re-rendering the tree. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createStore, useStore } from '@/lib/store';
import { Icon } from './Icon';

// ------------------------------------------------------------------ tooltip --
export interface TipRow { label: string; value: string; color?: string | null }
interface TipState { x: number; y: number; title: string | null; rows: TipRow[]; visible: boolean }
const tipStore = createStore<TipState>({ x: 0, y: 0, title: null, rows: [], visible: false });

export function showTip(x: number, y: number, title: string | null | undefined, rows: TipRow[]) {
  tipStore.set({ x, y, title: title || null, rows: rows || [], visible: true });
}
export function hideTip() {
  if (tipStore.get().visible) tipStore.set((s) => ({ ...s, visible: false }));
}

export function TooltipHost() {
  const tip = useStore(tipStore);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: 0, top: 0 });
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || !tip.visible) return;
    const pad = 12;
    const w = node.offsetWidth, h = node.offsetHeight;
    let left = tip.x + pad, top = tip.y + pad;
    if (left + w > window.innerWidth - 8) left = tip.x - w - pad;
    if (top + h > window.innerHeight - 8) top = tip.y - h - pad;
    setPos({ left, top });
  }, [tip]);
  return (
    <div ref={ref} className="viz-tooltip" hidden={!tip.visible} style={{ position: 'fixed', left: pos.left, top: pos.top }}>
      {tip.title ? <div className="tt-title">{tip.title}</div> : null}
      {tip.rows.map((r, i) => (
        <div className="tt-row" key={i}>
          <span className="row" style={{ gap: '6px' }}>
            {r.color ? <span className="tt-key" style={{ background: r.color }} /> : null}
            <span className="tt-label">{r.label}</span>
          </span>
          <span className="tt-value">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------- toasts --
export type ToastKind = 'info' | 'success' | 'error';
interface Toast { id: number; message: string; kind: ToastKind; show: boolean }
const toastStore = createStore<Toast[]>([]);
let toastSeq = 0;

export function toast(message: string, opts?: { kind?: ToastKind; duration?: number }) {
  const id = ++toastSeq;
  const kind = opts?.kind || 'info';
  toastStore.set((list) => [...list, { id, message, kind, show: false }]);
  const patch = (show: boolean) => toastStore.set((list) => list.map((t) => (t.id === id ? { ...t, show } : t)));
  setTimeout(() => patch(true), 10);
  setTimeout(() => {
    patch(false);
    setTimeout(() => toastStore.set((list) => list.filter((t) => t.id !== id)), 300);
  }, opts?.duration || 3200);
}

export function ToastHost() {
  const list = useStore(toastStore);
  return (
    <div id="toasts" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className={'toast toast-' + t.kind + (t.show ? ' show' : '')} role="status">
          <Icon name={t.kind === 'error' ? 'alert' : t.kind === 'success' ? 'check' : 'info'} size={16} />
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  );
}

// -------------------------------------------------------------------- modal --
export interface ConfirmOptions { title?: string; body?: string; confirmLabel?: string; cancelLabel?: string; danger?: boolean }
interface ModalState { opts: ConfirmOptions; resolve: (v: boolean) => void }
const modalStore = createStore<ModalState | null>(null);

export function confirmModal(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => modalStore.set({ opts, resolve }));
}

export function ModalHost() {
  const m = useStore(modalStore);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!m) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close(false);
      }
    };
    document.addEventListener('keydown', onKey);
    const t = setTimeout(() => confirmRef.current?.focus(), 20);
    return () => {
      document.removeEventListener('keydown', onKey);
      clearTimeout(t);
    };
  });
  if (!m) return null;
  const o = m.opts;
  function close(v: boolean) {
    modalStore.set(null);
    m!.resolve(v);
  }
  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) close(false); }}>
      <div className="modal card raised" role="dialog" aria-modal="true" aria-label={o.title || 'Confirm'}>
        <h3>{o.title || 'Are you sure?'}</h3>
        <p className="secondary">{o.body || ''}</p>
        <div className="row modal-actions">
          <button className="btn btn-ghost" type="button" onClick={() => close(false)}>{o.cancelLabel || 'Cancel'}</button>
          <button ref={confirmRef} className={'btn ' + (o.danger ? 'btn-danger' : 'btn-primary')} type="button" onClick={() => close(true)}>
            {o.confirmLabel || 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------- busy --
export interface BusyOptions { title?: string; steps?: string[]; stepMs?: number }
const busyStore = createStore<BusyOptions | null>(null);

export function busy(opts: BusyOptions | string | null) {
  busyStore.set(opts === null ? null : typeof opts === 'string' ? { title: opts } : opts);
}

export function BusyHost() {
  const b = useStore(busyStore);
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    setIdx(0);
    const steps = b?.steps || [];
    if (steps.length <= 1) return;
    const timer = setInterval(() => setIdx((i) => Math.min(i + 1, steps.length - 1)), b?.stepMs || 700);
    return () => clearInterval(timer);
  }, [b]);
  if (!b) return null;
  const steps = b.steps || [];
  return (
    <div className="busy-backdrop" role="status" aria-live="polite">
      <div className="busy card raised">
        <div className="row"><span className="spinner" /><h3 style={{ margin: 0 }}>{b.title || 'Working…'}</h3></div>
        {steps.length ? (
          <ol className="stepper">
            {steps.map((t, i) => (
              <li key={i} className={i === idx ? 'active' : i < idx ? 'done' : ''}><span className="step-dot" />{t}</li>
            ))}
          </ol>
        ) : null}
      </div>
    </div>
  );
}
