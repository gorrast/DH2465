'use client';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useApp } from '../shell/AppContext';
import { cssVar } from '@/lib/palette';
import { hideTip } from '../ui/overlays';

export { cssVar };

export function niceTicks(lo: number, hi: number, n: number): number[] {
  if (!(hi > lo)) return [lo];
  const span = hi - lo, raw = span / Math.max(1, n);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const start = Math.ceil(lo / step) * step;
  const out: number[] = [];
  for (let v = start; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

export const isVal = (v: unknown): v is number => v !== null && v !== undefined;

export const bandColor = (band: string) =>
  ({ good: cssVar('--status-good'), warning: cssVar('--status-warning'), serious: cssVar('--status-serious'), critical: cssVar('--status-critical') } as Record<string, string>)[band] || cssVar('--ink-muted');

/** Width of the chart container (tracks resizes), like the original clientWidth-based rendering. */
export function useWidth(fallback: number, fixed?: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState<number>(fixed || fallback);
  useLayoutEffect(() => {
    if (fixed) return;
    const node = ref.current;
    if (!node) return;
    const measure = () => setW(Math.max(160, node.clientWidth || fallback));
    measure();
    const ro = new ResizeObserver(() => requestAnimationFrame(measure));
    ro.observe(node);
    return () => ro.disconnect();
  }, [fallback, fixed]);
  useEffect(() => () => hideTip(), []);
  return [ref, fixed || w] as const;
}

/** Re-render charts when the theme flips: their colours are read from CSS tokens at render time. */
export function useThemeKey() {
  return useApp().theme;
}
