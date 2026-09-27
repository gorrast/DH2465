'use strict';
/* Reality check inbox: ask only when calendar, Maps and the body disagree (SPEC §9.4). */
(function () {
  const el = SL.el;
  const KIND_ICON = { calendar: 'calendar', location: 'map', hr: 'watch' };
  function evidenceChips(c) { return el('div', { class: 'row v-reality-evidence' }, c.evidence.map(e => el('span', { class: 'chip' }, SL.icon(KIND_ICON[e.kind] || 'info', { size: 13 }), e.text))); }
  function habitLine(a) {
    if (!a.habit_before && !a.habit_after) return null;
    const b = a.habit_before || {}, f = a.habit_after || {};
    return el('div', { class: 'v-reality-shift' }, SL.icon('habits', { size: 14 }), el('span', null, (f.title || b.title) + ': '), el('strong', null, SL.fmt.signed(b.effect, 1) + ' → ' + SL.fmt.signed(f.effect, 1) + ' pts'), el('span', { class: 'muted' }, ' (' + (b.n_with || 0) + ' → ' + (f.n_with || 0) + ' nights)'));
  }
  function card(c, onAnswer) {
    const actions = el('div', { class: 'row' });
    const yes = el('button', { class: 'btn btn-primary', type: 'button', onclick: () => onAnswer(c, 'yes', node) }, SL.icon('check', { size: 16 }), 'Yes');
    const no = el('button', { class: 'btn', type: 'button', onclick: () => onAnswer(c, 'no', node) }, SL.icon('x', { size: 16 }), 'No');
    actions.appendChild(yes); actions.appendChild(no);
    const node = el('div', { class: 'card v-reality-card', 'data-check': c.id },
      el('div', { class: 'row between' }, el('span', { class: 'badge ' + (c.kind === 'seen_not_booked' ? 'badge-accent' : 'badge-warning') }, c.kind === 'seen_not_booked' ? 'seen, not booked' : (c.kind === 'location_mismatch' ? 'location mismatch' : 'booked, not seen')), el('span', { class: 'tiny muted' }, SL.fmt.day(c.date))),
      el('h3', { class: 'v-reality-question' }, c.question), evidenceChips(c),
      el('div', { class: 'row between v-reality-actions' }, actions, el('span', { class: 'tiny muted' }, c.consequence || '')));
    return node;
  }
  function resolvedCard(c, extra) {
    return el('div', { class: 'card soft v-reality-resolved' },
      el('div', { class: 'row between' }, el('span', { class: 'row' }, el('span', { class: 'badge badge-' + (c.status === 'yes' ? 'good' : 'critical') }, c.status === 'yes' ? 'yes' : 'no'), el('span', { class: 'small' }, c.question)), el('span', { class: 'tiny muted' }, SL.fmt.day(c.date))),
      extra ? el('div', { class: 'row small' }, habitLine(extra), el('a', { class: 'btn btn-sm btn-ghost', href: '#/replay/' + extra.replay_date }, 'See that day →')) : el('div', { class: 'row tiny muted' }, c.consequence ? el('span', null, c.consequence.replace(/^If (yes|no), /, (m, w) => (w === c.status ? '' : m))) : null, el('a', { href: '#/replay/' + c.date }, 'See that day →')));
  }
  async function render(container) {
    container.appendChild(el('div', { class: 'view-head' }, el('div', null, el('div', { class: 'eyebrow' }, 'Reality check'), el('h1', null, 'Did that actually happen?'))));
    const body = el('div', { class: 'v-reality stack' }); container.appendChild(body);
    body.appendChild(el('p', { class: 'secondary v-reality-intro' }, SL.icon('info', { size: 16 }), ' We never ask you to log. We only ask when your calendar, your location and your body disagree.'));
    const inbox = el('div', { class: 'stack', 'data-tour': 'inbox' });
    const resolvedBox = el('div', { class: 'stack' });
    const olderBox = el('div', { class: 'stack' });
    body.appendChild(el('div', { class: 'grid grid-3' }, el('div', { class: 'span-2 stack' }, el('h3', null, 'Open questions'), inbox), el('div', { class: 'stack' }, el('h3', null, 'Answered'), resolvedBox)));
    body.appendChild(olderBox);
    const recent = {};
    async function load() {
      const data = await SL.api.get('/api/reality');
      SL.clear(inbox); SL.clear(resolvedBox); SL.clear(olderBox);
      if (!data.open.length) inbox.appendChild(el('div', { class: 'card empty' }, SL.icon('check', { size: 26 }), el('h2', null, 'All clear'), el('p', null, 'Calendar, Maps and watch agree for the last two weeks.')));
      data.open.forEach(c => inbox.appendChild(card(c, answer)));
      if (!data.resolved.length) resolvedBox.appendChild(el('p', { class: 'muted small' }, 'Nothing answered yet.'));
      data.resolved.forEach(c => resolvedBox.appendChild(resolvedCard(c, recent[c.id])));
      if (data.older.length) {
        const det = el('details', { class: 'card soft' }, el('summary', null, 'Older (' + data.older.length + ') — assumed as booked'), el('div', { class: 'stack', style: { marginTop: '10px' } }, data.older.map(c => card(c, answer))));
        olderBox.appendChild(det);
      }
    }
    async function answer(c, value, node) {
      node.querySelectorAll('button').forEach(b => { b.disabled = true; });
      try {
        const res = await SL.api.post('/api/reality/' + c.id + '/answer', { answer: value });
        recent[c.id] = res;
        SL.toast(value === 'yes' ? (c.kind === 'seen_not_booked' ? 'Added to your calendar and patterns' : 'Kept in your patterns') : 'Removed from your patterns', { kind: 'success' });
        await load();
      } catch (e) { SL.toast('Could not save: ' + e.message, { kind: 'error' }); node.querySelectorAll('button').forEach(b => { b.disabled = false; }); }
    }
    await load();
  }
  SL.router.register('reality', { title: 'Reality check', render });
})();
