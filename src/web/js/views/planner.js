'use strict';
/* Planner: what-if on today's (or a coming day's) calendar, with a predicted delta and likely range (SPEC §9.4). */
(function () {
  const el = SL.el;
  async function render(container, { params }) {
    const today = SL.date.today();
    const date = params[0] || today;
    const max = SL.date.addDays(today, 7);
    container.appendChild(el('div', { class: 'view-head' }, el('div', null, el('div', { class: 'eyebrow' }, 'Planner'), el('h1', null, date === today ? 'Tonight' : SL.fmt.dayLong(date))),
      el('div', { class: 'date-nav' },
        el('button', { class: 'btn btn-icon btn-ghost', type: 'button', 'aria-label': 'Previous day', disabled: date <= today, onclick: () => SL.router.go('#/planner/' + SL.date.addDays(date, -1)) }, SL.icon('chevron-left')),
        el('span', { class: 'date-label' }, SL.fmt.day(date)),
        el('button', { class: 'btn btn-icon btn-ghost', type: 'button', 'aria-label': 'Next day', disabled: date >= max, onclick: () => SL.router.go('#/planner/' + SL.date.addDays(date, 1)) }, SL.icon('chevron-right')))));
    const body = el('div', { class: 'v-planner stack' }); container.appendChild(body);
    body.appendChild(el('div', { class: 'skeleton', style: { height: '220px' } }));
    let day, report = null;
    try { day = await SL.api.get('/api/day/' + date); } catch (e) { SL.clear(body); body.appendChild(el('div', { class: 'card empty' }, el('h2', null, 'Nothing to plan here'), el('p', null, e.message))); return; }
    if (date === today) { try { report = await SL.api.get('/api/report/' + today); } catch (e) { report = null; } }
    SL.clear(body);
    let mods = [];
    const hero = { delta: el('div', { class: 'v-planner-delta' }, '–'), range: el('div', { class: 'small secondary' }, ''), pred: el('div', { class: 'v-planner-pred' }, ''), chips: el('div', { class: 'row' }) };
    const heroCard = el('div', { class: 'card v-planner-hero', 'data-tour': 'prediction' }, el('div', { class: 'eyebrow' }, 'Predicted change for this night'), hero.delta, hero.range, hero.pred, hero.chips,
      el('div', { class: 'tiny muted' }, 'From your own within-person model. Ranges come from resampling your nights; correlation, not proof.'));
    const list = el('div', { class: 'stack', 'data-tour': 'events' });
    const undo = el('button', { class: 'btn btn-sm', type: 'button', disabled: true, onclick: () => { mods = []; paintList(); recompute(); } }, SL.icon('refresh', { size: 14 }), 'Undo changes');
    const suggBox = el('div', { class: 'stack' });
    body.appendChild(el('div', { class: 'v-planner-grid' }, el('div', { class: 'stack' }, heroCard, suggBox),
      el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'The plan for ' + SL.fmt.day(date)), undo), list, el('div', { class: 'tiny muted', style: { marginTop: '10px' } }, 'Change a block and watch the prediction move. Nothing here edits your real calendar until you accept a suggestion.'))));

    const hourOf = (iso) => { const m = Charts.minuteOf(iso, date); return m / 60; };
    const has = (id, op) => mods.some(m => m.event_id === id && m.op === op);
    const toggleMod = (id, op, extra) => { if (has(id, op)) mods = mods.filter(m => !(m.event_id === id && m.op === op)); else { mods = mods.filter(m => m.event_id !== id); mods.push(Object.assign({ op, event_id: id }, extra || {})); } paintList(); recompute(); };
    const controlsFor = (ev) => {
      const ctl = [];
      const b = (label, op, extra) => ctl.push(el('button', { class: 'btn btn-sm' + (has(ev.id, op) ? ' active btn-primary' : ''), type: 'button', onclick: () => toggleMod(ev.id, op, extra) }, label));
      if (ev.type === 'meeting') { if (hourOf(ev.end) > 18) b('End at 18:00', 'end_at', { hour: 18 }); b('−2 h', 'shift', { hours: -2 }); b('→ Protected', 'to_protected'); }
      else if (ev.type === 'focus') { b('→ Protected', 'to_protected'); }
      else if (ev.type === 'workout') { if (hourOf(ev.start) >= 10) b('Move to 07:00', 'shift', { hours: 7 - hourOf(ev.start) }); }
      b('Remove', 'remove');
      return ctl;
    };
    function paintList() {
      SL.clear(list);
      const evs = day.events.filter(e => e.attended !== false).slice().sort((a, b) => (a.start < b.start ? -1 : 1));
      if (!evs.length) list.appendChild(el('p', { class: 'muted' }, 'An empty day. Add nothing and sleep well.'));
      evs.forEach(ev => {
        const removed = has(ev.id, 'remove');
        list.appendChild(el('div', { class: 'v-planner-event' + (removed ? ' removed' : '') },
          el('span', { class: 'v-planner-swatch', style: { background: SL.palette.event(ev.type) } }, SL.icon(SL.eventIcon(ev.type), { size: 14 })),
          el('div', { class: 'v-planner-event-body' }, el('div', { class: 'row between' }, el('span', { class: 'v-planner-title' }, ev.title, ev.source === 'user' ? el('span', { class: 'badge badge-accent', style: { marginLeft: '8px' } }, 'added by you') : null), el('span', { class: 'tiny muted tabular' }, SL.fmt.hm(ev.start) + '–' + SL.fmt.hm(ev.end))),
            el('div', { class: 'row v-planner-controls' }, controlsFor(ev)))));
      });
      undo.disabled = !mods.length;
    }
    let timer = null;
    function recompute() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        heroCard.classList.add('loading-dim');
        try {
          const w = await SL.api.post('/api/whatif', { date, mods });
          hero.delta.textContent = mods.length ? SL.fmt.signed(w.delta, 0) : '±0';
          hero.delta.className = 'v-planner-delta ' + (w.delta > 0 ? 'pts-pos' : w.delta < 0 ? 'pts-neg' : '');
          hero.range.textContent = mods.length && w.delta_low !== null ? 'likely ' + SL.fmt.signed(w.delta_low, 0) + ' to ' + SL.fmt.signed(w.delta_high, 0) + ' points' : 'Change the plan to see the effect';
          SL.clear(hero.pred); hero.pred.appendChild(el('span', { class: 'muted small' }, 'Predicted sleep score '));
          hero.pred.appendChild(el('strong', null, SL.fmt.score(w.baseline_pred)));
          if (mods.length) { hero.pred.appendChild(el('span', { class: 'muted small' }, ' → ')); hero.pred.appendChild(el('strong', null, SL.fmt.score(w.modified_pred))); }
          hero.pred.appendChild(el('span', { class: 'muted small' }, ' · typical error ±' + SL.fmt.num(w.rmse, 0)));
          SL.clear(hero.chips);
          (w.changed_factors || []).forEach(k => hero.chips.appendChild(el('span', { class: 'chip' }, ({ meetings_over_3: 'meeting load', b2b_over_2: 'back-to-back', late_meeting_hours: 'late meeting', evening_social: 'evening social', workout_morning: 'morning workout', workout_late: 'late workout', travel: 'travel', early_start: 'early start', protected_evening: 'protected evening', is_weekend: 'weekend' })[k] || k)));
        } catch (e) { hero.range.textContent = e.message; }
        heroCard.classList.remove('loading-dim');
      }, 250);
    }
    function paintSuggestions() {
      SL.clear(suggBox);
      if (!report || !report.suggestions.length) return;
      suggBox.appendChild(el('h4', null, 'Suggestions for tonight'));
      report.suggestions.forEach(s => {
        const actions = el('div', { class: 'row' });
        if (s.accepted) actions.appendChild(el('span', { class: 'row small v-planner-added' }, SL.icon('check', { size: 14 }), 'Added'));
        else if (s.proposed_event) actions.appendChild(el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: async (e) => { e.target.disabled = true; try { await SL.api.post('/api/suggestions/' + today + '/' + s.id + '/accept'); day = await SL.api.get('/api/day/' + date); report = await SL.api.get('/api/report/' + today); paintList(); paintSuggestions(); recompute(); SL.toast('Added to your calendar', { kind: 'success' }); } catch (err) { SL.toast(err.message, { kind: 'error' }); } } }, 'Add to calendar'));
        else if (s.kind === 'move_meeting') actions.appendChild(el('button', { class: 'btn btn-sm', type: 'button', onclick: () => { const late = day.events.filter(e => e.type === 'meeting' && hourOf(e.end) >= 19.5).sort((a, b) => (a.end < b.end ? 1 : -1))[0]; if (late) toggleMod(late.id, 'end_at', { hour: 18 }); } }, 'Try it'));
        suggBox.appendChild(el('div', { class: 'card soft v-planner-sugg' }, el('div', { class: 'row between' }, el('strong', null, s.title), (s.gain_low !== null && s.gain_low !== undefined) ? el('span', { class: 'chip pts pts-pos' }, SL.fmt.signed(s.gain_low, 0) + ' to ' + SL.fmt.signed(s.gain_high, 0)) : null), el('p', { class: 'small secondary' }, s.body), actions));
      });
    }
    paintList(); paintSuggestions(); recompute();
    return () => { if (timer) clearTimeout(timer); };
  }
  SL.router.register('planner', { title: 'Planner', render });
})();
