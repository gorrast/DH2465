'use strict';
/* Replay view: the day as the watch saw it, against the calendar and Maps (SPEC §9.4). */
(function () {
  const el = SL.el;
  const minuteLabel = (m) => { const mm = ((m % 1440) + 1440) % 1440; return String(mm / 60 | 0).padStart(2, '0') + ':' + String(mm % 60).padStart(2, '0'); };

  async function render(container, { params, query }) {
    const date = params[0] || SL.date.addDays(SL.date.today(), -1);
    const meta = SL.meta();
    container.appendChild(el('div', { class: 'view-head' }, el('div', null, el('div', { class: 'eyebrow' }, 'Replay'), el('h1', null, SL.fmt.dayLong(date))),
      el('div', { class: 'date-nav' },
        el('button', { class: 'btn btn-icon btn-ghost', type: 'button', 'aria-label': 'Previous day', disabled: meta.start && date <= meta.start, onclick: () => SL.router.go('#/replay/' + SL.date.addDays(date, -1)) }, SL.icon('chevron-left')),
        el('span', { class: 'date-label' }, date === SL.date.addDays(SL.date.today(), -1) ? 'Yesterday' : SL.fmt.day(date)),
        el('button', { class: 'btn btn-icon btn-ghost', type: 'button', 'aria-label': 'Next day', disabled: date >= SL.date.today(), onclick: () => SL.router.go('#/replay/' + SL.date.addDays(date, 1)) }, SL.icon('chevron-right')))));
    const body = el('div', { class: 'v-replay stack' }); container.appendChild(body);
    body.appendChild(el('div', { class: 'skeleton', style: { height: '300px' } }));
    let day;
    try { day = await SL.api.get('/api/day/' + date); } catch (e) { SL.clear(body); body.appendChild(el('div', { class: 'card empty' }, el('h2', null, 'No data for this day'), el('p', null, e.message))); return; }
    SL.clear(body);
    const attended = day.events.filter(e => e.attended !== false);
    const firstEvent = attended.length ? Math.min(...attended.map(e => Charts.minuteOf(e.start, date))) : 6 * 60;
    let cursor = query.t ? Math.max(0, Math.min(1439, +query.t)) : Math.max(0, Math.min(firstEvent - 30, 6 * 60));
    let speed = 16, playing = false, raf = null, last = null, stopAt = null;

    // watch face
    const face = {
      time: el('div', { class: 'v-replay-face-time' }, '--:--'), hr: el('div', { class: 'v-replay-face-hr' }, '–'), norm: el('div', { class: 'v-replay-face-norm muted small' }, ''),
      event: el('div', { class: 'v-replay-face-event' }), place: el('div', { class: 'v-replay-face-place muted small' }),
    };
    const faceCard = el('div', { class: 'card v-replay-facecard', 'data-tour': 'watchface' },
      el('div', { class: 'v-replay-face' }, face.time, el('div', { class: 'row', style: { alignItems: 'baseline', gap: '4px', justifyContent: 'center' } }, SL.icon('heart', { size: 16, class: 'v-replay-heart' }), face.hr, el('span', { class: 'tiny muted' }, 'bpm')), face.norm),
      face.event, face.place);
    const timelineBox = el('div', { class: 'v-replay-timeline' });
    const scrub = el('input', { type: 'range', min: 0, max: 1439, value: cursor, 'aria-label': 'Time of day', oninput: (e) => seek(+e.target.value) });
    const playBtn = el('button', { class: 'btn btn-primary', type: 'button', onclick: () => (playing ? pause() : play()) }, SL.icon('play', { size: 16 }), 'Play');
    const speedSeg = el('div', { class: 'segmented' }, [4, 16, 64].map(sp => el('button', { type: 'button', class: sp === speed ? 'active' : '', 'data-speed': sp, onclick: () => setSpeed(sp) }, sp + 'x')));
    const chapter = (label, fn) => el('button', { class: 'btn btn-sm', type: 'button', onclick: fn }, label);
    const transport = el('div', { class: 'row v-replay-transport', 'data-tour': 'transport' }, playBtn, speedSeg,
      chapter('Next event', () => { const nxt = attended.map(e => Charts.minuteOf(e.start, date)).filter(m => m > cursor + 1).sort((a, b) => a - b)[0]; if (nxt !== undefined) seek(Math.max(0, nxt - 15)); }),
      chapter('Evening', () => seek(17 * 60)),
      chapter('Bedtime', () => { const b = day.night && day.night.worn ? Charts.minuteOf(day.night.in_bed_start, date) : 23 * 60; seek(Math.max(0, Math.min(1439, b - 20))); }),
      el('span', { class: 'tiny muted' }, 'minutes per second'));
    const scrubRow = el('div', { class: 'v-replay-scrub' }, scrub);
    body.appendChild(el('div', { class: 'v-replay-grid' },
      faceCard,
      el('div', { class: 'card v-replay-main', 'data-tour': 'timeline' }, el('div', { class: 'card-title' }, el('h3', null, 'The day, minute by minute'), el('span', { class: 'row tiny muted' }, day.chips.map(c => el('span', { class: 'chip' }, c)))), timelineBox, scrubRow, transport,
        el('div', { class: 'tiny muted' }, 'Coral line: heart rate. Dotted: your usual heart rate at that hour on calm evenings. Shaded: above your norm. Blue shading: asleep. Dashed outline: booked but not attended.'))));
    const tl = Charts.dayTimeline(timelineBox, { date, events: day.events, visits: day.visits, hr: day.hr, norm: day.norm, night: day.night, nightPrev: day.night_prev, workouts: day.workouts, checks: day.checks, cursorMinute: cursor, onSeek: (m) => seek(m) });

    // side panel: events + night
    const checksByEvent = {}; day.checks.forEach(c => { if (c.event_id) checksByEvent[c.event_id] = c; });
    const evList = el('ul', { class: 'list v-replay-events' }, day.events.map(ev => {
      const r = day.responses[ev.id];
      const chk = checksByEvent[ev.id];
      return el('li', { class: 'list-item v-replay-event' + (ev.attended === false ? ' unattended' : ''), onclick: () => seek(Math.max(0, Charts.minuteOf(ev.start, date) - 5)) },
        el('span', { class: 'v-replay-evt-swatch', style: { background: SL.palette.event(ev.type) } }, SL.icon(SL.eventIcon(ev.type), { size: 14 })),
        el('div', { class: 'body' },
          el('div', { class: 'row between' }, el('span', { class: 'title' }, ev.title), el('span', { class: 'tiny muted tabular' }, SL.fmt.hm(ev.start) + '–' + SL.fmt.hm(ev.end))),
          el('div', { class: 'row tiny' },
            ev.attended === false ? el('span', { class: 'badge badge-critical' }, 'not attended') : null,
            ev.source === 'user' ? el('span', { class: 'badge badge-accent' }, 'added by you') : null,
            r && r.delta_during !== null && r.delta_during !== undefined ? el('span', { class: 'chip' }, SL.fmt.signed(r.delta_during, 0) + ' bpm during') : null,
            r && r.elevated_until ? el('span', { class: 'chip' }, 'elevated until ' + SL.fmt.hm(r.elevated_until)) : null,
            chk ? el('a', { class: 'badge badge-' + (chk.status === 'open' ? 'warning' : chk.status === 'no' ? 'critical' : 'good'), href: '#/reality' }, chk.status === 'open' ? 'reality check' : 'checked: ' + chk.status) : null)));
    }));
    const n = day.night;
    const nightCard = el('div', { class: 'card v-replay-night' }, el('div', { class: 'card-title' }, el('h3', null, 'The night after'), el('a', { class: 'small', href: '#/morning/' + SL.date.addDays(date, 1) }, 'Explain this night →')),
      n && n.worn ? el('div', { class: 'row' }, el('span', { class: 'chip' }, 'Score ' + n.score), el('span', { class: 'chip' }, 'In bed ' + SL.fmt.hm(n.in_bed_start)), el('span', { class: 'chip' }, 'Asleep ' + SL.fmt.minutes(n.duration_min)), el('span', { class: 'chip' }, 'HRV ' + SL.fmt.num(n.hrv_ms, 0) + ' ms'), el('span', { class: 'chip' }, 'RHR ' + n.resting_hr + ' bpm')) : el('p', { class: 'muted small' }, day.is_today ? 'Tonight has not happened yet.' : 'The watch was not worn this night.'));
    const evening = day.evening;
    body.appendChild(el('div', { class: 'grid grid-3' },
      el('div', { class: 'card span-2' }, el('div', { class: 'card-title' }, el('h3', null, 'Calendar vs body'), el('span', { class: 'tiny muted' }, 'click an event to jump there')), evList),
      el('div', { class: 'stack' }, nightCard,
        evening && evening.delta !== null && evening.delta !== undefined ? el('div', { class: 'card soft' }, el('h4', null, 'Evening, 20:00–23:00'), el('p', { class: 'small' }, 'Heart rate ' + SL.fmt.signed(evening.delta, 0) + ' bpm vs your calm-evening norm' + (evening.elevated_until ? ', elevated until ' + SL.fmt.hm(evening.elevated_until) : '') + '.')) : null)));

    // playback
    function paintFace(m) {
      const info = tl.valueAt(m);
      face.time.textContent = minuteLabel(m);
      face.hr.textContent = info.hr === null ? '–' : String(info.hr);
      face.norm.textContent = (info.hr !== null && info.norm !== null) ? SL.fmt.signed(info.hr - Math.round(info.norm), 0) + ' vs norm' : (info.hr === null ? 'watch not worn' : '');
      SL.clear(face.event);
      if (info.event) { face.event.appendChild(SL.icon(SL.eventIcon(info.event.type), { size: 14 })); face.event.appendChild(el('span', null, info.event.title)); face.event.style.color = SL.palette.event(info.event.type); }
      else { face.event.appendChild(el('span', { class: 'muted' }, m < 6 * 60 || (day.night && day.night.worn && Charts.minuteOf(day.night.in_bed_start, date) <= m) ? 'Asleep' : 'Free time')); face.event.style.color = ''; }
      face.place.textContent = info.place ? info.place.place_name : '';
      faceCard.classList.toggle('pulse', playing && info.hr !== null && info.hr > 100);
    }
    function seek(m) { cursor = Math.max(0, Math.min(1439, Math.round(m))); scrub.value = cursor; tl.setCursor(cursor); paintFace(cursor); }
    function tick(ts) {
      if (!playing) return;
      if (last !== null) {
        cursor += ((ts - last) / 1000) * speed;
        if (cursor >= 1439 || (stopAt !== null && cursor >= stopAt)) { cursor = Math.min(1439, stopAt !== null ? stopAt : 1439); seek(cursor); pause(); return; }
        seek(cursor);
      }
      last = ts; raf = requestAnimationFrame(tick);
    }
    function play(sp) { if (sp) setSpeed(sp); playing = true; last = null; SL.clear(playBtn); playBtn.appendChild(SL.icon('pause', { size: 16 })); playBtn.appendChild(document.createTextNode('Pause')); raf = requestAnimationFrame(tick); }
    function pause() { playing = false; stopAt = null; if (raf) cancelAnimationFrame(raf); raf = null; SL.clear(playBtn); playBtn.appendChild(SL.icon('play', { size: 16 })); playBtn.appendChild(document.createTextNode('Play')); faceCard.classList.remove('pulse'); }
    function setSpeed(sp) { speed = sp; Array.from(speedSeg.children).forEach(b => b.classList.toggle('active', +b.dataset.speed === sp)); }
    SL.replay = { play, pause, seek, playRange: (from, to, sp) => { seek(from); stopAt = to; play(sp); } };
    seek(cursor);
    return () => { pause(); SL.replay = null; };
  }
  SL.router.register('replay', { title: 'Replay', render });
})();
