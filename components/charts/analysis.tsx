'use client';
/* Analysis charts: effect bars, the nightly heat strip and the planted-vs-estimated scatter (ported from charts.js). */
import { fmt, dates } from '@/lib/format';
import { showTip, hideTip, type TipRow } from '../ui/overlays';
import { cssVar, isVal, niceTicks, useThemeKey, useWidth } from './common';

// --------------------------------------------------------------- effect bars
export interface EffectItem {
  label: string; effect: number | null; lo?: number | null; hi?: number | null; adjusted?: number | null;
  confidence?: string; direction?: string; n?: number; key?: string;
}
export function EffectBars(o: { items: EffectItem[]; width?: number; rowH?: number; labelW?: number; onSelect?: (it: EffectItem) => void }) {
  useThemeKey();
  const [ref, W] = useWidth(560, o.width);
  const items = o.items || [];
  const rowH = o.rowH || 34, labelW = o.labelW || 170, valueW = 170, padT = 8;
  const H = padT + rowH * items.length + 24;
  const vals = items.flatMap((it) => [it.effect, it.lo, it.hi, it.adjusted]).filter((v): v is number => isVal(v) && isFinite(v));
  const span = Math.max(2, ...vals.map(Math.abs)) * 1.15;
  const x0 = labelW, x1 = W - valueW, mid = (x0 + x1) / 2;
  const x = (v: number) => mid + (v / span) * ((x1 - x0) / 2);
  return (
    <div ref={ref}>
      <svg className="c-effects" viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
        {niceTicks(-span, span, 6).map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={padT} y2={H - 20} stroke={cssVar('--grid')} />
            <text x={x(t)} y={H - 6} textAnchor="middle" className="c-axis tabular">{fmt.signed(t, 0)}</text>
          </g>
        ))}
        <line x1={mid} x2={mid} y1={padT} y2={H - 20} stroke={cssVar('--axis')} strokeWidth={1.5} />
        {items.map((it, i) => {
          const cy = padT + rowH * i + rowH / 2;
          const v = isVal(it.effect) ? it.effect : 0;
          const color = it.direction === 'neutral' || Math.abs(v) < 0.05 ? cssVar('--div-mid') : v > 0 ? cssVar('--div-better') : cssVar('--div-worse');
          const bx = Math.min(x(0), x(v)), bwid = Math.max(2, Math.abs(x(v) - x(0)));
          const tip = (e: React.PointerEvent) => showTip(e.clientX, e.clientY, it.label, ([{ label: 'effect', value: fmt.signed(it.effect, 1) + ' pts', color }] as TipRow[])
            .concat(isVal(it.lo) ? [{ label: '95 % interval', value: fmt.signed(it.lo, 1) + ' to ' + fmt.signed(it.hi, 1) }] : [])
            .concat(isVal(it.adjusted) ? [{ label: 'adjusted (model)', value: fmt.signed(it.adjusted, 1) }] : [])
            .concat(it.n !== undefined ? [{ label: 'nights', value: String(it.n) }] : []));
          return (
            <g key={i} className={'c-effect-row' + (o.onSelect ? ' clickable' : '')} onPointerMove={tip} onPointerLeave={hideTip} onClick={o.onSelect ? () => o.onSelect!(it) : undefined}>
              <text x={0} y={cy + 4} className="c-label">{it.label}</text>
              <rect x={bx} y={cy - 8} width={bwid} height={16} rx={4} fill={color} opacity={it.confidence === 'low' ? 0.55 : 0.95} />
              {isVal(it.lo) && isVal(it.hi) ? (
                <>
                  <line x1={x(it.lo)} x2={x(it.hi)} y1={cy} y2={cy} stroke={cssVar('--ink-secondary')} strokeWidth={1.5} />
                  <line x1={x(it.lo)} x2={x(it.lo)} y1={cy - 5} y2={cy + 5} stroke={cssVar('--ink-secondary')} strokeWidth={1.5} />
                  <line x1={x(it.hi)} x2={x(it.hi)} y1={cy - 5} y2={cy + 5} stroke={cssVar('--ink-secondary')} strokeWidth={1.5} />
                </>
              ) : null}
              {isVal(it.adjusted) ? <path d={`M${x(it.adjusted)} ${cy - 7} l6 7 l-6 7 l-6 -7 z`} fill={cssVar('--card')} stroke={cssVar('--ink-primary')} strokeWidth={1.5} /> : null}
              <text x={x1 + 10} y={cy + 4} className="c-value tabular">{isVal(it.effect) ? fmt.signed(it.effect, 1) + ' pts' : '–'}</text>
              {it.confidence ? <text x={W - 4} y={cy + 4} textAnchor="end" className={'c-axis c-conf-' + it.confidence}>{it.confidence}</text> : null}
            </g>
          );
        })}
      </svg>
      <div className="c-legend">
        <span className="c-legend-item"><span className="c-legend-swatch" style={{ background: cssVar('--div-better') }} />better sleep</span>
        <span className="c-legend-item"><span className="c-legend-swatch" style={{ background: cssVar('--div-worse') }} />worse sleep</span>
        <span className="c-legend-item"><span className="c-legend-diamond" />adjusted (model)</span>
        <span className="c-legend-item"><span className="c-legend-whisker" />95 % interval</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- heat strip
