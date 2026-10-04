'use client';
/* The 24-hour day: calendar lane, Maps lane, minute heart rate against the personal norm, sleep shading (charts.js). */
import { memo, useMemo, useRef, useState } from 'react';
import { minuteLabel, minuteOf } from '@/lib/format';
import { ICON_PATHS, eventIcon } from '@/lib/icons';
import { EVENT_LABELS, palette } from '@/lib/palette';
import { showTip, hideTip, type TipRow } from '../ui/overlays';
import { cssVar, niceTicks, useThemeKey, useWidth } from './common';

const PLACE_LABEL: Record<string, string> = { home: 'Home', office: 'Office', gym: 'Gym', restaurant: 'Restaurant', bar: 'Bar', transit: 'Transit', airport: 'Airport', hotel: 'Hotel', away: 'Away', outdoors: 'Outdoors', other: 'Elsewhere' };
const PLACE_SHADE: Record<string, number> = { home: 0.18, office: 0.42, gym: 0.6, restaurant: 0.6, bar: 0.6, transit: 0.3, airport: 0.5, hotel: 0.45, away: 0.5, outdoors: 0.5, other: 0.35 };

export interface TimelineData {
  date: string; events: any[]; visits: any[]; hr: (number | null)[] | null; norm: (number | null)[] | null;
  night?: any; nightPrev?: any; workouts?: any[]; checks?: any[];
}
export interface MinuteInfo { hr: number | null; norm: number | null; event: any | null; place: any | null }

/** What is happening at minute ``m`` of the day (heart rate, norm, attended event, place). */
export function valueAt(o: TimelineData, m: number): MinuteInfo {
  const hr = (o.hr || [])[m];
  const norm = (o.norm || [])[m];
  const ev = (o.events || []).find((e) => e.attended !== false && (minuteOf(e.start, o.date) as number) <= m && (minuteOf(e.end, o.date) as number) > m) || null;
  const place = (o.visits || []).find((v) => (minuteOf(v.start, o.date) as number) <= m && (minuteOf(v.end, o.date) as number) > m) || null;
  return { hr: hr === undefined ? null : hr, norm: norm === undefined ? null : norm, event: ev, place };
}

interface Props extends TimelineData {
  compact?: boolean; width?: number; className?: string; cursorMinute?: number | null;
  onSeek?: (m: number) => void; onHover?: (m: number, info: MinuteInfo) => void;
}

interface Geometry { W: number; H: number; padL: number; padR: number; padT: number; yHr: number; hrH: number; x: (m: number) => number }

