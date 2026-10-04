'use client';
/* Small charts: score ring, sparkline, bars, sleep stages and the data table (ported from charts.js). */
import { useRef, useState } from 'react';
import { fmt, bandFor, minuteOf, minuteLabel } from '@/lib/format';
import { showTip, hideTip, type TipRow } from '../ui/overlays';
import { bandColor, cssVar, isVal, niceTicks, useThemeKey, useWidth } from './common';

// ---------------------------------------------------------------------- ring
export function Ring({ value, max = 100, label, sublabel, band, size = 180 }: { value: number | null | undefined; max?: number; label?: string; sublabel?: string | null; band?: string; size?: number }) {
  useThemeKey();
  const sw = Math.max(8, size * 0.075), r = (size - sw) / 2, c = size / 2, circ = 2 * Math.PI * r;
  const frac = !isVal(value) ? 0 : Math.max(0, Math.min(1, value / (max || 100)));
  const color = bandColor(band || bandFor(value));
  return (
    <svg className="c-ring" viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label={(label || 'score') + ' ' + fmt.score(value)}>
      <circle cx={c} cy={c} r={r} fill="none" stroke={cssVar('--card-3')} strokeWidth={sw} />
      {frac > 0 ? <circle cx={c} cy={c} r={r} fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeDasharray={`${circ * frac} ${circ}`} transform={`rotate(-90 ${c} ${c})`} className="c-ring-arc" /> : null}
      <text x={c} y={c + (label ? -2 : 8)} textAnchor="middle" className="c-ring-value" style={{ fontSize: size * 0.3 + 'px' }}>{fmt.score(value)}</text>
      {label ? <text x={c} y={c + size * 0.13} textAnchor="middle" className="c-ring-label">{label}</text> : null}
      {sublabel ? <text x={c} y={c + size * 0.23} textAnchor="middle" className="c-ring-sub">{sublabel}</text> : null}
    </svg>
  );
}