export interface HeatDay { date: string; score: number | null; worn: boolean; is_weekend?: boolean }
export function HeatStrip(o: { className?: string; days: HeatDay[]; width?: number; onSelect?: (d: HeatDay) => void }) {
  useThemeKey();
  const [ref, W] = useWidth(700, o.width);
  const binColor = (score: number | null) => (!isVal(score) ? null : score < 60 ? cssVar('--seq-6') : score < 70 ? cssVar('--seq-5') : score < 80 ? cssVar('--seq-4') : score < 90 ? cssVar('--seq-3') : cssVar('--seq-2'));
  const days = (o.days || []).slice().sort((a, b) => (a.date < b.date ? -1 : 1));
  if (!days.length) return <div ref={ref} className={o.className}><div className="c-empty muted">No nights yet</div></div>;
  const first = dates.parse(days[0].date);
  const offset = (first.getDay() + 6) % 7; // Monday = 0
  const cols = Math.ceil((days.length + offset) / 7);
  const cell = Math.max(10, Math.min(22, Math.floor((W - 40) / cols) - 3)), gapPx = 3, padL = 34, padT = 18;
  const H = padT + 7 * (cell + gapPx) + 4;
  let lastMonth: number | null = null;
  const monthLabels: { x: number; text: string }[] = [];
  const cells = days.map((day, i) => {
    const idx = i + offset, col = Math.floor(idx / 7), row = idx % 7;
    const cx = padL + col * (cell + gapPx), cy = padT + row * (cell + gapPx);
    const dt = dates.parse(day.date);
    if (dt.getMonth() !== lastMonth && row === 0) {
      monthLabels.push({ x: cx, text: dt.toLocaleString('en', { month: 'short' }) });
      lastMonth = dt.getMonth();
    }
    const color = day.worn ? binColor(day.score) : null;
    return (
      <g key={day.date}>
        <rect x={cx} y={cy} width={cell} height={cell} rx={3} fill={day.worn ? color || cssVar('--card-3') : 'url(#hatch-heat)'} className={'c-heat-cell' + (o.onSelect ? ' clickable' : '')} data-date={day.date}
          onPointerMove={(e) => showTip(e.clientX, e.clientY, fmtDayLong(day.date), ([{ label: 'sleep score', value: day.worn ? String(day.score) : 'watch not worn', color: color || cssVar('--ink-muted') }] as TipRow[]).concat(day.is_weekend ? [{ label: 'night', value: 'weekend' }] : []))}
          onPointerLeave={hideTip} onClick={o.onSelect ? () => o.onSelect!(day) : undefined} />
        {day.worn && cell >= 18 ? <text x={cx + cell / 2} y={cy + cell / 2 + 3.5} textAnchor="middle" className="c-heat-value">{String(day.score)}</text> : null}
      </g>
    );
  });
  return (
    <div ref={ref} className={o.className}>
      <svg className="c-heat" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="Sleep score by night">
        <defs>
          <pattern id="hatch-heat" width={5} height={5} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width={5} height={5} fill={cssVar('--card-3')} />
            <line x1={0} y1={0} x2={0} y2={5} stroke={cssVar('--hairline-strong')} strokeWidth={2} />
          </pattern>
        </defs>
        {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d, i) => (i % 2 === 0 ? <text key={d} x={padL - 8} y={padT + i * (cell + gapPx) + cell - 3} textAnchor="end" className="c-axis">{d}</text> : null))}
        {monthLabels.map((m) => <text key={m.x} x={m.x} y={padT - 6} className="c-axis">{m.text}</text>)}
        {cells}
      </svg>
      <div className="c-legend">
        {([['< 60', '--seq-6'], ['60–69', '--seq-5'], ['70–79', '--seq-4'], ['80–89', '--seq-3'], ['90+', '--seq-2']] as [string, string][]).map(([lab, c]) => (
          <span key={lab} className="c-legend-item"><span className="c-legend-swatch" style={{ background: cssVar(c) }} />{lab}</span>
        ))}
        <span className="c-legend-item"><span className="c-legend-swatch c-hatch" />watch not worn</span>
      </div>
    </div>
  );
}
const fmtDayLong = (iso: string) => fmt.dayLong(iso);

