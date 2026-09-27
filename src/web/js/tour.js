'use strict';
/* Presenter tour: ten steps in pitch order, spotlighting anchors set by the views (SPEC §9.4). */
(function () {
  const el = SL.el;
  let idx = -1, root = null, active = false, pollTimer = null, onResize = null;
  const steps = () => {
    const today = SL.date.today();
    return [
      { title: 'A score. No why.', text: 'This is what a wearable gives you this morning: a number and a word. The watch knows how the night went — not what happened yesterday.', hash: '#/morning/' + today + '?reveal=1', anchor: 'watch-card' },
      { title: 'Why?', text: 'One click. StressLess matches the night to yesterday’s calendar, Maps history and heart rate, and names the three most likely causes — with evidence and a suggestion you can add to the calendar.', hash: '#/morning/' + today + '?reveal=1', anchor: 'causes', onEnter: () => { const b = document.querySelector('[data-tour="reveal"]'); if (b) b.click(); } },
      { title: 'The body rode the meetings', text: 'Watch the evening: after the late meeting the heart rate stays above the dotted line — your usual heart rate at that hour — until well past ten.', hash: '#/replay/' + SL.date.addDays(today, -1) + '?t=1020', anchor: 'timeline', onEnter: () => { setTimeout(() => { if (SL.replay) SL.replay.playRange(17 * 60, 23.5 * 60, 64); }, 400); } },
      { title: 'No logging. Only confirmations.', text: 'The watch saw a workout the calendar did not know about. Answer once, and the pattern updates in front of you.', hash: '#/reality', anchor: 'inbox' },
      { title: 'Patterns over weeks', text: 'Six weeks in: how meeting load, late finishes and evenings out relate to the sleep score — with sample sizes and intervals, not just averages.', hash: '#/week', anchor: 'buckets' },
      { title: 'Change tomorrow', text: 'End tonight’s late meeting at 18:00 and the predicted score moves, with a likely range. The block you accepted a minute ago is already in the plan.', hash: '#/planner/' + today, anchor: 'prediction' },
      { title: 'Same engine, different person', text: 'Open the persona menu and switch to Robin: different life, different first cause. The engine is the same; the person is not.', hash: '#/morning/' + today, anchor: 'persona' },
      { title: 'Under the hood', text: 'Because this is a simulation, we can check the engine against the truth we planted: rank agreement, out-of-sample skill, and a planted null factor to catch false alarms.', hash: '#/lab', anchor: 'validation' },
      { title: 'What the calendar can’t see', text: 'Alcohol, caffeine, screens, sleep debt, illness, unworn nights. The honest answer is on the screen, not hidden.', hash: '#/lab', anchor: 'challenges' },
      { title: 'The watch measures. The calendar explains.', text: 'Back to this morning: a score with a why, and one concrete change already on the calendar for tonight.', hash: '#/morning/' + today, anchor: 'suggestion' },
    ];
  };
  function ensureRoot() {
    if (root) return root;
    root = document.getElementById('tour-root') || document.body;
    return root;
  }
  function paint() {
    const r = ensureRoot();
    SL.clear(r);
    if (!active) return;
    const list = steps();
    const s = list[idx];
    const target = document.querySelector('[data-tour="' + s.anchor + '"]');
    const rect = target ? target.getBoundingClientRect() : null;
    const spot = el('div', { class: 'tour-spot' });
    if (rect) { spot.style.left = (rect.left - 8) + 'px'; spot.style.top = (rect.top - 8) + 'px'; spot.style.width = (rect.width + 16) + 'px'; spot.style.height = (rect.height + 16) + 'px'; }
    else { spot.classList.add('nospot'); }
    const card = el('div', { class: 'tour-card card raised', role: 'dialog', 'aria-label': 'Presenter tour' },
      el('div', { class: 'eyebrow' }, 'Step ' + (idx + 1) + ' of ' + list.length),
      el('h3', null, s.title), el('p', null, s.text),
      el('div', { class: 'row between' },
        el('div', { class: 'tour-dots' }, list.map((_, i) => el('span', { class: 'tour-dot' + (i === idx ? ' on' : i < idx ? ' done' : '') }))),
        el('div', { class: 'row' }, el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: stop }, 'Exit'), el('button', { class: 'btn btn-sm', type: 'button', disabled: idx === 0, onclick: prev }, '←'), el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: next }, idx === list.length - 1 ? 'Done' : 'Next →'))));
    // place the card: below the spot if room, else above, else bottom-right
    if (rect) {
      const below = rect.bottom + 24;
      if (below + 200 < window.innerHeight) { card.style.top = below + 'px'; card.style.left = Math.min(Math.max(16, rect.left), window.innerWidth - 440) + 'px'; }
      else if (rect.top - 220 > 0) { card.style.top = (rect.top - 220) + 'px'; card.style.left = Math.min(Math.max(16, rect.left), window.innerWidth - 440) + 'px'; }
      else { card.style.right = '24px'; card.style.bottom = '24px'; }
    } else { card.style.right = '24px'; card.style.bottom = '24px'; }
    r.appendChild(el('div', { class: 'tour-backdrop' }));
    r.appendChild(spot);
    r.appendChild(card);
  }
  function goto(i) {
    const list = steps();
    idx = Math.max(0, Math.min(list.length - 1, i));
    const s = list[idx];
    SL.state.set('historyDays', null);
    if (location.hash !== s.hash) location.hash = s.hash;
    if (pollTimer) clearInterval(pollTimer);
    let tries = 0;
    paint();
    pollTimer = setInterval(() => {
      tries++;
      const target = document.querySelector('[data-tour="' + s.anchor + '"]');
      if (target || tries > 30) {
        clearInterval(pollTimer); pollTimer = null;
        paint();
        if (target) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        setTimeout(paint, 450);
        if (s.onEnter) setTimeout(s.onEnter, 300);
      }
    }, 100);
  }
  function onKey(e) {
    if (!active) return;
    if (e.key === 'Escape') { e.preventDefault(); stop(); }
    else if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'Enter') { e.preventDefault(); next(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); prev(); }
  }
  function start() { if (active) return; active = true; document.addEventListener('keydown', onKey, true); onResize = () => paint(); window.addEventListener('resize', onResize); window.addEventListener('scroll', onResize, true); goto(0); }
  function stop() { active = false; idx = -1; document.removeEventListener('keydown', onKey, true); if (onResize) { window.removeEventListener('resize', onResize); window.removeEventListener('scroll', onResize, true); } if (pollTimer) clearInterval(pollTimer); paint(); }
  function next() { if (idx >= steps().length - 1) { stop(); return; } goto(idx + 1); }
  function prev() { goto(idx - 1); }
  SL.tour = { start, stop, toggle: () => (active ? stop() : start()), active: () => active, next, prev };
})();