// ----------------------------------------------------------------- sparkline
interface SparkProps {
  className?: string; values: (number | null)[]; norm?: (number | null)[] | null; baseline?: number | null; width?: number; height?: number;
  color?: string; label?: string; unit?: string; digits?: number; xLabels?: string[]; start?: string; stepMin?: number;
}
export function Sparkline(o: SparkProps) {
  useThemeKey();
  const [ref, W] = useWidth(320, o.width);
  const [cursor, setCursor] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const H = o.height || 56, padY = 4;
  const vals = o.values || [];
  const norm = o.norm || null;
  const all = (vals as (number | null | undefined)[]).concat(norm || []).concat(isVal(o.baseline) ? [o.baseline] : []).filter(isVal);
  if (!vals.length || !all.length) return <div ref={ref} className={o.className}><div className="c-empty tiny muted">No data</div></div>;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1e-9) { hi = lo + 1; lo = lo - 1; }
  const padV = (hi - lo) * 0.1; lo -= padV; hi += padV;
  const x = (i: number) => (vals.length > 1 ? (i / (vals.length - 1)) * W : W / 2);
  const y = (v: number) => H - padY - ((v - lo) / (hi - lo)) * (H - 2 * padY);
  const color = o.color || cssVar('--series-1');
  let fill = '', normPath = '';
  if (norm) {
    let d = '';
    vals.forEach((v, i) => { const nv = norm[i]; if (v !== null && isVal(nv)) d += (d ? ' L' : 'M') + x(i) + ' ' + y(Math.max(v, nv + 3)); });
    let back = '';
    for (let i = vals.length - 1; i >= 0; i--) { const nv = norm[i]; if (vals[i] !== null && isVal(nv)) back += ' L' + x(i) + ' ' + y(nv + 3); }
    if (d) fill = d + back + ' Z';
    norm.forEach((v, i) => { if (isVal(v)) normPath += (normPath ? ' L' : 'M') + x(i) + ' ' + y(v); });
  }
  let line = ''; let pen = false;
  vals.forEach((v, i) => { if (!isVal(v)) { pen = false; return; } line += (pen ? ' L' : ' M') + x(i) + ' ' + y(v); pen = true; });
  let lastIdx = -1; vals.forEach((v, i) => { if (isVal(v)) lastIdx = i; });
  const onMove = (e: React.PointerEvent) => {
    const b = svgRef.current!.getBoundingClientRect();
    const i = Math.max(0, Math.min(vals.length - 1, Math.round(((e.clientX - b.left) / b.width) * (vals.length - 1))));
    setCursor(i);
    const rows: TipRow[] = [{ label: o.label || 'value', value: vals[i] === null ? '–' : fmt.num(vals[i], o.digits || 0) + (o.unit ? ' ' + o.unit : ''), color }];
    if (norm && isVal(norm[i])) rows.push({ label: 'your norm', value: fmt.num(norm[i], 0) + (o.unit ? ' ' + o.unit : ''), color: cssVar('--ink-muted') });
    let title: string | null = o.xLabels ? o.xLabels[i] : null;
    if (!title && o.start) title = minuteLabel((minuteOf(o.start) || 0) + i * (o.stepMin || 5));
    showTip(e.clientX, e.clientY, title, rows);
  };
  return (
    <div ref={ref} className={o.className}>
      <svg ref={svgRef} className="c-spark" viewBox={`0 0 ${W} ${H}`} width={W} height={H} preserveAspectRatio="none">
        {fill ? <path d={fill} fill={cssVar('--div-worse')} opacity={0.12} /> : null}
        {normPath ? <path d={normPath} fill="none" stroke={cssVar('--ink-muted')} strokeWidth={1.5} strokeDasharray="3 3" /> : null}
        {isVal(o.baseline) ? <line x1={0} x2={W} y1={y(o.baseline)} y2={y(o.baseline)} stroke={cssVar('--ink-muted')} strokeWidth={1} strokeDasharray="3 3" /> : null}
        <path d={line.trim()} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {lastIdx >= 0 ? <circle cx={x(lastIdx)} cy={y(vals[lastIdx] as number)} r={4} fill={color} stroke={cssVar('--card')} strokeWidth={2} /> : null}
        <line x1={cursor === null ? 0 : x(cursor)} x2={cursor === null ? 0 : x(cursor)} y1={0} y2={H} stroke={cssVar('--hairline-strong')} strokeWidth={1} opacity={cursor === null ? 0 : 1} />
        <rect x={0} y={0} width={W} height={H} fill="transparent" onPointerMove={onMove} onPointerLeave={() => { setCursor(null); hideTip(); }} />
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------- bars
export interface BarItem { label: string; value: number | null; n?: number; lo?: number | null; hi?: number | null }
export function Bars(o: { className?: string; items: BarItem[]; width?: number; height?: number; max?: number; color?: string; unit?: string; ariaLabel?: string; formatValue?: (v: number) => string }) {
  useThemeKey();
  const [ref, W] = useWidth(480, o.width);
  const items = o.items || [];
  const H = o.height || 240;
  const padL = 36, padR = 12, padT = 26, padB = 44;
  const max = o.max || Math.max(100, ...items.map((i) => i.hi || i.value || 0));
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const y = (v: number) => padT + plotH - (v / max) * plotH;
  const slot = plotW / Math.max(1, items.length);
  const bw = Math.min(24, slot * 0.5);
  const color = o.color || cssVar('--series-1');
  const formatValue = o.formatValue || ((v: number) => fmt.num(v, 0));
  return (
    <div ref={ref} className={o.className}>
      <svg className="c-bars" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={o.ariaLabel || 'bar chart'}>
        {niceTicks(0, max, 4).map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke={cssVar('--grid')} strokeWidth={1} />
            <text x={padL - 8} y={y(t) + 4} textAnchor="end" className="c-axis tabular">{String(t)}</text>
          </g>
        ))}
        {items.map((it, i) => {
          const cx = padL + slot * (i + 0.5);
          let body = null;
          if (!isVal(it.value)) {
            body = <text x={cx} y={y(0) - 8} textAnchor="middle" className="c-label muted">no days</text>;
          } else {
            const top = y(it.value), h = Math.max(2, y(0) - top);
            const r = Math.min(4, h / 2);
            const d = `M${cx - bw / 2} ${y(0)} V${top + r} Q${cx - bw / 2} ${top} ${cx - bw / 2 + r} ${top} H${cx + bw / 2 - r} Q${cx + bw / 2} ${top} ${cx + bw / 2} ${top + r} V${y(0)} Z`;
            const hasRange = isVal(it.lo) && isVal(it.hi);
            const tip = (e: React.PointerEvent) => showTip(e.clientX, e.clientY, it.label, ([{ label: o.unit || 'value', value: fmt.num(it.value, 1), color }] as TipRow[])
              .concat(it.n !== undefined ? [{ label: 'nights', value: String(it.n) }] : [])
              .concat(isVal(it.lo) ? [{ label: '95 % range', value: fmt.num(it.lo, 0) + '–' + fmt.num(it.hi, 0) }] : []));
            body = (
              <>
                <path d={d} fill={color} className="c-bar" onPointerMove={tip} onPointerLeave={hideTip} />
                {hasRange ? (
                  <>
                    <line x1={cx} x2={cx} y1={y(it.hi!)} y2={y(it.lo!)} stroke={cssVar('--ink-secondary')} strokeWidth={1.5} />
                    <line x1={cx - 5} x2={cx + 5} y1={y(it.hi!)} y2={y(it.hi!)} stroke={cssVar('--ink-secondary')} strokeWidth={1.5} />
                    <line x1={cx - 5} x2={cx + 5} y1={y(it.lo!)} y2={y(it.lo!)} stroke={cssVar('--ink-secondary')} strokeWidth={1.5} />
                  </>
                ) : null}
                <text x={cx} y={Math.min(top, isVal(it.hi) ? y(it.hi) : top) - 8} textAnchor="middle" className="c-value">{formatValue(it.value)}</text>
              </>
            );
          }
          return (
            <g key={i}>
              {body}
              <text x={cx} y={H - padB + 18} textAnchor="middle" className="c-label">{it.label}</text>
              {it.n !== undefined ? <text x={cx} y={H - padB + 34} textAnchor="middle" className="c-axis">{'n = ' + it.n}</text> : null}
            </g>
          );
        })}
        <line x1={padL} x2={W - padR} y1={y(0)} y2={y(0)} stroke={cssVar('--axis')} strokeWidth={1} />
      </svg>
    </div>
  );
}

