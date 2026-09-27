'use strict';
/* Week view: heat strip, meeting load vs sleep, strongest pattern, last seven days, top habits. */
(function () {
  const el = SL.el;
  async function render(container, { params }) {
    const end = params[0] || SL.date.today();
    const hd = SL.state.get('historyDays');
    container.appendChild(el('div', { class: 'view-head' }, el('div', null, el('div', { class: 'eyebrow' }, 'Weekly insight'), el('h1', null, 'Patterns over the last weeks')),
      el('span', { class: 'small muted' }, 'up to ' + SL.fmt.day(SL.date.addDays(end, -1)))));
    const body = el('div', { class: 'v-week stack' }); container.appendChild(body);
    body.appendChild(el('div', { class: 'skeleton', style: { height: '200px' } }));
    const w = await SL.api.get('/api/week?end=' + end + (hd ? '&history_days=' + hd : ''));
    SL.clear(body);
    const heatBox = el('div', { class: 'v-week-heat' });
    body.appendChild(el('div', { class: 'card', 'data-tour': 'heat' }, el('div', { class: 'card-title' }, el('h3', null, 'Every night, ' + w.heat.length + ' of them'), el('span', { class: 'tiny muted' }, 'click a night to open its morning report')), heatBox));
    Charts.heatStrip(heatBox, { days: w.heat, onSelect: (d) => SL.router.go('#/morning/' + SL.date.addDays(d.date, 1)) });
    const bucketsBox = el('div', { class: 'v-week-buckets' });
    body.appendChild(el('div', { class: 'grid grid-3' },
      el('div', { class: 'card span-2', 'data-tour': 'buckets' }, el('div', { class: 'card-title' }, el('h3', null, 'Average sleep score by meeting load, last ' + w.weeks + ' weeks'), el('span', { class: 'tiny muted' }, 'work nights only · whiskers: 95 % range')), bucketsBox, el('p', { class: 'secondary v-week-headline' }, w.headline)),
      el('div', { class: 'card accent', 'data-tour': 'strongest' }, el('div', { class: 'eyebrow small' }, 'Strongest pattern'), el('p', { class: 'v-week-strongest' }, w.strongest_pattern || 'No pattern clears the confidence bar yet.'), el('a', { class: 'small', href: '#/habits', style: { color: 'inherit', textDecoration: 'underline' } }, 'All habits →'))));
    Charts.bars(bucketsBox, { items: w.buckets.map(b => ({ label: b.label, value: b.mean_score, n: b.n, lo: b.lo, hi: b.hi })), unit: 'sleep score', height: 260, ariaLabel: 'Average sleep score by meeting load' });
    body.appendChild(el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'The last seven nights')),
      el('div', { class: 'v-week-last7' }, w.last7.map(d => el('a', { class: 'v-week-day' + (d.worn ? '' : ' unworn'), href: '#/morning/' + SL.date.addDays(d.date, 1) },
        el('div', { class: 'v-week-day-name' }, SL.fmt.day(d.date)),
        el('div', { class: 'v-week-day-score', style: { color: d.worn ? 'var(--status-' + Charts.bandFor(d.score) + ')' : 'var(--ink-muted)' } }, d.worn ? String(d.score) : '–'),
        el('div', { class: 'v-week-day-chips' }, d.chips.slice(0, 3).map(c => el('span', { class: 'chip' }, c))))))));
    const effBox = el('div');
    body.appendChild(el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'Top patterns'), el('a', { class: 'small', href: '#/habits' }, 'See all →')), effBox,
      el('div', { class: 'tiny muted' }, 'Difference in sleep score on nights with the pattern vs without, weekday and weekend nights compared separately. Diamonds: model-adjusted effect.')));
    Charts.effectBars(effBox, { items: w.top_habits.map(h => ({ label: h.title, effect: h.effect, lo: h.ci_low, hi: h.ci_high, confidence: h.confidence, direction: h.direction, adjusted: h.adjusted_effect, n: h.n_with, key: h.key })), onSelect: () => SL.router.go('#/habits') });
  }
  SL.router.register('week', { title: 'Week', render });
})();
