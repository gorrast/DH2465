'use strict';
/* Under the hood: pipeline, model card, validation against planted truth, cold start, open challenges (SPEC §9.4). */
(function () {
  const el = SL.el;
  const LABELS = { meetings_over_3: 'Meeting load', b2b_over_2: 'Back-to-back', late_meeting_hours: 'Late meetings', evening_social: 'Evening social', workout_morning: 'Morning workout', workout_late: 'Late workout', travel: 'Travel', early_start: 'Early start', protected_evening: 'Protected evening', is_weekend: 'Weekend' };
  const pct = (v) => v === null || v === undefined ? '–' : Math.round(v * 100) + ' %';
  const num = (v, d) => v === null || v === undefined ? '–' : SL.fmt.num(v, d === undefined ? 2 : d);
  function stat(label, value, caption) { return el('div', { class: 'stat-tile v-lab-stat' }, el('div', { class: 'label' }, label), el('div', { class: 'value' }, value), caption ? el('div', { class: 'tiny muted' }, caption) : null); }
  async function render(container) {
    const hd = SL.state.get('historyDays');
    const today = SL.date.today();
    container.appendChild(el('div', { class: 'view-head' }, el('div', null, el('div', { class: 'eyebrow' }, 'Under the hood'), el('h1', null, 'How the engine explains a night')), el('span', { class: 'badge badge-accent' }, 'Simulator ground truth — demo only')));
    const body = el('div', { class: 'v-lab stack' }); container.appendChild(body);
    body.appendChild(el('div', { class: 'skeleton', style: { height: '200px' } }));
    const [model, val, report, habits] = await Promise.all([
      SL.api.get('/api/model' + (hd ? '?history_days=' + hd : '')), SL.api.get('/api/validation'), SL.api.get('/api/report/' + today).catch(() => null), SL.api.get('/api/habits' + (hd ? '?history_days=' + hd : ''))]);
    SL.clear(body);
    const src = (report && report.sources) || {};
    // pipeline
    const step = (icon, title, sub) => el('div', { class: 'v-lab-step' }, el('span', { class: 'v-lab-step-icon' }, SL.icon(icon, { size: 18 })), el('div', null, el('strong', null, title), el('div', { class: 'tiny muted' }, sub)));
    body.appendChild(el('div', { class: 'card', 'data-tour': 'pipeline' }, el('div', { class: 'card-title' }, el('h3', null, 'The pipeline')),
      el('div', { class: 'v-lab-pipeline' },
        step('calendar', 'Calendar', (src.calendar_events || '–') + ' events yesterday'), el('span', { class: 'v-lab-arrow' }, '→'),
        step('map', 'Maps', (src.maps_places || '–') + ' places'), el('span', { class: 'v-lab-arrow' }, '→'),
        step('watch', 'Watch', (src.watch_minutes || 0).toLocaleString('en') + ' minutes'), el('span', { class: 'v-lab-arrow' }, '→'),
        step('habits', 'Features', '10 numbers per day'), el('span', { class: 'v-lab-arrow' }, '→'),
        step('heart', 'Personal baselines', 'your own medians'), el('span', { class: 'v-lab-arrow' }, '→'),
        step('lab', 'Within-person model', model.n_nights + ' nights, ridge λ ' + num(model.ridge_lambda, 0)), el('span', { class: 'v-lab-arrow' }, '→'),
        step('brain', 'Attribution', 'only factors present that day'), el('span', { class: 'v-lab-arrow' }, '→'),
        step('sparkles', 'Suggestions', 'calendar-ready blocks'))));
    // model card
    const coefBox = el('div');
    body.appendChild(el('div', { class: 'card', 'data-tour': 'model' }, el('div', { class: 'card-title' }, el('h3', null, 'Model card'), el('span', { class: 'tiny muted' }, 'ridge regression across your nights, penalty chosen by leave-one-out cross-validation')),
      el('div', { class: 'grid grid-5' },
        stat('Nights in the fit', String(model.n_nights), model.n_unworn ? model.n_unworn + ' unworn nights excluded' : 'all nights worn'),
        stat('In-sample R²', pct(model.r2), 'how much the fit explains on the nights it saw'),
        stat('Out-of-sample R²', pct(model.r2_loo), 'honest number: each night predicted without itself'),
        stat('Typical error', '±' + num(model.rmse_loo, 0), 'sleep-score points, out of sample'),
        stat('Calm-day prediction', num(model.calm_day_pred, 0), 'a day with none of the factors')),
      model.insufficient ? el('p', { class: 'secondary' }, 'Fewer than ten nights: the model waits. Causes are not shown until it has enough to learn from.') : null,
      el('h4', { style: { marginTop: '14px' } }, 'Effect per unit of each factor'), coefBox,
      el('p', { class: 'tiny muted' }, '95 % intervals per factor from a moving-block bootstrap; with ten factors expect roughly one false alarm in a null world.')));
    Charts.effectBars(coefBox, { items: model.coefficients.filter(c => c.n_active > 0).map(c => ({ label: c.label, effect: c.value, lo: c.ci_low, hi: c.ci_high, n: c.n_active, direction: Math.abs(c.value) < 0.3 ? 'neutral' : (c.value > 0 ? 'good' : 'bad') })), rowH: 30 });
    // cold start slider
    const slider = el('input', { type: 'range', min: 0, max: 3, step: 1, value: String([7, 14, 28, null].indexOf(hd === undefined ? null : hd)), 'aria-label': 'Nights of history', onchange: (e) => { const v = [7, 14, 28, null][+e.target.value]; SL.state.set('historyDays', v); } });
    body.appendChild(el('div', { class: 'card soft', 'data-tour': 'coldstart' }, el('div', { class: 'card-title' }, el('h3', null, 'Cold start: how much history does it need?'), el('span', { class: 'chip' }, hd ? hd + ' nights' : 'all nights')),
      el('div', { class: 'row', style: { gap: '14px' } }, el('span', { class: 'small muted' }, '7'), slider, el('span', { class: 'small muted' }, 'all')),
      el('p', { class: 'small secondary' }, 'Slide left and watch the intervals widen and the badges drop. The app shows what your watch measured from night one; explanations start at ten nights and firm up over weeks. A pill in the top bar reminds you while a shorter history is in use.')));
    // validation
    if (val.available) {
      const scatterBox = el('div');
      const pts = val.coefficients.filter(c => c.planted_total !== null).map(c => ({ x: c.planted_total, y: c.estimated, lo: c.ci_low, hi: c.ci_high, label: c.label }));
      const hollow = val.coefficients.filter(c => c.planted_direct !== null).map(c => ({ x: c.planted_direct, y: c.estimated, label: c.label + ' (direct)', hollow: true }));
      const nullRow = val.coefficients.find(c => c.null_planted);
      body.appendChild(el('div', { class: 'card', 'data-tour': 'validation' }, el('div', { class: 'card-title' }, el('h3', null, 'Checked against the planted truth'), el('span', { class: 'badge badge-accent' }, 'Simulator ground truth — demo only')),
        el('div', { class: 'grid grid-3' },
          el('div', { class: 'span-2' }, scatterBox, el('p', { class: 'tiny muted' }, 'Each dot is one factor: what the simulator planted (horizontal) vs what the engine estimated (vertical); bars are the engine’s 95 % intervals; on the diagonal means perfect. Filled dots: the total effect including correlated hidden factors. Hollow dots: the direct effect alone — the calendar sees the dinner, not the wine.')),
          el('div', { class: 'stack' },
            stat('Rank agreement', num(val.spearman_total, 2), 'Spearman between planted and estimated effects — ' + (val.spearman_total >= 0.8 ? 'the engine ordered the real causes correctly' : val.spearman_total >= 0.6 ? 'mostly the right order' : 'weak ordering')),
            stat('Night-by-night agreement', num(val.pooled_spearman, 2), 'over every (night, factor) pair that was active (' + val.pooled_n + ' pairs)'),
            val.holdout ? stat('Prediction skill', pct(val.holdout.skill), 'predicts the last ' + val.holdout.n_test + ' nights ' + Math.round((val.holdout.skill || 0) * 100) + ' % better than assuming your median (error ±' + num(val.holdout.rmse_holdout, 0) + ' vs ±' + num(val.holdout.rmse_naive, 0) + ')') : null,
            nullRow ? stat('Planted null', SL.fmt.signed(nullRow.estimated, 1), nullRow.label + ' was planted as no effect for this persona — engine says ' + SL.fmt.signed(nullRow.estimated, 1) + ' (interval ' + SL.fmt.signed(nullRow.ci_low, 1) + ' to ' + SL.fmt.signed(nullRow.ci_high, 1) + ')' + (nullRow.ci_covers_zero ? ': correctly covers zero' : ': a false alarm')) : null,
            val.spearman_before_answers !== null && val.spearman_before_answers !== undefined ? stat('After your answers', num(val.spearman_before_answers, 2) + ' → ' + num(val.spearman_after_answers, 2), 'rank agreement before vs after applying your reality-check answers') : null))));
      Charts.scatter(scatterBox, { points: pts.concat(hollow), xLabel: 'planted effect (points per unit)', yLabel: 'estimated effect', identity: true, height: 320 });
      const r = val.reality, h = val.hidden, s = val.stressors;
      body.appendChild(el('div', { class: 'grid grid-3' },
        el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'Reality checks: right, wrong, missed')),
          el('table', { class: 'data' }, el('tbody', null,
            el('tr', null, el('td', null, 'Booked, not attended — caught'), el('td', { class: 'num' }, String(r.booked_not_seen.tp))),
            el('tr', null, el('td', null, 'Asked although it happened'), el('td', { class: 'num' }, String(r.booked_not_seen.fp))),
            el('tr', null, el('td', null, 'Missed skips'), el('td', { class: 'num' }, String(r.booked_not_seen.fn))),
            el('tr', null, el('td', null, 'Precision / recall'), el('td', { class: 'num' }, pct(r.booked_not_seen.precision) + ' / ' + pct(r.booked_not_seen.recall))),
            el('tr', null, el('td', null, 'Unbooked activities found'), el('td', { class: 'num' }, r.seen_not_booked.tp + ' of ' + (r.seen_not_booked.tp + r.seen_not_booked.fn))))),
          el('p', { class: 'tiny muted' }, 'Meetings attended from home never trigger a question: location cannot tell a video call from a skipped one, so we do not ask.')),
        el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'What the calendar cannot see')),
          el('ul', { class: 'small secondary v-lab-list' },
            el('li', null, h.alcohol_nights + ' nights with alcohol, mostly after social evenings'),
            el('li', null, h.caffeine_days + ' late-coffee days, ' + h.screens_nights + ' late-screen nights'),
            el('li', null, (h.illness_nights || []).length + ' illness nights' + (h.illness_nights && h.illness_nights.length ? ' (' + SL.fmt.day(h.illness_nights[0]) + ' onwards)' : '')),
            el('li', null, 'Sleep debt carried night to night (average ' + num(h.sleep_debt_mean, 0) + ' min)'),
            el('li', null, (h.unworn_nights || []).length + ' unworn nights, ' + h.unworn_social_nights + ' of them after social evenings — missing data is not random')),
          el('p', { class: 'small' }, 'The engine flagged ' + h.flagged + ' nights as "not explained by your calendar": precision ' + pct(h.precision) + ', recall ' + pct(h.recall) + '.'),
          h.illness_nights && h.illness_nights.length ? el('a', { class: 'btn btn-sm', href: '#/morning/' + SL.date.addDays(h.illness_nights[h.illness_nights.length - 1], 1) }, 'Show me a night the calendar can’t explain →') : null),
        el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'Why this is not circular')),
          el('p', { class: 'small secondary' }, 'The engine uses the same day features as the simulator, so recovering coefficients alone would prove little. What makes it a real test:'),
          el('ul', { class: 'small v-lab-list' },
            el('li', null, pct((s.pct_booked_not_attended || 0) / 100) + ' of booked events were never attended — the calendar lies, and the engine only learns the truth through reality checks'),
            el('li', null, pct((s.pct_nights_hidden || 0) / 100) + ' of nights carry a hidden factor the calendar cannot see'),
            el('li', null, pct((s.pct_unworn || 0) / 100) + ' of nights have no watch data'),
            el('li', null, 'The score is non-linear and the fit is judged out of sample: in-sample R² minus out-of-sample R² = ' + num(s.r2_gap, 2)),
            el('li', null, 'A planted null factor checks for false alarms')))));
    } else {
      body.appendChild(el('div', { class: 'card soft' }, el('h3', null, 'No planted truth'), el('p', { class: 'secondary' }, val.reason || 'This dataset was imported from real sources; there is nothing to validate against.')));
    }
    // open challenges
    const challenges = [
      ['Correlation is not causation, especially with one person’s data', 'Every number carries n, an interval and a confidence badge; the text says "was followed by", never "caused"; the footer reports out-of-sample fit.'],
      ['The calendar misses coffee, alcohol, screens and unbooked stress', 'Nights the calendar cannot explain are flagged; body signals (resting heart rate, wrist temperature) hint at alcohol or illness; unbooked activities are detected from Maps and the watch.'],
      ['Cold start: value shows up only after weeks', 'The watch view works from night one; explanations start at ten nights; the slider above shows confidence firming up.'],
      ['Health plus calendar data is a sensitive combination', 'Everything runs on this machine; the Data view lists every field and why; the optional AI narrative receives only a de-identified summary.'],
      ['The watch must be worn as much as possible', 'Charging gaps and unworn nights are handled gracefully, and the Lab shows that missingness is not random.'],
    ];
    body.appendChild(el('div', { class: 'card', 'data-tour': 'challenges' }, el('div', { class: 'card-title' }, el('h3', null, 'Open challenges from the pitch, and what this demo does about them')),
      el('div', { class: 'grid grid-2' }, challenges.map(([c, a]) => el('div', { class: 'card soft' }, el('strong', null, c), el('p', { class: 'small secondary', style: { marginTop: '6px' } }, a)))),
      val.available && val.limitations ? el('div', { style: { marginTop: '12px' } }, el('h4', null, 'Known limitations'), el('ul', { class: 'small secondary v-lab-list' }, val.limitations.map(l => el('li', null, l)))) : null));
  }
  SL.router.register('lab', { title: 'Under the hood', render });
})();