// ------------------------------------------------------------------- scatter
export interface ScatterPoint { x: number | null; y: number | null; lo?: number | null; hi?: number | null; label?: string; hollow?: boolean; color?: string }
export function Scatter(o: { points: ScatterPoint[]; width?: number; height?: number; xLabel?: string; yLabel?: string; identity?: boolean }) {
  useThemeKey();
  const [ref, W] = useWidth(480, o.width);
  const pts = (o.points || []).filter((p) => isVal(p.x) && isVal(p.y)) as (ScatterPoint & { x: number; y: number })[];
  const H = o.height || 300, padL = 44, padR = 16, padT = 12, padB = 40;
  const all = pts.flatMap((p) => [p.x, p.y, p.lo, p.hi]).filter((v): v is number => isVal(v) && isFinite(v));
  let lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const pad = Math.max(1, (hi - lo) * 0.12); lo -= pad; hi += pad;
  const x = (v: number) => padL + ((v - lo) / (hi - lo)) * (W - padL - padR);
  const y = (v: number) => padT + (H - padT - padB) - ((v - lo) / (hi - lo)) * (H - padT - padB);
  const midY = (padT + H - padB) / 2;
  return (
    <div ref={ref}>
      <svg className="c-scatter" viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
        {niceTicks(lo, hi, 5).map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke={cssVar('--grid')} />
            <line x1={x(t)} x2={x(t)} y1={padT} y2={H - padB} stroke={cssVar('--grid')} />
            <text x={padL - 8} y={y(t) + 4} textAnchor="end" className="c-axis tabular">{fmt.signed(t, 0)}</text>
            <text x={x(t)} y={H - padB + 16} textAnchor="middle" className="c-axis tabular">{fmt.signed(t, 0)}</text>
          </g>
        ))}
        {o.identity ? <line x1={x(lo)} y1={y(lo)} x2={x(hi)} y2={y(hi)} stroke={cssVar('--axis')} strokeWidth={1.5} /> : null}
        <line x1={x(0)} x2={x(0)} y1={padT} y2={H - padB} stroke={cssVar('--axis')} />
        <line x1={padL} x2={W - padR} y1={y(0)} y2={y(0)} stroke={cssVar('--axis')} />
        {pts.map((p, i) => {
          const color = p.color || cssVar('--series-2');
          return (
            <g key={i}>
              {isVal(p.lo) && isVal(p.hi) ? <line x1={x(p.x)} x2={x(p.x)} y1={y(p.lo)} y2={y(p.hi)} stroke={color} strokeWidth={1.5} opacity={0.7} /> : null}
              <circle cx={x(p.x)} cy={y(p.y)} r={6} fill={p.hollow ? cssVar('--card') : color} stroke={p.hollow ? color : cssVar('--card')} strokeWidth={2}
                onPointerMove={(e) => showTip(e.clientX, e.clientY, p.label, ([{ label: o.xLabel || 'x', value: fmt.signed(p.x, 1) }, { label: o.yLabel || 'y', value: fmt.signed(p.y, 1), color }] as TipRow[])
                  .concat(isVal(p.lo) ? [{ label: '95 % interval', value: fmt.signed(p.lo, 1) + ' to ' + fmt.signed(p.hi, 1) }] : []))}
                onPointerLeave={hideTip} />
              {p.label && !p.hollow && pts.length <= 12 ? <text x={x(p.x) + 9} y={y(p.y) - 8} className="c-label small">{p.label}</text> : null}
            </g>
          );
        })}
        <text x={(padL + W - padR) / 2} y={H - 6} textAnchor="middle" className="c-axis">{o.xLabel || ''}</text>
        <text x={12} y={midY} textAnchor="middle" className="c-axis" transform={`rotate(-90 12 ${midY})`}>{o.yLabel || ''}</text>
      </svg>
    </div>
  );
}
