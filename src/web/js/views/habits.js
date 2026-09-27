'use strict';
/* Habits view: every recurring pattern ranked by effect, with intervals and the adjusted effect. */
(function () {
  const el = SL.el;
  let filter = 'all';
  async function render(container) {
    const hd = SL.state.get('historyDays');
    container.appendChild(el('div', { class: 'view-head' }, el('div', null, el('div', { class: 'eyebrow' }, 'Habits'), el('h1', null, 'Your patterns, ranked by effect'))));
    const body = el('div', { class: 'v-habits stack' }); container.appendChild(body);
    body.appendChild(el('div', { class: 'skeleton', style: { height: '200px' } }));
    const data = await SL.api.get('/api/habits' + (hd ? '?history_days=' + hd : ''));
    SL.clear(body);
    const habits = data.habits;
    const groups = ['all', 'good', 'bad', 'calendar', 'workout', 'social', 'travel', 'routine'];
    const chips = el('div', { class: 'row v-habits-filters' });
    const effBox = el('div');
    const cards = el('div', { class: 'grid grid-3 v-habits-cards' });
    const tableBox = el('div', { hidden: true });
    let showTable = false;
    const visible = () => habits.filter(h => filter === 'all' || h.direction === filter || h.group === filter);
    const paint = () => {
      SL.clear(chips);
      groups.forEach(g => chips.appendChild(el('button', { class: 'btn btn-sm ' + (filter === g ? 'btn-primary' : ''), type: 'button', onclick: () => { filter = g; paint(); } }, g === 'all' ? 'All' : g[0].toUpperCase() + g.slice(1))));
      const items = visible();
      Charts.effectBars(effBox, { items: items.map(h => ({ label: h.title, effect: h.effect, lo: h.ci_low, hi: h.ci_high, confidence: h.confidence, direction: h.direction, adjusted: h.adjusted_effect, n: h.n_with })), rowH: 36 });
      SL.clear(cards);
      items.forEach(h => cards.appendChild(el('div', { class: 'card v-habits-card' },
        el('div', { class: 'row between' }, el('h3', null, h.title), el('span', { class: 'badge badge-' + h.confidence }, h.confidence)),
        el('p', { class: 'small secondary' }, h.description),
        el('div', { class: 'v-habits-effect' },
          h.adjusted_effect !== null && h.adjusted_effect !== undefined
            ? el('div', null, el('span', { class: 'pts ' + (h.adjusted_effect < 0 ? 'pts-neg' : 'pts-pos'), style: { fontSize: '24px' } }, SL.fmt.signed(h.adjusted_effect, 1)), el('span', { class: 'small muted' }, ' pts, adjusted'))
            : el('div', null, el('span', { class: 'pts ' + ((h.effect || 0) < 0 ? 'pts-neg' : 'pts-pos'), style: { fontSize: '24px' } }, SL.fmt.signed(h.effect, 1)), el('span', { class: 'small muted' }, ' pts')),
          el('div', { class: 'small secondary' }, 'Simple comparison: ' + SL.fmt.signed(h.effect, 1) + ((h.ci_low !== null && h.ci_low !== undefined) ? ' (95 % ' + SL.fmt.signed(h.ci_low, 1) + ' to ' + SL.fmt.signed(h.ci_high, 1) + ')' : ''))),
        el('div', { class: 'row tiny muted' }, el('span', null, 'n = ' + h.n_with + ' vs ' + h.n_without + ' nights'),
          (h.metric_effects && h.metric_effects.hrv_ms_pct !== null && h.metric_effects.hrv_ms_pct !== undefined) ? el('span', null, 'HRV ' + SL.fmt.pct(h.metric_effects.hrv_ms_pct, 0)) : null,
          (h.metric_effects && h.metric_effects.resting_hr !== null && h.metric_effects.resting_hr !== undefined) ? el('span', null, 'RHR ' + SL.fmt.signed(h.metric_effects.resting_hr, 1) + ' bpm') : null),
        (h.example_dates && h.example_dates.length) ? el('div', { class: 'row tiny' }, el('span', { class: 'muted' }, 'Recent:'), h.example_dates.slice(-4).map(d => el('a', { href: '#/morning/' + SL.date.addDays(d, 1) }, SL.fmt.day(d)))) : null)));
      if (showTable) Charts.table(tableBox, [{ key: 'title', label: 'Pattern' }, { key: 'n', label: 'Nights with / without' }, { key: 'effect', label: 'Effect (pts)', num: true }, { key: 'ci', label: '95 % interval' }, { key: 'adjusted', label: 'Adjusted', num: true }, { key: 'confidence', label: 'Confidence' }],
        items.map(h => ({ title: h.title, n: h.n_with + ' / ' + h.n_without, effect: SL.fmt.signed(h.effect, 1), ci: (h.ci_low === null || h.ci_low === undefined) ? '–' : SL.fmt.signed(h.ci_low, 1) + ' to ' + SL.fmt.signed(h.ci_high, 1), adjusted: (h.adjusted_effect === null || h.adjusted_effect === undefined) ? '–' : SL.fmt.signed(h.adjusted_effect, 1), confidence: h.confidence })));
    };
    const tableBtn = el('button', { class: 'btn btn-sm', type: 'button', onclick: () => { showTable = !showTable; tableBox.hidden = !showTable; tableBtn.textContent = showTable ? 'Hide table' : 'Table view'; paint(); } }, 'Table view');
    body.appendChild(el('div', { class: 'row between' }, chips, tableBtn));
    body.appendChild(el('div', { class: 'card', 'data-tour': 'effects' }, el('div', { class: 'card-title' }, el('h3', null, 'Effect on sleep score'), el('span', { class: 'tiny muted' }, 'model: ' + data.model.n_nights + ' nights · out-of-sample R² ' + SL.fmt.num((data.model.r2_loo || 0) * 100, 0) + ' %')), effBox, tableBox));
    body.appendChild(cards);
    paint();
  }
  SL.router.register('habits', { title: 'Habits', render });
})();
