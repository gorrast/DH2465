'use strict';
/* Morning report view (SPEC §9.4). */
(function () {
  const el = SL.el;
  const state = { revealed: false };

  function badge(conf) { return el('span', { class: 'badge badge-' + conf }, conf); }
  function pts(v, lo, hi) {
    return el('span', { class: 'chip pts ' + (v < 0 ? 'pts-neg' : 'pts-pos'), title: (lo !== null && lo !== undefined) ? 'likely ' + SL.fmt.signed(lo, 0) + ' to ' + SL.fmt.signed(hi, 0) + ' points' : '' }, SL.fmt.signed(v, 1) + ' pts');
  }
  function chip(text, icon) { return el('span', { class: 'chip' }, icon ? SL.icon(icon, { size: 13 }) : null, text); }

  function causeItem(c, expandedDefault) {
    const evidenceBox = el('div', { class: 'v-morning-evidence' });
    let expanded = !!expandedDefault;
    const paint = () => {
      SL.clear(evidenceBox);
      if (!expanded) return;
      c.evidence.forEach(ev => {
        evidenceBox.appendChild(el('div', { class: 'v-morning-evidence-row' }, SL.icon({ hr: 'pulse', hrv: 'heart', rhr: 'heart', bedtime: 'bed', duration: 'moon', interruptions: 'bed', temp: 'thermometer', location: 'map', calendar: 'calendar', resp: 'lungs', spo2: 'drop' }[ev.kind] || 'info', { size: 14 }), el('span', null, ev.text)));
        if (ev.series && ev.series.length) {
          const box = el('div', { class: 'v-morning-spark' });
          evidenceBox.appendChild(box);
          Charts.sparkline(box, { values: ev.series, norm: ev.series_baseline || null, start: ev.series_start, stepMin: ev.series_step_min || 5, height: 64, unit: ev.unit || '', label: ev.kind === 'hr' ? 'heart rate' : ev.kind, digits: 0 });
          if (ev.series_baseline) evidenceBox.appendChild(el('div', { class: 'tiny muted' }, 'Solid: last night · dotted: your usual at that hour · shaded: above your norm'));
        }
      });
    };
    const toggle = el('button', { class: 'btn btn-ghost btn-sm v-morning-toggle', type: 'button', onclick: () => { expanded = !expanded; toggle.textContent = expanded ? 'Hide evidence' : 'Show evidence'; paint(); } }, expanded ? 'Hide evidence' : 'Show evidence');
    paint();
    return el('li', { class: 'list-item v-morning-cause', 'data-factor': c.factor },
      el('span', { class: 'num' }, String(c.rank)),
      el('div', { class: 'body' },
        el('div', { class: 'row between' }, el('span', { class: 'title' }, c.title), el('span', { class: 'row' }, pts(c.points, c.points_low, c.points_high), badge(c.confidence))),
        el('div', { class: 'detail' }, c.detail),
        el('div', { class: 'row tiny muted' }, c.n_similar ? el('span', null, c.n_similar + ' similar nights in your history') : null, (c.evidence && c.evidence.length) ? toggle : null),
        evidenceBox));
  }

  function suggestionCard(s, morning) {
    const actions = el('div', { class: 'row v-morning-sugg-actions' });
    const paintAccepted = () => {
      SL.clear(actions);
      actions.appendChild(el('span', { class: 'row v-morning-added' }, SL.icon('check', { size: 16 }), 'Added to your calendar'));
      actions.appendChild(el('a', { class: 'btn btn-sm', href: '/api/suggestions/' + morning + '/' + s.id + '.ics', download: 'stressless-' + s.id + '.ics' }, SL.icon('download', { size: 14 }), 'Download .ics'));
      actions.appendChild(el('a', { class: 'btn btn-sm btn-ghost', href: '#/planner/' + morning }, 'See it in the Planner'));
    };
    if (s.accepted) paintAccepted();
    else if (s.proposed_event) {
      const btn = el('button', { class: 'btn btn-primary', type: 'button', onclick: async () => {
        btn.disabled = true;
        try { await SL.api.post('/api/suggestions/' + morning + '/' + s.id + '/accept'); s.accepted = true; paintAccepted(); SL.toast('Added "' + s.proposed_event.title + '" to tonight', { kind: 'success' }); }
        catch (e) { btn.disabled = false; SL.toast('Could not add: ' + e.message, { kind: 'error' }); }
      } }, SL.icon('calendar', { size: 16 }), 'Add to calendar');
      actions.appendChild(btn);
    } else {
      actions.appendChild(el('a', { class: 'btn', href: '#/planner/' + (s.for_date || morning) }, SL.icon('planner', { size: 16 }), 'Try it in the Planner'));
    }
    const range = (s.gain_low !== null && s.gain_low !== undefined) ? ' · likely ' + SL.fmt.signed(s.gain_low, 0) + ' to ' + SL.fmt.signed(s.gain_high, 0) + ' points' : '';
    return el('div', { class: 'card accent v-morning-sugg', 'data-tour': 'suggestion' },
      el('div', { class: 'eyebrow' }, 'Suggestion' + range), el('h3', null, s.title), el('p', { class: 'small' }, s.body), actions);
  }

  function statTile(m) {
    const icon = { hrv_ms: 'heart', resting_hr: 'pulse', wrist_temp_dev: 'thermometer', resp_rate: 'lungs', spo2: 'drop' }[m.key] || 'info';
    const fmtValue = (v) => v === null || v === undefined ? '–' : (m.key === 'wrist_temp_dev' ? SL.fmt.signed(v, 1) : m.key === 'spo2' ? SL.fmt.num(v, 1) : m.key === 'hrv_ms' ? SL.fmt.num(v, 0) : m.key === 'resp_rate' ? SL.fmt.num(v, 1) : SL.fmt.num(v, 0));
    const delta = m.delta === null || m.delta === undefined ? null : (m.key === 'hrv_ms' && m.delta_pct !== null && m.delta_pct !== undefined ? SL.fmt.pct(m.delta_pct, 0) : SL.fmt.signed(m.delta, (m.key === 'wrist_temp_dev' || m.key === 'resp_rate' || m.key === 'spo2') ? 1 : 0) + ' ' + m.unit);
    const tile = el('div', { class: 'stat-tile v-morning-tile' },
      el('div', { class: 'label' }, SL.icon(icon, { size: 14 }), m.label),
      el('div', { class: 'value' }, fmtValue(m.value), el('small', null, m.unit)),
      el('div', { class: 'delta' }, delta === null ? el('span', { class: 'muted' }, 'no baseline yet') : el('span', null, delta + ' vs baseline'), el('span', { class: 'badge badge-' + m.status }, m.status)),
      el('div', { class: 'trend' }));
    if (m.series && m.series.some(v => v !== null)) Charts.sparkline(tile.querySelector('.trend'), { values: m.series, baseline: m.baseline, height: 32, label: m.label, unit: m.unit, digits: m.key === 'wrist_temp_dev' ? 2 : 1, xLabels: m.series.map((_, i) => (13 - i) === 0 ? 'last night' : (13 - i) + ' nights ago') });
    return tile;
  }

  function dateNav(morning) {
    const today = SL.date.today();
    const meta = SL.meta();
    return el('div', { class: 'date-nav' },
      el('button', { class: 'btn btn-icon btn-ghost', type: 'button', 'aria-label': 'Previous day', disabled: meta.start && morning <= SL.date.addDays(meta.start, 1), onclick: () => SL.router.go('#/morning/' + SL.date.addDays(morning, -1)) }, SL.icon('chevron-left')),
      el('span', { class: 'date-label' }, morning === today ? 'This morning' : SL.fmt.day(morning)),
      el('button', { class: 'btn btn-icon btn-ghost', type: 'button', 'aria-label': 'Next day', disabled: morning >= today, onclick: () => SL.router.go('#/morning/' + SL.date.addDays(morning, 1)) }, SL.icon('chevron-right')),
      morning !== today ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => SL.router.go('#/morning/' + today) }, 'Today') : null);
  }

  function historySelect() {
    const cur = SL.state.get('historyDays');
    const sel = el('select', { class: 'select', 'aria-label': 'Nights of history used', onchange: (e) => SL.state.set('historyDays', e.target.value === 'all' ? null : +e.target.value) },
      [7, 14, 28].map(n => el('option', { value: String(n), selected: cur === n }, n + ' nights')), el('option', { value: 'all', selected: cur === null || cur === undefined }, 'All nights'));
    return el('label', { class: 'row small muted' }, 'History used', sel);
  }

  async function render(container, { params, query }) {
    const morning = params[0] || SL.date.today();
    const hd = SL.state.get('historyDays');
    const veil = query.reveal === '1' && !state.revealed;
    container.appendChild(el('div', { class: 'view-head' }, el('div', null, el('div', { class: 'eyebrow' }, 'Morning report'), el('h1', null, SL.fmt.dayLong(morning))), dateNav(morning)));
    const body = el('div', { class: 'v-morning' }); container.appendChild(body);
    body.appendChild(el('div', { class: 'skeleton', style: { height: '220px' } }));
    let report, day = null;
    try {
      report = await SL.api.get('/api/report/' + morning + (hd ? '?history_days=' + hd : ''));
    } catch (e) {
      SL.clear(body);
      body.appendChild(el('div', { class: 'card empty' }, SL.icon('moon', { size: 28 }), el('h2', null, /No report yet/.test(e.message) ? 'No report yet' : 'No report'), el('p', null, e.message), el('button', { class: 'btn', onclick: () => SL.router.go('#/morning/' + SL.date.today()) }, 'Go to this morning')));
      return;
    }
    try { day = await SL.api.get('/api/day/' + report.night_date); } catch (e) { day = null; }
    SL.clear(body);
    const src = report.sources || {};
    body.appendChild(el('div', { class: 'row v-morning-sources', 'data-tour': 'sources' },
      chip('Calendar · ' + (src.calendar_events || 0) + ' events', 'calendar'), chip('Maps · ' + (src.maps_places || 0) + ' places', 'map'), chip('Watch · ' + (src.watch_minutes || 0).toLocaleString('en') + ' min', 'watch'),
      el('span', { class: 'tiny muted' }, 'yesterday, ' + SL.fmt.day(report.night_date))));

    const night = report.night;
    const asleep = night && night.worn ? SL.fmt.minutes(night.duration_min) : '–';
    const watchCard = el('div', { class: 'card soft v-morning-watch', 'data-tour': 'watch-card' },
      el('div', { class: 'eyebrow' }, 'What your watch says'),
      el('div', { class: 'v-morning-watch-face' },
        el('div', { class: 'v-morning-watch-score' }, SL.fmt.score(report.score)),
        el('div', { class: 'v-morning-watch-meta' }, el('div', { class: 'v-morning-watch-rating' }, report.rating || 'No data'), el('div', { class: 'muted small' }, 'Sleep score'))),
      el('div', { class: 'row v-morning-watch-rows small' }, el('span', null, SL.icon('moon', { size: 14 }), ' Asleep ' + asleep), night && night.worn ? el('span', null, SL.icon('bed', { size: 14 }), ' ' + SL.fmt.hm(night.in_bed_start) + ' → ' + SL.fmt.hm(night.wake_time)) : null),
      el('p', { class: 'v-morning-watch-quote' }, report.score === null ? 'No data for last night.' : 'That’s all your watch tells you.'));
    const ringBox = el('div', { class: 'v-morning-ringbox' });
    const ringCard = el('div', { class: 'card v-morning-ring' }, ringBox,
      el('div', { class: 'v-morning-delta' }, report.delta_vs_baseline === null || report.delta_vs_baseline === undefined ? el('span', { class: 'muted' }, report.baseline_score ? 'Usual ' + SL.fmt.score(report.baseline_score) : 'Building your baseline') : el('span', { class: report.delta_vs_baseline < 0 ? 'pts-neg' : 'pts-pos' }, SL.fmt.signed(report.delta_vs_baseline, 0) + ' vs your usual ' + SL.fmt.score(report.baseline_score))));
    const causesCol = el('div', { class: 'v-morning-causes' + (veil ? ' veiled' : ''), 'data-tour': 'causes' });
    body.appendChild(el('div', { class: 'v-morning-hero', 'data-tour': 'hero' }, watchCard, ringCard, causesCol));
    Charts.ring(ringBox, { value: report.score, label: 'sleep score', sublabel: report.rating, band: Charts.bandFor(report.score), size: 190 });

    const fillCauses = () => {
      SL.clear(causesCol);
      if (report.missing_data) {
        causesCol.appendChild(el('div', { class: 'card' }, el('h3', null, 'No watch data'), el('p', { class: 'secondary' }, report.missing_data), el('p', { class: 'small muted' }, 'Yesterday still counts for your patterns; the day strip below shows what it looked like.')));
      } else if (report.model && report.model.insufficient) {
        causesCol.appendChild(el('div', { class: 'card' }, el('h3', null, 'Building your baseline'), el('p', { class: 'secondary' }, report.confidence_note)));
      } else if (!report.causes.length) {
        causesCol.appendChild(el('div', { class: 'card' }, el('h3', null, 'Nothing in your calendar stands out'), el('p', { class: 'secondary' }, 'A calm day. ' + (report.unexplained_note || ''))));
      } else {
        const list = el('ol', { class: 'list v-morning-cause-list' }, report.causes.map((c, i) => causeItem(c, i === 0 || c.evidence.some(e => e.kind === 'hr' && e.series))));
        causesCol.appendChild(el('div', { class: 'card v-morning-causes-card' }, el('div', { class: 'card-title' }, el('h3', null, report.causes.length === 1 ? 'The likely cause' : (report.causes.length === 2 ? 'Two likely causes' : 'Three likely causes')), el('span', { class: 'tiny muted' }, 'calendar · Maps · watch')), list));
      }
      if (report.helpers && report.helpers.length) causesCol.appendChild(el('div', { class: 'card soft' }, el('h4', null, 'What helped'), el('ul', { class: 'list' }, report.helpers.map(h => el('li', { class: 'row between small' }, el('span', null, el('strong', null, h.title), ' — ', h.detail), pts(h.points, h.points_low, h.points_high))))));
      if (report.suggestions && report.suggestions.length) causesCol.appendChild(suggestionCard(report.suggestions[0], morning));
      Array.from(causesCol.children).forEach((node, i) => { node.classList.add('v-morning-stagger'); node.style.animationDelay = (i * 0.18) + 's'; });
    };
    if (veil) {
      causesCol.appendChild(el('div', { class: 'card v-morning-why' },
        el('p', { class: 'v-morning-why-text' }, 'A number. No explanation.'),
        el('button', { class: 'btn btn-primary v-morning-why-btn', type: 'button', 'data-tour': 'reveal', onclick: () => { state.revealed = true; causesCol.classList.remove('veiled'); fillCauses(); } }, 'Why?')));
    } else {
      fillCauses();
    }

    body.appendChild(el('div', { class: 'card v-morning-narrative', 'data-tour': 'narrative' },
      el('div', { class: 'card-title' }, el('h3', null, 'In plain words'), el('span', { class: 'chip' }, SL.icon('brain', { size: 13 }), report.reasoning_mode === 'claude' ? 'Written by Claude' : 'On-device rules')),
      el('p', null, report.narrative || '—')));

    if (day && day.hr) {
      const strip = el('div', { class: 'v-morning-strip' });
      body.appendChild(el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'Yesterday at a glance'), el('a', { class: 'small', href: '#/replay/' + report.night_date }, 'Open the full replay →')), strip,
        el('div', { class: 'tiny muted' }, 'Calendar blocks above, heart rate below. Dotted: your usual heart rate at that hour; shaded: above it. Click to jump into the replay.')));
      Charts.dayTimeline(strip, { date: day.date, events: day.events, visits: day.visits, hr: day.hr, norm: day.norm, night: day.night, nightPrev: day.night_prev, workouts: day.workouts, checks: day.checks, compact: true, onSeek: (m) => SL.router.go('#/replay/' + report.night_date + '?t=' + m) });
    }

    if (night && night.worn) {
      const primary = report.recovery.filter(m => ['hrv_ms', 'resting_hr', 'wrist_temp_dev'].includes(m.key));
      const more = report.recovery.filter(m => !['hrv_ms', 'resting_hr', 'wrist_temp_dev'].includes(m.key));
      const moreBox = el('div', { class: 'grid grid-3 v-morning-more', hidden: true }, more.map(statTile));
      const moreBtn = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => { moreBox.hidden = !moreBox.hidden; moreBtn.textContent = moreBox.hidden ? 'More markers' : 'Fewer markers'; } }, 'More markers');
      const stagesBox = el('div', { class: 'v-morning-stages' });
      body.appendChild(el('div', { class: 'card', 'data-tour': 'recovery' },
        el('div', { class: 'card-title' }, el('h3', null, 'Last night in numbers'), moreBtn),
        el('div', { class: 'grid grid-3' }, primary.map(statTile)), moreBox,
        el('div', { class: 'divider' }),
        el('div', { class: 'grid grid-2' },
          el('div', null, el('h4', null, 'The night'), el('div', { class: 'row v-morning-nightfacts' },
            chip('In bed ' + SL.fmt.hm(night.in_bed_start), 'bed'), chip('Asleep ' + SL.fmt.hm(night.sleep_onset), 'moon'), chip('Woke ' + SL.fmt.hm(night.wake_time), 'sun'),
            chip(SL.fmt.minutes(night.duration_min) + ' asleep'), chip(night.interruptions + ' interruption' + (night.interruptions === 1 ? '' : 's') + ', ' + SL.fmt.minutes(night.awake_min) + ' awake')), stagesBox),
          el('div', null, el('h4', null, 'Facts from the night'), el('div', { class: 'row' }, report.proximal.map(e => chip(e.text))))),
        night.score_parts ? el('div', { class: 'tiny muted', style: { marginTop: '8px' } }, 'Score parts — duration ' + night.score_parts.duration + '/50 · consistency ' + night.score_parts.consistency + '/30 · interruptions ' + night.score_parts.interruptions + '/20') : null));
      Charts.stages(stagesBox, { night });
    }

    body.appendChild(el('div', { class: 'card soft row between v-morning-footer', 'data-tour': 'confidence' },
      el('span', { class: 'small secondary row' }, SL.icon('info', { size: 14 }), report.confidence_note), historySelect()));
  }

  SL.router.register('morning', { title: 'Morning', render });
})();