/** Static layers, memoized so playback (which only moves the cursor) does not redraw 1 440 points per frame. */
const Layers = memo(function Layers({ o, g, compact, theme }: { o: TimelineData; g: Geometry; compact: boolean; theme: string }) {
  void theme;
  const { W, H, padL, padT, yHr, hrH, x } = g;
  const laneEv = compact ? 22 : 34, laneLoc = compact ? 0 : 16, gap = 6;
  const yEv = padT, yLoc = padT + laneEv + gap;
  const hr = o.hr || [], norm = o.norm || [];
  const hrVals = hr.filter((v): v is number => v !== null && v !== undefined);
  const lo = Math.max(30, Math.min(...(hrVals.length ? hrVals : [50])) - 5), hi = Math.min(200, Math.max(...(hrVals.length ? hrVals : [120])) + 5);
  const y = (v: number) => yHr + hrH - ((v - lo) / Math.max(1, hi - lo)) * hrH;
  const sleepFill = cssVar('--sleep-deep');
  const out: React.ReactNode[] = [];

  // sleep shading
  if (o.nightPrev && o.nightPrev.worn && o.nightPrev.wake_time) {
    const w = minuteOf(o.nightPrev.wake_time, o.date);
    if (w !== null && w > 0) out.push(<rect key="sleep-prev" x={x(0)} y={yHr} width={x(Math.min(1440, w)) - x(0)} height={hrH} fill={sleepFill} opacity={0.12} />);
  }
  if (o.night && o.night.worn && o.night.in_bed_start) {
    const b = minuteOf(o.night.in_bed_start, o.date);
    if (b !== null && b < 1440) out.push(<rect key="sleep" x={x(b)} y={yHr} width={x(1440) - x(b)} height={hrH} fill={sleepFill} opacity={0.12} />);
  }
  // grid + hour labels
  for (let h = 0; h <= 24; h += compact ? 6 : 3) {
    out.push(<line key={'g' + h} x1={x(h * 60)} x2={x(h * 60)} y1={padT} y2={yHr + hrH} stroke={cssVar('--grid')} />);
    out.push(<text key={'gl' + h} x={x(h * 60)} y={H - 5} textAnchor="middle" className="c-axis">{(h % 24).toString().padStart(2, '0') + ':00'}</text>);
  }
  const ticks = compact ? [Math.ceil(lo / 10) * 10 + 10, Math.floor(hi / 10) * 10 - 10].filter((v, i, a) => a.indexOf(v) === i && v > lo && v < hi) : niceTicks(lo, hi, 4);
  ticks.forEach((t) => out.push(<text key={'t' + t} x={padL - 6} y={y(t) + 4} textAnchor="end" className="c-axis tabular">{String(t)}</text>));
  // norm + exceedance
  if (norm.length) {
    let nd = ''; let pen = false;
    for (let m = 0; m < 1440; m += 5) { const v = norm[m]; if (v === null || v === undefined) { pen = false; continue; } nd += (pen ? ' L' : ' M') + x(m) + ' ' + y(v); pen = true; }
    let ed = ''; let back: [number, number][] = [];
    for (let m = 0; m < 1440; m += 2) {
      const v = hr[m], nv = norm[m];
      if (v === null || v === undefined || nv === null || nv === undefined) continue;
      if (v > nv + 3) { ed += (ed && back.length ? ' L' : ed ? ' M' : 'M') + x(m) + ' ' + y(v); back.push([x(m), y(nv + 3)]); }
      else if (back.length) { for (let k = back.length - 1; k >= 0; k--) ed += ' L' + back[k][0] + ' ' + back[k][1]; ed += ' Z'; back = []; }
    }
    if (back.length) { for (let k = back.length - 1; k >= 0; k--) ed += ' L' + back[k][0] + ' ' + back[k][1]; ed += ' Z'; }
    if (ed) out.push(<path key="exceed" d={ed} fill={cssVar('--div-worse')} opacity={0.16} />);
    if (nd) out.push(<path key="norm" d={nd.trim()} fill="none" stroke={cssVar('--ink-muted')} strokeWidth={1.5} strokeDasharray="4 4" className="c-norm" />);
  }
  // HR line
  let d = ''; let pen = false;
  for (let m = 0; m < 1440; m++) { const v = hr[m]; if (v === null || v === undefined) { pen = false; continue; } d += (pen ? ' L' : ' M') + x(m).toFixed(1) + ' ' + y(v).toFixed(1); pen = true; }
  out.push(<path key="hr" d={d.trim()} fill="none" stroke={cssVar('--series-1')} strokeWidth={compact ? 1.5 : 2} strokeLinejoin="round" className="c-hr" />);
  // workout brackets
  (o.workouts || []).forEach((w, i) => {
    const a = minuteOf(w.start, o.date), b = minuteOf(w.end, o.date);
    if (a === null || b === null) return;
    out.push(<rect key={'w' + i} x={x(a)} y={yHr} width={Math.max(2, x(b) - x(a))} height={3} fill={cssVar('--evt-workout')} />);
  });
  // location lane
  if (laneLoc) {
    (o.visits || []).forEach((v, i) => {
      const a = Math.max(0, minuteOf(v.start, o.date) as number), b = Math.min(1440, minuteOf(v.end, o.date) as number);
      if (b <= a) return;
      out.push(
        <rect key={'v' + i} x={x(a)} y={yLoc} width={Math.max(1, x(b) - x(a) - 1)} height={laneLoc} rx={3} fill={cssVar('--ink-muted')} opacity={PLACE_SHADE[v.place_type] || 0.35}
          onPointerMove={(e) => showTip(e.clientX, e.clientY, minuteLabel(a) + '–' + minuteLabel(b), [{ label: PLACE_LABEL[v.place_type] || v.place_type, value: v.place_name }])}
          onPointerLeave={hideTip} />,
      );
      if (x(b) - x(a) > 60) out.push(<text key={'vl' + i} x={x(a) + 6} y={yLoc + laneLoc - 4} className="c-loc-label">{v.place_name}</text>);
    });
    out.push(<text key="maps" x={padL - 6} y={yLoc + laneLoc - 4} textAnchor="end" className="c-axis">Maps</text>);
  }
  // events lane
  const checksByEvent: Record<string, any> = {};
  (o.checks || []).forEach((c) => { if (c.event_id) checksByEvent[c.event_id] = c; });
  const sorted = (o.events || []).slice().sort((a, b) => (a.start < b.start ? -1 : 1));
  sorted.forEach((ev) => {
    const a = Math.max(0, minuteOf(ev.start, o.date) as number), b = Math.min(1440, minuteOf(ev.end, o.date) as number);
    if (b <= a) return;
    const color = palette.event(ev.type);
    const rectAttrs: React.SVGProps<SVGRectElement> = { x: x(a), y: yEv, width: Math.max(3, x(b) - x(a) - 2), height: laneEv, rx: 5, fill: color, opacity: ev.attended === false ? 0.35 : 0.9 };
    if (ev.type === 'protected') Object.assign(rectAttrs, { fill: 'transparent', stroke: cssVar('--evt-protected'), strokeWidth: 1.5, strokeDasharray: '4 3' });
    if (ev.attended === false) Object.assign(rectAttrs, { stroke: color, strokeWidth: 1.5, strokeDasharray: '3 3', fill: 'transparent' });
    const wpx = x(b) - x(a);
    const ink = ev.type === 'protected' || ev.attended === false ? cssVar('--ink-primary') : ev.type === 'focus' ? '#1B1F3B' : '#FFFFFF';
    const chk = checksByEvent[ev.id];
    const tip = (e: React.PointerEvent) => showTip(e.clientX, e.clientY, minuteLabel(a) + '–' + minuteLabel(b), ([{ label: EVENT_LABELS[ev.type] || ev.type, value: ev.title, color }] as TipRow[])
      .concat(ev.attended === false ? [{ label: 'status', value: 'not attended' }] : [])
      .concat(chk ? [{ label: 'reality check', value: chk.status }] : []));
    out.push(
      <g key={'e' + ev.id} className={'c-evt c-evt-' + ev.type + (ev.attended === false ? ' unattended' : '')} onPointerMove={tip} onPointerLeave={hideTip}>
        <rect {...rectAttrs} />
        {!compact || wpx > 40 ? (
          <>
            <g transform={`translate(${x(a) + 5} ${yEv + (laneEv - 14) / 2}) scale(${14 / 24})`} fill="none" stroke={ink} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
              dangerouslySetInnerHTML={{ __html: ICON_PATHS[eventIcon(ev.type)] || ICON_PATHS.dot }} />
            {wpx > 56 ? (
              <>
                <clipPath id={'clip-' + ev.id}><rect x={x(a)} y={yEv} width={Math.max(0, wpx - 6)} height={laneEv} /></clipPath>
                <text x={x(a) + 22} y={yEv + laneEv / 2 + 4} className="c-evt-label" fill={ink} clipPath={`url(#clip-${ev.id})`}>{ev.title}</text>
              </>
            ) : null}
          </>
        ) : null}
        {chk ? <circle cx={x(b) - 6} cy={yEv + 6} r={5} fill={chk.status === 'open' ? cssVar('--status-warning') : chk.status === 'no' ? cssVar('--status-critical') : cssVar('--status-good')} stroke={cssVar('--card')} strokeWidth={2} /> : null}
      </g>,
    );
  });
  out.push(<text key="cal" x={padL - 6} y={yEv + laneEv / 2 + 4} textAnchor="end" className="c-axis">Calendar</text>);
  if (!compact) out.push(<text key="bpm" x={padL - 6} y={yHr - 2} textAnchor="end" className="c-axis">bpm</text>);
  return <>{out}</>;
});