// -------------------------------------------------------------------- stages
const KIND_COLOR: Record<string, string> = { deep: '--sleep-deep', core: '--sleep-core', rem: '--sleep-rem', awake: '--sleep-awake' };
export function Stages({ className, night, width }: { className?: string; night: any; width?: number }) {
  useThemeKey();
  const [ref, W] = useWidth(480, width);
  if (!night || !night.worn || !night.stages || !night.stages.length) return <div ref={ref} className={className}><div className="c-empty muted small">No stage data</div></div>;
  const H = 34;
  const t0 = new Date(night.stages[0].start).getTime(), t1 = new Date(night.stages[night.stages.length - 1].end).getTime();
  const x = (t: number) => ((t - t0) / Math.max(1, t1 - t0)) * W;
  return (
    <div ref={ref} className={className}>
      <svg className="c-stages" viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
        {night.stages.map((st: any, i: number) => {
          const a = new Date(st.start).getTime(), b = new Date(st.end).getTime();
          return (
            <rect key={i} x={x(a) + 1} y={4} width={Math.max(1, x(b) - x(a) - 2)} height={24} rx={3} fill={cssVar(KIND_COLOR[st.kind] || '--ink-muted')}
              onPointerMove={(e) => showTip(e.clientX, e.clientY, fmt.hm(st.start) + '–' + fmt.hm(st.end), [{ label: st.kind, value: fmt.minutes((b - a) / 60000), color: cssVar(KIND_COLOR[st.kind]) }])}
              onPointerLeave={hideTip} />
          );
        })}
      </svg>
      <div className="c-legend">
        {([['deep', night.deep_min], ['core', night.core_min], ['rem', night.rem_min], ['awake', night.awake_min]] as [string, number][]).map(([k, m]) => (
          <span key={k} className="c-legend-item">
            <span className="c-legend-swatch" style={{ background: cssVar(KIND_COLOR[k]) }} />
            {k.toUpperCase() === 'REM' ? 'REM' : k}
            <span className="muted">{' ' + fmt.minutes(m)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------- table
export interface Column { key: string; label: string; num?: boolean }
export function DataTable({ columns, rows }: { columns: Column[]; rows: Record<string, unknown>[] }) {
  return (
    <table className="data c-table">
      <thead><tr>{columns.map((c) => <th key={c.key} className={c.num ? 'num' : ''}>{c.label}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>{columns.map((c) => <td key={c.key} className={c.num ? 'num' : ''}>{r[c.key] === null || r[c.key] === undefined ? '–' : String(r[c.key])}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}
