'use strict';
/* StressLess charts — hand-drawn SVG primitives with hover layers (SPEC §9.3).
 * Every chart: Charts.x(el, opts) -> { update(opts), destroy() }. Text via text nodes only. */
(function () {
  const svg = (tag, attrs, ...children) => SL.svg(tag, attrs, ...children);
  const el = (tag, attrs, ...children) => SL.el(tag, attrs, ...children);
  const Charts = {};

  // ---------------------------------------------------------------- tooltip
  let tip = null;
  function tooltip() {
    if (!tip) { tip = el('div', { class: 'viz-tooltip', hidden: true }); document.body.appendChild(tip); }
    return tip;
  }
  function showTip(x, y, title, rows) {
    const t = tooltip();
    SL.clear(t);
    if (title) t.appendChild(el('div', { class: 'tt-title' }, title));
    (rows || []).forEach(r => {
      t.appendChild(el('div', { class: 'tt-row' },
        el('span', { class: 'row', style: { gap: '6px' } }, r.color ? el('span', { class: 'tt-key', style: { background: r.color } }) : null, el('span', { class: 'tt-label' }, r.label)),
        el('span', { class: 'tt-value' }, r.value)));
    });
    t.hidden = false;
    const pad = 12;
    const w = t.offsetWidth, h = t.offsetHeight;
    let left = x + pad, top = y + pad;
    if (left + w > window.innerWidth - 8) left = x - w - pad;
    if (top + h > window.innerHeight - 8) top = y - h - pad;
    t.style.left = left + 'px'; t.style.top = top + 'px';
  }
  function hideTip() { if (tip) tip.hidden = true; }
  Charts.hideTip = hideTip;

  // ----------------------------------------------------------------- utils
  const cssVar = (n) => SL.palette.var(n);
  function niceTicks(lo, hi, n) {
    if (!(hi > lo)) return [lo];
    const span = hi - lo, raw = span / Math.max(1, n);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const start = Math.ceil(lo / step) * step;
    const out = [];
    for (let v = start; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
    return out;
  }
  function minuteLabel(m) { const mm = ((m % 1440) + 1440) % 1440; return (mm / 60 | 0).toString().padStart(2, '0') + ':' + (mm % 60).toString().padStart(2, '0'); }
  function width(elm, fallback) { return Math.max(160, elm.clientWidth || fallback || 600); }
  function bind(elm, render) {
    let frame = null;
    const onResize = () => { if (frame) cancelAnimationFrame(frame); frame = requestAnimationFrame(render); };
    window.addEventListener('resize', onResize);
    return () => { window.removeEventListener('resize', onResize); hideTip(); };
  }
  Charts.minuteOf = function (iso, dayIso) {
    if (!iso) return null;
    const m = String(iso).match(/(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/);
    if (!m) return null;
    let v = (+m[2]) * 60 + (+m[3]);
    if (dayIso && m[1] > dayIso) v += 1440;
    if (dayIso && m[1] < dayIso) v -= 1440;
    return v;
  };
  const bandColor = (band) => ({ good: cssVar('--status-good'), warning: cssVar('--status-warning'), serious: cssVar('--status-serious'), critical: cssVar('--status-critical') }[band] || cssVar('--ink-muted'));
  Charts.bandFor = function (score) {
    if (score === null || score === undefined) return 'unknown';
    if (score <= 40) return 'critical'; if (score <= 60) return 'serious'; if (score <= 80) return 'warning'; return 'good';
  };
  Charts.ratingFor = function (score) {
    if (score === null || score === undefined) return 'No data';
    if (score <= 40) return 'Very low'; if (score <= 60) return 'Low'; if (score <= 80) return 'OK'; if (score <= 95) return 'High'; return 'Very high';
  };

  // ------------------------------------------------------------------ ring
  Charts.ring = function (elm, opts) {
    let o = opts;
    function render() {
      SL.clear(elm);
      const size = o.size || 180, sw = Math.max(8, size * 0.075), r = (size - sw) / 2, c = size / 2, circ = 2 * Math.PI * r;
      const frac = (o.value === null || o.value === undefined) ? 0 : Math.max(0, Math.min(1, o.value / (o.max || 100)));
      const band = o.band || Charts.bandFor(o.value);
      const color = bandColor(band);
      const s = svg('svg', { class: 'c-ring', viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: 'img', 'aria-label': (o.label || 'score') + ' ' + SL.fmt.score(o.value) });
      s.appendChild(svg('circle', { cx: c, cy: c, r, fill: 'none', stroke: cssVar('--card-3'), 'stroke-width': sw }));
      if (frac > 0) s.appendChild(svg('circle', { cx: c, cy: c, r, fill: 'none', stroke: color, 'stroke-width': sw, 'stroke-linecap': 'round', 'stroke-dasharray': `${circ * frac} ${circ}`, transform: `rotate(-90 ${c} ${c})`, class: 'c-ring-arc' }));
      s.appendChild(svg('text', { x: c, y: c + (o.label ? -2 : 8), 'text-anchor': 'middle', class: 'c-ring-value', style: { fontSize: (size * 0.3) + 'px' } }, SL.fmt.score(o.value)));
      if (o.label) s.appendChild(svg('text', { x: c, y: c + size * 0.13, 'text-anchor': 'middle', class: 'c-ring-label' }, o.label));
      if (o.sublabel) s.appendChild(svg('text', { x: c, y: c + size * 0.23, 'text-anchor': 'middle', class: 'c-ring-sub' }, o.sublabel));
      elm.appendChild(s);
    }
    render();
    return { update: (n) => { o = Object.assign({}, o, n); render(); }, destroy: () => SL.clear(elm) };
  };

  // ------------------------------------------------------------- sparkline
  Charts.sparkline = function (elm, opts) {
    let o = opts;
    let unbind = null;
    function render() {
      SL.clear(elm);
      const W = o.width || width(elm, 320), H = o.height || 56, padY = 4;
      const vals = o.values || [];
      const norm = o.norm || null;
      const all = vals.concat(norm || []).concat(o.baseline !== undefined && o.baseline !== null ? [o.baseline] : []).filter(v => v !== null && v !== undefined);
      if (!vals.length || !all.length) { elm.appendChild(el('div', { class: 'c-empty tiny muted' }, 'No data')); return; }
      let lo = Math.min(...all), hi = Math.max(...all);
      if (hi - lo < 1e-9) { hi = lo + 1; lo = lo - 1; }
      const padV = (hi - lo) * 0.1; lo -= padV; hi += padV;
      const x = (i) => vals.length > 1 ? (i / (vals.length - 1)) * W : W / 2;
      const y = (v) => H - padY - ((v - lo) / (hi - lo)) * (H - 2 * padY);
      const s = svg('svg', { class: 'c-spark', viewBox: `0 0 ${W} ${H}`, width: W, height: H, preserveAspectRatio: 'none' });
      const color = o.color || cssVar('--series-1');
      // exceedance fill (value above norm + 3)
      if (norm) {
        let d = '';
        vals.forEach((v, i) => { if (v !== null && norm[i] !== null && norm[i] !== undefined) { d += (d ? ' L' : 'M') + x(i) + ' ' + y(Math.max(v, norm[i] + 3)) ; } });
        let back = '';
        for (let i = vals.length - 1; i >= 0; i--) if (vals[i] !== null && norm[i] !== null && norm[i] !== undefined) back += ' L' + x(i) + ' ' + y(norm[i] + 3);
        if (d) s.appendChild(svg('path', { d: d + back + ' Z', fill: cssVar('--div-worse'), opacity: 0.12 }));
        let nd = '';
        norm.forEach((v, i) => { if (v !== null && v !== undefined) nd += (nd ? ' L' : 'M') + x(i) + ' ' + y(v); });
        if (nd) s.appendChild(svg('path', { d: nd, fill: 'none', stroke: cssVar('--ink-muted'), 'stroke-width': 1.5, 'stroke-dasharray': '3 3' }));
      }
      if (o.baseline !== undefined && o.baseline !== null) s.appendChild(svg('line', { x1: 0, x2: W, y1: y(o.baseline), y2: y(o.baseline), stroke: cssVar('--ink-muted'), 'stroke-width': 1, 'stroke-dasharray': '3 3' }));
      let d = ''; let pen = false;
      vals.forEach((v, i) => { if (v === null || v === undefined) { pen = false; return; } d += (pen ? ' L' : ' M') + x(i) + ' ' + y(v); pen = true; });
      s.appendChild(svg('path', { d: d.trim(), fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
      let lastIdx = -1; vals.forEach((v, i) => { if (v !== null && v !== undefined) lastIdx = i; });
      if (lastIdx >= 0) { s.appendChild(svg('circle', { cx: x(lastIdx), cy: y(vals[lastIdx]), r: 4, fill: color, stroke: cssVar('--card'), 'stroke-width': 2 })); }
      const cursor = svg('line', { x1: 0, x2: 0, y1: 0, y2: H, stroke: cssVar('--hairline-strong'), 'stroke-width': 1, opacity: 0 });
      s.appendChild(cursor);
      const rect = svg('rect', { x: 0, y: 0, width: W, height: H, fill: 'transparent' });
      rect.addEventListener('pointermove', (e) => {
        const b = s.getBoundingClientRect();
        const i = Math.max(0, Math.min(vals.length - 1, Math.round(((e.clientX - b.left) / b.width) * (vals.length - 1))));
        cursor.setAttribute('x1', x(i)); cursor.setAttribute('x2', x(i)); cursor.setAttribute('opacity', 1);
        const rows = [{ label: o.label || 'value', value: vals[i] === null ? '–' : SL.fmt.num(vals[i], o.digits || 0) + (o.unit ? ' ' + o.unit : ''), color }];
        if (norm && norm[i] !== null && norm[i] !== undefined) rows.push({ label: 'your norm', value: SL.fmt.num(norm[i], 0) + (o.unit ? ' ' + o.unit : ''), color: cssVar('--ink-muted') });
        let title = o.xLabels ? o.xLabels[i] : null;
        if (!title && o.start) { const m = Charts.minuteOf(o.start) + i * (o.stepMin || 5); title = minuteLabel(m); }
        showTip(e.clientX, e.clientY, title, rows);
      });
      rect.addEventListener('pointerleave', () => { cursor.setAttribute('opacity', 0); hideTip(); });
      s.appendChild(rect);
      elm.appendChild(s);
    }
    render();
    unbind = bind(elm, render);
    return { update: (n) => { o = Object.assign({}, o, n); render(); }, destroy: () => { unbind(); SL.clear(elm); } };
  };

  // ------------------------------------------------------------------ bars
  Charts.bars = function (elm, opts) {
    let o = opts; let unbind = null;
    function render() {
      SL.clear(elm);
      const items = o.items || [];
      const W = o.width || width(elm, 480), H = o.height || 240;
      const padL = 36, padR = 12, padT = 26, padB = 44;
      const max = o.max || Math.max(100, ...items.map(i => i.hi || i.value || 0));
      const plotW = W - padL - padR, plotH = H - padT - padB;
      const y = (v) => padT + plotH - (v / max) * plotH;
      const s = svg('svg', { class: 'c-bars', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': o.ariaLabel || 'bar chart' });
      niceTicks(0, max, 4).forEach(t => {
        s.appendChild(svg('line', { x1: padL, x2: W - padR, y1: y(t), y2: y(t), stroke: cssVar('--grid'), 'stroke-width': 1 }));
        s.appendChild(svg('text', { x: padL - 8, y: y(t) + 4, 'text-anchor': 'end', class: 'c-axis tabular' }, String(t)));
      });
      const slot = plotW / Math.max(1, items.length);
      const bw = Math.min(24, slot * 0.5);
      const color = o.color || cssVar('--series-1');
      items.forEach((it, i) => {
        const cx = padL + slot * (i + 0.5);
        if (it.value === null || it.value === undefined) {
          s.appendChild(svg('text', { x: cx, y: y(0) - 8, 'text-anchor': 'middle', class: 'c-label muted' }, 'no days'));
        } else {
          const top = y(it.value), h = Math.max(2, y(0) - top);
          const r = Math.min(4, h / 2);
          const d = `M${cx - bw / 2} ${y(0)} V${top + r} Q${cx - bw / 2} ${top} ${cx - bw / 2 + r} ${top} H${cx + bw / 2 - r} Q${cx + bw / 2} ${top} ${cx + bw / 2} ${top + r} V${y(0)} Z`;
          const bar = svg('path', { d, fill: color, class: 'c-bar' });
          bar.addEventListener('pointermove', (e) => showTip(e.clientX, e.clientY, it.label, [{ label: o.unit || 'value', value: SL.fmt.num(it.value, 1), color }].concat(it.n !== undefined ? [{ label: 'nights', value: String(it.n) }] : []).concat(it.lo !== null && it.lo !== undefined ? [{ label: '95 % range', value: SL.fmt.num(it.lo, 0) + '–' + SL.fmt.num(it.hi, 0) }] : [])));
          bar.addEventListener('pointerleave', hideTip);
          s.appendChild(bar);
          if (it.lo !== null && it.lo !== undefined && it.hi !== null && it.hi !== undefined) {
            s.appendChild(svg('line', { x1: cx, x2: cx, y1: y(it.hi), y2: y(it.lo), stroke: cssVar('--ink-secondary'), 'stroke-width': 1.5 }));
            s.appendChild(svg('line', { x1: cx - 5, x2: cx + 5, y1: y(it.hi), y2: y(it.hi), stroke: cssVar('--ink-secondary'), 'stroke-width': 1.5 }));
            s.appendChild(svg('line', { x1: cx - 5, x2: cx + 5, y1: y(it.lo), y2: y(it.lo), stroke: cssVar('--ink-secondary'), 'stroke-width': 1.5 }));
          }
          s.appendChild(svg('text', { x: cx, y: Math.min(top, it.hi !== undefined && it.hi !== null ? y(it.hi) : top) - 8, 'text-anchor': 'middle', class: 'c-value' }, (o.formatValue || ((v) => SL.fmt.num(v, 0)))(it.value)));
        }
        s.appendChild(svg('text', { x: cx, y: H - padB + 18, 'text-anchor': 'middle', class: 'c-label' }, it.label));
        if (it.n !== undefined) s.appendChild(svg('text', { x: cx, y: H - padB + 34, 'text-anchor': 'middle', class: 'c-axis' }, 'n = ' + it.n));
      });
      s.appendChild(svg('line', { x1: padL, x2: W - padR, y1: y(0), y2: y(0), stroke: cssVar('--axis'), 'stroke-width': 1 }));
      elm.appendChild(s);
    }
    render(); unbind = bind(elm, render);
    return { update: (n) => { o = Object.assign({}, o, n); render(); }, destroy: () => { unbind(); SL.clear(elm); } };
  };

  // ------------------------------------------------------------------ line
  Charts.line = function (elm, opts) {
    let o = opts; let unbind = null;
    function render() {
      SL.clear(elm);
      const series = (o.series || []).filter(s => s.values && s.values.length);
      const W = o.width || width(elm, 480), H = o.height || 200, padL = 36, padR = 12, padT = 12, padB = 28;
      const n = Math.max(...series.map(s => s.values.length), 1);
      const ys = series.flatMap(s => s.values.map(v => v.y)).filter(v => v !== null && v !== undefined);
      let [lo, hi] = o.yDomain || [Math.min(...ys), Math.max(...ys)];
      if (!(hi > lo)) { hi = lo + 1; }
      const x = (i) => padL + (n > 1 ? (i / (n - 1)) * (W - padL - padR) : (W - padL - padR) / 2);
      const y = (v) => padT + (H - padT - padB) - ((v - lo) / (hi - lo)) * (H - padT - padB);
      const s = svg('svg', { class: 'c-line', viewBox: `0 0 ${W} ${H}`, width: W, height: H });
      niceTicks(lo, hi, 4).forEach(t => { s.appendChild(svg('line', { x1: padL, x2: W - padR, y1: y(t), y2: y(t), stroke: cssVar('--grid') })); s.appendChild(svg('text', { x: padL - 8, y: y(t) + 4, 'text-anchor': 'end', class: 'c-axis tabular' }, String(t))); });
      if (o.baseline !== undefined && o.baseline !== null) s.appendChild(svg('line', { x1: padL, x2: W - padR, y1: y(o.baseline), y2: y(o.baseline), stroke: cssVar('--ink-muted'), 'stroke-dasharray': '3 3' }));
      series.forEach((ser, k) => {
        const color = ser.color || cssVar('--series-' + (k + 1));
        let d = ''; let pen = false;
        ser.values.forEach((v, i) => { if (v.y === null || v.y === undefined) { pen = false; return; } d += (pen ? ' L' : ' M') + x(i) + ' ' + y(v.y); pen = true; });
        s.appendChild(svg('path', { d: d.trim(), fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round' }));
        ser.values.forEach((v, i) => { if (v.y !== null && v.y !== undefined && (n <= 20 || i === ser.values.length - 1)) s.appendChild(svg('circle', { cx: x(i), cy: y(v.y), r: 4, fill: color, stroke: cssVar('--card'), 'stroke-width': 2 })); });
      });
      (o.xLabels || []).forEach((lab, i) => { if (n <= 14 || i % Math.ceil(n / 7) === 0) s.appendChild(svg('text', { x: x(i), y: H - 8, 'text-anchor': 'middle', class: 'c-axis' }, lab)); });
      const cursor = svg('line', { x1: 0, x2: 0, y1: padT, y2: H - padB, stroke: cssVar('--hairline-strong'), opacity: 0 });
      s.appendChild(cursor);
      const rect = svg('rect', { x: padL, y: 0, width: W - padL - padR, height: H, fill: 'transparent' });
      rect.addEventListener('pointermove', (e) => {
        const b = s.getBoundingClientRect(); const px = (e.clientX - b.left) * (W / b.width);
        const i = Math.max(0, Math.min(n - 1, Math.round(((px - padL) / (W - padL - padR)) * (n - 1))));
        cursor.setAttribute('x1', x(i)); cursor.setAttribute('x2', x(i)); cursor.setAttribute('opacity', 1);
        showTip(e.clientX, e.clientY, (o.xLabels || [])[i] || '', series.map((ser, k) => ({ label: ser.name, value: ser.values[i] && ser.values[i].y !== null && ser.values[i].y !== undefined ? SL.fmt.num(ser.values[i].y, o.digits || 0) + (o.unit ? ' ' + o.unit : '') : '–', color: ser.color || cssVar('--series-' + (k + 1)) })));
      });
      rect.addEventListener('pointerleave', () => { cursor.setAttribute('opacity', 0); hideTip(); });
      s.appendChild(rect);
      elm.appendChild(s);
      if (series.length >= 2) {
        elm.appendChild(el('div', { class: 'c-legend' }, series.map((ser, k) => el('span', { class: 'c-legend-item' }, el('span', { class: 'c-legend-line', style: { background: ser.color || cssVar('--series-' + (k + 1)) } }), ser.name))));
      }
    }
    render(); unbind = bind(elm, render);
    return { update: (n) => { o = Object.assign({}, o, n); render(); }, destroy: () => { unbind(); SL.clear(elm); } };
  };

  // ----------------------------------------------------------- effect bars
  Charts.effectBars = function (elm, opts) {
    let o = opts; let unbind = null;
    function render() {
      SL.clear(elm);
      const items = o.items || [];
      const W = o.width || width(elm, 560), rowH = o.rowH || 34, labelW = o.labelW || 170, valueW = 170, padT = 8;
      const H = padT + rowH * items.length + 24;
      const vals = items.flatMap(it => [it.effect, it.lo, it.hi, it.adjusted]).filter(v => v !== null && v !== undefined && isFinite(v));
      const span = Math.max(2, ...vals.map(Math.abs)) * 1.15;
      const x0 = labelW, x1 = W - valueW, mid = (x0 + x1) / 2;
      const x = (v) => mid + (v / span) * ((x1 - x0) / 2);
      const s = svg('svg', { class: 'c-effects', viewBox: `0 0 ${W} ${H}`, width: W, height: H });
      niceTicks(-span, span, 6).forEach(t => { s.appendChild(svg('line', { x1: x(t), x2: x(t), y1: padT, y2: H - 20, stroke: cssVar('--grid') })); s.appendChild(svg('text', { x: x(t), y: H - 6, 'text-anchor': 'middle', class: 'c-axis tabular' }, SL.fmt.signed(t, 0))); });
      s.appendChild(svg('line', { x1: mid, x2: mid, y1: padT, y2: H - 20, stroke: cssVar('--axis'), 'stroke-width': 1.5 }));
      items.forEach((it, i) => {
        const cy = padT + rowH * i + rowH / 2;
        const g = svg('g', { class: 'c-effect-row' + (o.onSelect ? ' clickable' : '') });
        const label = svg('text', { x: 0, y: cy + 4, class: 'c-label' }, it.label);
        g.appendChild(label);
        const v = it.effect === null || it.effect === undefined ? 0 : it.effect;
        const color = it.direction === 'neutral' || Math.abs(v) < 0.05 ? cssVar('--div-mid') : (v > 0 ? cssVar('--div-better') : cssVar('--div-worse'));
        const bx = Math.min(x(0), x(v)), bwid = Math.max(2, Math.abs(x(v) - x(0)));
        g.appendChild(svg('rect', { x: bx, y: cy - 8, width: bwid, height: 16, rx: 4, fill: color, opacity: it.confidence === 'low' ? 0.55 : 0.95 }));
        if (it.lo !== null && it.lo !== undefined && it.hi !== null && it.hi !== undefined) {
          g.appendChild(svg('line', { x1: x(it.lo), x2: x(it.hi), y1: cy, y2: cy, stroke: cssVar('--ink-secondary'), 'stroke-width': 1.5 }));
          g.appendChild(svg('line', { x1: x(it.lo), x2: x(it.lo), y1: cy - 5, y2: cy + 5, stroke: cssVar('--ink-secondary'), 'stroke-width': 1.5 }));
          g.appendChild(svg('line', { x1: x(it.hi), x2: x(it.hi), y1: cy - 5, y2: cy + 5, stroke: cssVar('--ink-secondary'), 'stroke-width': 1.5 }));
        }
        if (it.adjusted !== null && it.adjusted !== undefined) g.appendChild(svg('path', { d: `M${x(it.adjusted)} ${cy - 7} l6 7 l-6 7 l-6 -7 z`, fill: cssVar('--card'), stroke: cssVar('--ink-primary'), 'stroke-width': 1.5 }));
        g.appendChild(svg('text', { x: x1 + 10, y: cy + 4, class: 'c-value tabular' }, it.effect === null || it.effect === undefined ? '–' : SL.fmt.signed(it.effect, 1) + ' pts'));
        if (it.confidence) g.appendChild(svg('text', { x: W - 4, y: cy + 4, 'text-anchor': 'end', class: 'c-axis c-conf-' + it.confidence }, it.confidence));
        g.addEventListener('pointermove', (e) => showTip(e.clientX, e.clientY, it.label, [{ label: 'effect', value: SL.fmt.signed(it.effect, 1) + ' pts', color }].concat(it.lo !== undefined && it.lo !== null ? [{ label: '95 % interval', value: SL.fmt.signed(it.lo, 1) + ' to ' + SL.fmt.signed(it.hi, 1) }] : []).concat(it.adjusted !== undefined && it.adjusted !== null ? [{ label: 'adjusted (model)', value: SL.fmt.signed(it.adjusted, 1) }] : []).concat(it.n !== undefined ? [{ label: 'nights', value: String(it.n) }] : [])));
        g.addEventListener('pointerleave', hideTip);
        if (o.onSelect) g.addEventListener('click', () => o.onSelect(it));
        s.appendChild(g);
      });
      elm.appendChild(s);
      elm.appendChild(el('div', { class: 'c-legend' }, el('span', { class: 'c-legend-item' }, el('span', { class: 'c-legend-swatch', style: { background: cssVar('--div-better') } }), 'better sleep'), el('span', { class: 'c-legend-item' }, el('span', { class: 'c-legend-swatch', style: { background: cssVar('--div-worse') } }), 'worse sleep'), el('span', { class: 'c-legend-item' }, el('span', { class: 'c-legend-diamond' }), 'adjusted (model)'), el('span', { class: 'c-legend-item' }, el('span', { class: 'c-legend-whisker' }), '95 % interval')));
    }
    render(); unbind = bind(elm, render);
    return { update: (n) => { o = Object.assign({}, o, n); render(); }, destroy: () => { unbind(); SL.clear(elm); } };
  };

  // ---------------------------------------------------------- day timeline
  const PLACE_LABEL = { home: 'Home', office: 'Office', gym: 'Gym', restaurant: 'Restaurant', bar: 'Bar', transit: 'Transit', airport: 'Airport', hotel: 'Hotel', away: 'Away', outdoors: 'Outdoors', other: 'Elsewhere' };
  const PLACE_SHADE = { home: 0.18, office: 0.42, gym: 0.6, restaurant: 0.6, bar: 0.6, transit: 0.3, airport: 0.5, hotel: 0.45, away: 0.5, outdoors: 0.5, other: 0.35 };
  Charts.dayTimeline = function (elm, opts) {
    let o = opts; let unbind = null; let cursorLine = null; let cursorMin = o.cursorMinute || null; let geom = null;
    function render() {
      SL.clear(elm);
      const compact = !!o.compact;
      const W = o.width || width(elm, 900);
      const padL = 62, padR = 12, padT = 8;
      const laneEv = compact ? 22 : 34, laneLoc = compact ? 0 : 16, hrH = compact ? 44 : 120, gap = 6, padB = 20;
      const H = padT + laneEv + gap + (laneLoc ? laneLoc + gap : 0) + hrH + padB;
      const x = (m) => padL + (Math.max(0, Math.min(1440, m)) / 1440) * (W - padL - padR);
      const s = svg('svg', { class: 'c-timeline' + (compact ? ' compact' : ''), viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': 'Day timeline ' + (o.date || '') });
      const yEv = padT, yLoc = padT + laneEv + gap, yHr = yLoc + (laneLoc ? laneLoc + gap : 0);
      const hr = o.hr || [], norm = o.norm || [];
      const hrVals = hr.filter(v => v !== null && v !== undefined);
      const lo = Math.max(30, Math.min(...(hrVals.length ? hrVals : [50])) - 5), hi = Math.min(200, Math.max(...(hrVals.length ? hrVals : [120])) + 5);
      const y = (v) => yHr + hrH - ((v - lo) / Math.max(1, hi - lo)) * hrH;
      // sleep shading
      const sleepFill = cssVar('--sleep-deep');
      if (o.nightPrev && o.nightPrev.worn && o.nightPrev.wake_time) {
        const w = Charts.minuteOf(o.nightPrev.wake_time, o.date);
        if (w !== null && w > 0) s.appendChild(svg('rect', { x: x(0), y: yHr, width: x(Math.min(1440, w)) - x(0), height: hrH, fill: sleepFill, opacity: 0.12 }));
      }
      if (o.night && o.night.worn && o.night.in_bed_start) {
        const b = Charts.minuteOf(o.night.in_bed_start, o.date);
        if (b !== null && b < 1440) s.appendChild(svg('rect', { x: x(b), y: yHr, width: x(1440) - x(b), height: hrH, fill: sleepFill, opacity: 0.12 }));
      }
      // grid + hour labels
      for (let h = 0; h <= 24; h += compact ? 6 : 3) {
        s.appendChild(svg('line', { x1: x(h * 60), x2: x(h * 60), y1: padT, y2: yHr + hrH, stroke: cssVar('--grid') }));
        s.appendChild(svg('text', { x: x(h * 60), y: H - 5, 'text-anchor': 'middle', class: 'c-axis' }, (h % 24).toString().padStart(2, '0') + ':00'));
      }
      const ticks = compact ? [Math.ceil(lo / 10) * 10 + 10, Math.floor(hi / 10) * 10 - 10].filter((v, i, a) => a.indexOf(v) === i && v > lo && v < hi) : niceTicks(lo, hi, 4);
      ticks.forEach(t => { s.appendChild(svg('text', { x: padL - 6, y: y(t) + 4, 'text-anchor': 'end', class: 'c-axis tabular' }, String(t))); });
      // norm + exceedance
      if (norm.length) {
        let nd = ''; let pen = false;
        for (let m = 0; m < 1440; m += 5) { const v = norm[m]; if (v === null || v === undefined) { pen = false; continue; } nd += (pen ? ' L' : ' M') + x(m) + ' ' + y(v); pen = true; }
        let ed = ''; let back = [];
        for (let m = 0; m < 1440; m += 2) {
          const v = hr[m], nv = norm[m];
          if (v === null || v === undefined || nv === null || nv === undefined) continue;
          if (v > nv + 3) { ed += (ed && back.length ? ' L' : (ed ? ' M' : 'M')) + x(m) + ' ' + y(v); back.push([x(m), y(nv + 3)]); }
          else if (back.length) { for (let k = back.length - 1; k >= 0; k--) ed += ' L' + back[k][0] + ' ' + back[k][1]; ed += ' Z'; back = []; }
        }
        if (back.length) { for (let k = back.length - 1; k >= 0; k--) ed += ' L' + back[k][0] + ' ' + back[k][1]; ed += ' Z'; }
        if (ed) s.appendChild(svg('path', { d: ed, fill: cssVar('--div-worse'), opacity: 0.16 }));
        if (nd) s.appendChild(svg('path', { d: nd.trim(), fill: 'none', stroke: cssVar('--ink-muted'), 'stroke-width': 1.5, 'stroke-dasharray': '4 4', class: 'c-norm' }));
      }
      // HR line
      let d = ''; let pen = false;
      for (let m = 0; m < 1440; m++) { const v = hr[m]; if (v === null || v === undefined) { pen = false; continue; } d += (pen ? ' L' : ' M') + x(m).toFixed(1) + ' ' + y(v).toFixed(1); pen = true; }
      s.appendChild(svg('path', { d: d.trim(), fill: 'none', stroke: cssVar('--series-1'), 'stroke-width': compact ? 1.5 : 2, 'stroke-linejoin': 'round', class: 'c-hr' }));
      // workouts brackets
      (o.workouts || []).forEach(w => {
        const a = Charts.minuteOf(w.start, o.date), b = Charts.minuteOf(w.end, o.date);
        if (a === null || b === null) return;
        s.appendChild(svg('rect', { x: x(a), y: yHr, width: Math.max(2, x(b) - x(a)), height: 3, fill: cssVar('--evt-workout') }));
      });
      // location lane
      if (laneLoc) {
        (o.visits || []).forEach(v => {
          const a = Math.max(0, Charts.minuteOf(v.start, o.date)), b = Math.min(1440, Charts.minuteOf(v.end, o.date));
          if (b <= a) return;
          const r = svg('rect', { x: x(a), y: yLoc, width: Math.max(1, x(b) - x(a) - 1), height: laneLoc, rx: 3, fill: cssVar('--ink-muted'), opacity: PLACE_SHADE[v.place_type] || 0.35 });
          r.addEventListener('pointermove', (e) => showTip(e.clientX, e.clientY, minuteLabel(a) + '–' + minuteLabel(b), [{ label: PLACE_LABEL[v.place_type] || v.place_type, value: v.place_name }]));
          r.addEventListener('pointerleave', hideTip);
          s.appendChild(r);
          if (x(b) - x(a) > 60) s.appendChild(svg('text', { x: x(a) + 6, y: yLoc + laneLoc - 4, class: 'c-loc-label' }, v.place_name));
        });
        s.appendChild(svg('text', { x: padL - 6, y: yLoc + laneLoc - 4, 'text-anchor': 'end', class: 'c-axis' }, 'Maps'));
      }
      // events lane
      const checksByEvent = {}; (o.checks || []).forEach(c => { if (c.event_id) checksByEvent[c.event_id] = c; });
      const sorted = (o.events || []).slice().sort((a, b) => (a.start < b.start ? -1 : 1));
      sorted.forEach(ev => {
        const a = Math.max(0, Charts.minuteOf(ev.start, o.date)), b = Math.min(1440, Charts.minuteOf(ev.end, o.date));
        if (b <= a) return;
        const color = SL.palette.event(ev.type);
        const g = svg('g', { class: 'c-evt c-evt-' + ev.type + (ev.attended === false ? ' unattended' : '') });
        const rectAttrs = { x: x(a), y: yEv, width: Math.max(3, x(b) - x(a) - 2), height: laneEv, rx: 5, fill: color, opacity: ev.attended === false ? 0.35 : 0.9 };
        if (ev.type === 'protected') { rectAttrs.fill = 'transparent'; rectAttrs.stroke = cssVar('--evt-protected'); rectAttrs['stroke-width'] = 1.5; rectAttrs['stroke-dasharray'] = '4 3'; }
        if (ev.attended === false) { rectAttrs.stroke = color; rectAttrs['stroke-width'] = 1.5; rectAttrs['stroke-dasharray'] = '3 3'; rectAttrs.fill = 'transparent'; }
        g.appendChild(svg('rect', rectAttrs));
        const wpx = x(b) - x(a);
        if (!compact || wpx > 40) {
          const iconPath = SL.icons[SL.eventIcon(ev.type)] || SL.icons.dot;
          const ig = svg('g', { transform: `translate(${x(a) + 5} ${yEv + (laneEv - 14) / 2}) scale(${14 / 24})`, fill: 'none', stroke: ev.type === 'protected' || ev.attended === false ? cssVar('--ink-primary') : (ev.type === 'focus' ? '#1B1F3B' : '#FFFFFF'), 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
          ig.innerHTML = iconPath; // trusted constant icon markup
          g.appendChild(ig);
          if (wpx > 56) {
            const t = svg('text', { x: x(a) + 22, y: yEv + laneEv / 2 + 4, class: 'c-evt-label', fill: ev.type === 'protected' || ev.attended === false ? cssVar('--ink-primary') : (ev.type === 'focus' ? '#1B1F3B' : '#FFFFFF') }, ev.title);
            g.appendChild(svg('clipPath', { id: 'clip-' + ev.id }, svg('rect', { x: x(a), y: yEv, width: Math.max(0, wpx - 6), height: laneEv })));
            t.setAttribute('clip-path', `url(#clip-${ev.id})`);
            g.appendChild(t);
          }
        }
        if (checksByEvent[ev.id]) {
          const c = checksByEvent[ev.id];
          g.appendChild(svg('circle', { cx: x(b) - 6, cy: yEv + 6, r: 5, fill: c.status === 'open' ? cssVar('--status-warning') : (c.status === 'no' ? cssVar('--status-critical') : cssVar('--status-good')), stroke: cssVar('--card'), 'stroke-width': 2 }));
        }
        g.addEventListener('pointermove', (e) => showTip(e.clientX, e.clientY, minuteLabel(a) + '–' + minuteLabel(b), [{ label: SL.EVENT_LABELS[ev.type] || ev.type, value: ev.title, color }].concat(ev.attended === false ? [{ label: 'status', value: 'not attended' }] : []).concat(checksByEvent[ev.id] ? [{ label: 'reality check', value: checksByEvent[ev.id].status }] : [])));
        g.addEventListener('pointerleave', hideTip);
        s.appendChild(g);
      });
      s.appendChild(svg('text', { x: padL - 6, y: yEv + laneEv / 2 + 4, 'text-anchor': 'end', class: 'c-axis' }, 'Calendar'));
      if (!compact) s.appendChild(svg('text', { x: padL - 6, y: yHr - 2, 'text-anchor': 'end', class: 'c-axis' }, 'bpm'));
      // cursor + hover
      cursorLine = svg('line', { x1: x(cursorMin || 0), x2: x(cursorMin || 0), y1: padT, y2: yHr + hrH, stroke: cssVar('--accent'), 'stroke-width': 2, opacity: cursorMin === null ? 0 : 1, class: 'c-cursor' });
      s.appendChild(cursorLine);
      const hover = svg('line', { x1: 0, x2: 0, y1: padT, y2: yHr + hrH, stroke: cssVar('--hairline-strong'), opacity: 0 });
      s.appendChild(hover);
      const rect = svg('rect', { x: padL, y: yHr, width: W - padL - padR, height: hrH, fill: 'transparent', style: { cursor: o.onSeek ? 'pointer' : 'default' } });
      const minuteAt = (e) => { const b = s.getBoundingClientRect(); const px = (e.clientX - b.left) * (W / b.width); return Math.max(0, Math.min(1439, Math.round(((px - padL) / (W - padL - padR)) * 1440))); };
      rect.addEventListener('pointermove', (e) => {
        const m = minuteAt(e); hover.setAttribute('x1', x(m)); hover.setAttribute('x2', x(m)); hover.setAttribute('opacity', 1);
        const info = api.valueAt(m);
        const rows = [{ label: 'heart rate', value: info.hr === null ? '–' : info.hr + ' bpm', color: cssVar('--series-1') }];
        if (info.norm !== null) rows.push({ label: 'your norm', value: Math.round(info.norm) + ' bpm', color: cssVar('--ink-muted') });
        if (info.event) rows.push({ label: SL.EVENT_LABELS[info.event.type] || 'event', value: info.event.title, color: SL.palette.event(info.event.type) });
        if (info.place) rows.push({ label: 'place', value: info.place.place_name });
        showTip(e.clientX, e.clientY, minuteLabel(m), rows);
        if (o.onHover) o.onHover(m, info);
      });
      rect.addEventListener('pointerleave', () => { hover.setAttribute('opacity', 0); hideTip(); });
      if (o.onSeek) rect.addEventListener('click', (e) => o.onSeek(minuteAt(e)));
      s.appendChild(rect);
      elm.appendChild(s);
      geom = { x };
    }
    const api = {
      update: (n) => { o = Object.assign({}, o, n); if (n && n.cursorMinute !== undefined) cursorMin = n.cursorMinute; render(); },
      destroy: () => { if (unbind) unbind(); SL.clear(elm); },
      setCursor: (m) => { cursorMin = m; if (cursorLine && geom) { cursorLine.setAttribute('x1', geom.x(m)); cursorLine.setAttribute('x2', geom.x(m)); cursorLine.setAttribute('opacity', m === null ? 0 : 1); } },
      valueAt: (m) => {
        const hr = (o.hr || [])[m]; const norm = (o.norm || [])[m];
        const ev = (o.events || []).find(e => e.attended !== false && Charts.minuteOf(e.start, o.date) <= m && Charts.minuteOf(e.end, o.date) > m) || null;
        const place = (o.visits || []).find(v => Charts.minuteOf(v.start, o.date) <= m && Charts.minuteOf(v.end, o.date) > m) || null;
        return { hr: hr === undefined ? null : hr, norm: norm === undefined ? null : norm, event: ev, place };
      },
    };
    render(); unbind = bind(elm, render);
    return api;
  };

  // ------------------------------------------------------------- heat strip
  Charts.heatStrip = function (elm, opts) {
    let o = opts; let unbind = null;
    const binColor = (score) => score === null || score === undefined ? null : (score < 60 ? cssVar('--seq-6') : score < 70 ? cssVar('--seq-5') : score < 80 ? cssVar('--seq-4') : score < 90 ? cssVar('--seq-3') : cssVar('--seq-2'));
    function render() {
      SL.clear(elm);
      const days = (o.days || []).slice().sort((a, b) => (a.date < b.date ? -1 : 1));
      if (!days.length) { elm.appendChild(el('div', { class: 'c-empty muted' }, 'No nights yet')); return; }
      const first = SL.date.parse(days[0].date); const offset = (first.getDay() + 6) % 7; // Monday = 0
      const cols = Math.ceil((days.length + offset) / 7);
      const W = o.width || width(elm, 700), cell = Math.max(10, Math.min(22, Math.floor((W - 40) / cols) - 3)), gapPx = 3, padL = 34, padT = 18;
      const H = padT + 7 * (cell + gapPx) + 4;
      const s = svg('svg', { class: 'c-heat', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': 'Sleep score by night' });
      ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach((d, i) => { if (i % 2 === 0) s.appendChild(svg('text', { x: padL - 8, y: padT + i * (cell + gapPx) + cell - 3, 'text-anchor': 'end', class: 'c-axis' }, d)); });
      let lastMonth = null;
      days.forEach((day, i) => {
        const idx = i + offset, col = Math.floor(idx / 7), row = idx % 7;
        const cx = padL + col * (cell + gapPx), cy = padT + row * (cell + gapPx);
        const dt = SL.date.parse(day.date);
        if (dt.getMonth() !== lastMonth && row === 0) { s.appendChild(svg('text', { x: cx, y: padT - 6, class: 'c-axis' }, dt.toLocaleString('en', { month: 'short' }))); lastMonth = dt.getMonth(); }
        const color = day.worn ? binColor(day.score) : null;
        const r = svg('rect', { x: cx, y: cy, width: cell, height: cell, rx: 3, fill: color || cssVar('--card-3'), class: 'c-heat-cell' + (o.onSelect ? ' clickable' : ''), 'data-date': day.date });
        if (!day.worn) r.setAttribute('fill', 'url(#hatch-heat)');
        r.addEventListener('pointermove', (e) => showTip(e.clientX, e.clientY, SL.fmt.dayLong(day.date), [{ label: 'sleep score', value: day.worn ? String(day.score) : 'watch not worn', color: color || cssVar('--ink-muted') }].concat(day.is_weekend ? [{ label: 'night', value: 'weekend' }] : [])));
        r.addEventListener('pointerleave', hideTip);
        if (o.onSelect) r.addEventListener('click', () => o.onSelect(day));
        s.appendChild(r);
        if (day.worn && cell >= 18) s.appendChild(svg('text', { x: cx + cell / 2, y: cy + cell / 2 + 3.5, 'text-anchor': 'middle', class: 'c-heat-value' }, String(day.score)));
      });
      const defs = svg('defs', null, svg('pattern', { id: 'hatch-heat', width: 5, height: 5, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, svg('rect', { width: 5, height: 5, fill: cssVar('--card-3') }), svg('line', { x1: 0, y1: 0, x2: 0, y2: 5, stroke: cssVar('--hairline-strong'), 'stroke-width': 2 })));
      s.insertBefore(defs, s.firstChild);
      elm.appendChild(s);
      elm.appendChild(el('div', { class: 'c-legend' }, [['< 60', cssVar('--seq-6')], ['60–69', cssVar('--seq-5')], ['70–79', cssVar('--seq-4')], ['80–89', cssVar('--seq-3')], ['90+', cssVar('--seq-2')]].map(([lab, c]) => el('span', { class: 'c-legend-item' }, el('span', { class: 'c-legend-swatch', style: { background: c } }), lab)).concat([el('span', { class: 'c-legend-item' }, el('span', { class: 'c-legend-swatch c-hatch' }), 'watch not worn')])));
    }
    render(); unbind = bind(elm, render);
    return { update: (n) => { o = Object.assign({}, o, n); render(); }, destroy: () => { unbind(); SL.clear(elm); } };
  };

  // --------------------------------------------------------------- scatter
  Charts.scatter = function (elm, opts) {
    let o = opts; let unbind = null;
    function render() {
      SL.clear(elm);
      const pts = (o.points || []).filter(p => p.x !== null && p.y !== null && p.x !== undefined && p.y !== undefined);
      const W = o.width || width(elm, 480), H = o.height || 300, padL = 44, padR = 16, padT = 12, padB = 40;
      const all = pts.flatMap(p => [p.x, p.y, p.lo, p.hi]).filter(v => v !== null && v !== undefined && isFinite(v));
      let lo = Math.min(0, ...all), hi = Math.max(0, ...all); const pad = Math.max(1, (hi - lo) * 0.12); lo -= pad; hi += pad;
      const x = (v) => padL + ((v - lo) / (hi - lo)) * (W - padL - padR);
      const y = (v) => padT + (H - padT - padB) - ((v - lo) / (hi - lo)) * (H - padT - padB);
      const s = svg('svg', { class: 'c-scatter', viewBox: `0 0 ${W} ${H}`, width: W, height: H });
      niceTicks(lo, hi, 5).forEach(t => {
        s.appendChild(svg('line', { x1: padL, x2: W - padR, y1: y(t), y2: y(t), stroke: cssVar('--grid') }));
        s.appendChild(svg('line', { x1: x(t), x2: x(t), y1: padT, y2: H - padB, stroke: cssVar('--grid') }));
        s.appendChild(svg('text', { x: padL - 8, y: y(t) + 4, 'text-anchor': 'end', class: 'c-axis tabular' }, SL.fmt.signed(t, 0)));
        s.appendChild(svg('text', { x: x(t), y: H - padB + 16, 'text-anchor': 'middle', class: 'c-axis tabular' }, SL.fmt.signed(t, 0)));
      });
      if (o.identity) s.appendChild(svg('line', { x1: x(lo), y1: y(lo), x2: x(hi), y2: y(hi), stroke: cssVar('--axis'), 'stroke-width': 1.5 }));
      s.appendChild(svg('line', { x1: x(0), x2: x(0), y1: padT, y2: H - padB, stroke: cssVar('--axis') }));
      s.appendChild(svg('line', { x1: padL, x2: W - padR, y1: y(0), y2: y(0), stroke: cssVar('--axis') }));
      pts.forEach(p => {
        const color = p.color || cssVar('--series-2');
        if (p.lo !== null && p.lo !== undefined && p.hi !== null && p.hi !== undefined) s.appendChild(svg('line', { x1: x(p.x), x2: x(p.x), y1: y(p.lo), y2: y(p.hi), stroke: color, 'stroke-width': 1.5, opacity: 0.7 }));
        const c = svg('circle', { cx: x(p.x), cy: y(p.y), r: 6, fill: p.hollow ? cssVar('--card') : color, stroke: p.hollow ? color : cssVar('--card'), 'stroke-width': 2 });
        c.addEventListener('pointermove', (e) => showTip(e.clientX, e.clientY, p.label, [{ label: o.xLabel || 'x', value: SL.fmt.signed(p.x, 1) }, { label: o.yLabel || 'y', value: SL.fmt.signed(p.y, 1), color }].concat(p.lo !== undefined && p.lo !== null ? [{ label: '95 % interval', value: SL.fmt.signed(p.lo, 1) + ' to ' + SL.fmt.signed(p.hi, 1) }] : [])));
        c.addEventListener('pointerleave', hideTip);
        s.appendChild(c);
        if (p.label && !p.hollow && pts.length <= 12) s.appendChild(svg('text', { x: x(p.x) + 9, y: y(p.y) - 8, class: 'c-label small' }, p.label));
      });
      s.appendChild(svg('text', { x: (padL + W - padR) / 2, y: H - 6, 'text-anchor': 'middle', class: 'c-axis' }, o.xLabel || ''));
      s.appendChild(svg('text', { x: 12, y: (padT + H - padB) / 2, 'text-anchor': 'middle', class: 'c-axis', transform: `rotate(-90 12 ${(padT + H - padB) / 2})` }, o.yLabel || ''));
      elm.appendChild(s);
    }
    render(); unbind = bind(elm, render);
    return { update: (n) => { o = Object.assign({}, o, n); render(); }, destroy: () => { unbind(); SL.clear(elm); } };
  };

  // ---------------------------------------------------------------- stages
  Charts.stages = function (elm, opts) {
    let o = opts;
    const KIND_COLOR = { deep: '--sleep-deep', core: '--sleep-core', rem: '--sleep-rem', awake: '--sleep-awake' };
    function render() {
      SL.clear(elm);
      const night = o.night;
      if (!night || !night.worn || !night.stages || !night.stages.length) { elm.appendChild(el('div', { class: 'c-empty muted small' }, 'No stage data')); return; }
      const W = o.width || width(elm, 480), H = 34;
      const t0 = new Date(night.stages[0].start).getTime(), t1 = new Date(night.stages[night.stages.length - 1].end).getTime();
      const x = (t) => ((t - t0) / Math.max(1, t1 - t0)) * W;
      const s = svg('svg', { class: 'c-stages', viewBox: `0 0 ${W} ${H}`, width: W, height: H });
      night.stages.forEach(st => {
        const a = new Date(st.start).getTime(), b = new Date(st.end).getTime();
        const r = svg('rect', { x: x(a) + 1, y: 4, width: Math.max(1, x(b) - x(a) - 2), height: 24, rx: 3, fill: cssVar(KIND_COLOR[st.kind] || '--ink-muted') });
        r.addEventListener('pointermove', (e) => showTip(e.clientX, e.clientY, SL.fmt.hm(st.start) + '–' + SL.fmt.hm(st.end), [{ label: st.kind, value: SL.fmt.minutes((b - a) / 60000), color: cssVar(KIND_COLOR[st.kind]) }]));
        r.addEventListener('pointerleave', hideTip);
        s.appendChild(r);
      });
      elm.appendChild(s);
      elm.appendChild(el('div', { class: 'c-legend' }, [['deep', night.deep_min], ['core', night.core_min], ['rem', night.rem_min], ['awake', night.awake_min]].map(([k, m]) => el('span', { class: 'c-legend-item' }, el('span', { class: 'c-legend-swatch', style: { background: cssVar(KIND_COLOR[k]) } }), k.toUpperCase() === 'REM' ? 'REM' : k, el('span', { class: 'muted' }, ' ' + SL.fmt.minutes(m))))));
    }
    render();
    return { update: (n) => { o = Object.assign({}, o, n); render(); }, destroy: () => SL.clear(elm) };
  };

  // ----------------------------------------------------------------- table
  Charts.table = function (elm, columns, rows) {
    SL.clear(elm);
    const t = el('table', { class: 'data c-table' },
      el('thead', null, el('tr', null, columns.map(c => el('th', { class: c.num ? 'num' : '' }, c.label)))),
      el('tbody', null, rows.map(r => el('tr', null, columns.map(c => el('td', { class: c.num ? 'num' : '' }, r[c.key] === null || r[c.key] === undefined ? '–' : String(r[c.key])))))));
    elm.appendChild(t);
    return { update: (c, r) => Charts.table(elm, c, r), destroy: () => SL.clear(elm) };
  };

  window.Charts = Charts;
})();