export function DayTimeline(props: Props) {
  const theme = useThemeKey();
  const compact = !!props.compact;
  const [ref, W] = useWidth(900, props.width);
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const padL = 62, padR = 12, padT = 8;
  const laneEv = compact ? 22 : 34, laneLoc = compact ? 0 : 16, hrH = compact ? 44 : 120, gap = 6, padB = 20;
  const H = padT + laneEv + gap + (laneLoc ? laneLoc + gap : 0) + hrH + padB;
  const yHr = padT + laneEv + gap + (laneLoc ? laneLoc + gap : 0);
  const x = (m: number) => padL + (Math.max(0, Math.min(1440, m)) / 1440) * (W - padL - padR);
  const data = useMemo<TimelineData>(() => ({
    date: props.date, events: props.events, visits: props.visits, hr: props.hr, norm: props.norm, night: props.night, nightPrev: props.nightPrev, workouts: props.workouts, checks: props.checks,
  }), [props.date, props.events, props.visits, props.hr, props.norm, props.night, props.nightPrev, props.workouts, props.checks]);
  const geom = useMemo<Geometry>(() => ({ W, H, padL, padR, padT, yHr, hrH, x }), [W, H, yHr, hrH]); // eslint-disable-line react-hooks/exhaustive-deps

  const minuteAt = (e: React.PointerEvent | React.MouseEvent) => {
    const b = svgRef.current!.getBoundingClientRect();
    const px = (e.clientX - b.left) * (W / b.width);
    return Math.max(0, Math.min(1439, Math.round(((px - padL) / (W - padL - padR)) * 1440)));
  };
  const onMove = (e: React.PointerEvent) => {
    const m = minuteAt(e);
    setHover(m);
    const info = valueAt(data, m);
    const rows: TipRow[] = [{ label: 'heart rate', value: info.hr === null ? '–' : info.hr + ' bpm', color: cssVar('--series-1') }];
    if (info.norm !== null) rows.push({ label: 'your norm', value: Math.round(info.norm) + ' bpm', color: cssVar('--ink-muted') });
    if (info.event) rows.push({ label: EVENT_LABELS[info.event.type] || 'event', value: info.event.title, color: palette.event(info.event.type) });
    if (info.place) rows.push({ label: 'place', value: info.place.place_name });
    showTip(e.clientX, e.clientY, minuteLabel(m), rows);
    props.onHover?.(m, info);
  };
  const cursor = props.cursorMinute ?? null;
  return (
    <div ref={ref} className={props.className}>
      <svg ref={svgRef} className={'c-timeline' + (compact ? ' compact' : '')} viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={'Day timeline ' + (props.date || '')}>
        <Layers o={data} g={geom} compact={compact} theme={theme} />
        <line x1={x(cursor || 0)} x2={x(cursor || 0)} y1={padT} y2={yHr + hrH} stroke={cssVar('--accent')} strokeWidth={2} opacity={cursor === null ? 0 : 1} className="c-cursor" />
        <line x1={x(hover || 0)} x2={x(hover || 0)} y1={padT} y2={yHr + hrH} stroke={cssVar('--hairline-strong')} opacity={hover === null ? 0 : 1} />
        <rect x={padL} y={yHr} width={W - padL - padR} height={hrH} fill="transparent" style={{ cursor: props.onSeek ? 'pointer' : 'default' }}
          onPointerMove={onMove} onPointerLeave={() => { setHover(null); hideTip(); }} onClick={props.onSeek ? (e) => props.onSeek!(minuteAt(e)) : undefined} />
      </svg>
    </div>
  );
}
