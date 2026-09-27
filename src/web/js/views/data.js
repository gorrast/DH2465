'use strict';
/* Data & privacy: what is connected, what is read, persona/seed, import, delete (SPEC §9.4). */
(function () {
  const el = SL.el;
  const CLASSES = [
    ['Calendar events', 'title, start, end, attendees count, location hint', 'to know what your day looked like', 'local only'],
    ['Location visits', 'place type and name, start, end', 'to check whether booked events happened', 'local only'],
    ['Heart rate', 'one sample per minute', 'to see how your body responded during and after events', 'local only'],
    ['Sleep', 'bedtime, stages, interruptions, wake time', 'to compute and explain the sleep score', 'local only'],
    ['Recovery markers', 'overnight HRV, resting heart rate, respiratory rate, wrist temperature, blood oxygen', 'to compare each night with your own baseline', 'local only'],
    ['Your answers', 'yes/no to reality checks, accepted suggestions', 'to correct the calendar and improve your patterns', 'local only'],
  ];
  async function render(container) {
    const meta = SL.meta();
    container.appendChild(el('div', { class: 'view-head' }, el('div', null, el('div', { class: 'eyebrow' }, 'Data & privacy'), el('h1', null, 'What StressLess reads, and why'))));
    const body = el('div', { class: 'v-data stack' }); container.appendChild(body);
    const isDemo = meta.source === 'demo';
    const conn = (icon, title, status, note) => el('div', { class: 'card v-data-conn' }, el('div', { class: 'row between' }, el('span', { class: 'row' }, el('span', { class: 'v-data-icon' }, SL.icon(icon, { size: 18 })), el('strong', null, title)), el('span', { class: 'badge ' + (status.startsWith('Demo') ? 'badge-accent' : 'badge-good') }, status)), el('p', { class: 'small secondary' }, note));
    body.appendChild(el('div', { class: 'grid grid-4' },
      conn('calendar', 'Calendar', isDemo ? 'Demo data' : 'Imported', isDemo ? 'Ten weeks of a simulated calendar. In the product: Google Calendar or EventKit, read-only, plus one write per accepted suggestion.' : 'Imported from your .ics export.'),
      conn('watch', 'Watch', isDemo ? 'Demo data' : 'Imported', isDemo ? 'Simulated Apple Watch: heart rate, sleep stages, HRV, resting heart rate, wrist temperature. In the product: HealthKit on the phone.' : 'Imported from Apple Health.'),
      conn('map', 'Maps', isDemo ? 'Demo data' : 'Imported', isDemo ? 'Simulated Google Maps timeline. In the product: Google Takeout or the Timeline API, used only to confirm booked events.' : 'Imported from Google Takeout.'),
      conn('brain', 'Reasoning', meta.reasoning_mode === 'claude' ? 'Claude (opt-in)' : 'On-device rules', meta.reasoning_mode === 'claude' ? 'Claude writes the narrative from a de-identified summary: numbers and titles only, never ids, times, places or people.' : 'The explanation text is written by rules on this machine. Set STRESSLESS_REASONER=claude to let Claude write it (opt-in).')));
    body.appendChild(el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'Data classes')),
      el('table', { class: 'data' }, el('thead', null, el('tr', null, ['What', 'Fields', 'Why', 'Retention'].map(h => el('th', null, h)))), el('tbody', null, CLASSES.map(r => el('tr', null, r.map(c => el('td', null, c))))))));
    // demo dataset
    const seedInput = el('input', { class: 'input', type: 'number', value: String(meta.seed), min: 0, max: 9999, style: { width: '90px' }, 'aria-label': 'Seed' });
    let chosen = meta.persona.key;
    const cards = el('div', { class: 'grid grid-3' });
    const paintPersonas = () => { SL.clear(cards); (meta.personas || []).forEach(p => cards.appendChild(el('button', { type: 'button', class: 'card soft v-data-persona' + (chosen === p.key ? ' chosen' : ''), onclick: () => { chosen = p.key; paintPersonas(); } },
      el('div', { class: 'row between' }, el('span', { class: 'avatar' }, p.name.slice(0, 1)), p.key === meta.persona.key ? el('span', { class: 'badge badge-accent' }, 'current') : (p.ready ? el('span', { class: 'badge badge-good' }, 'ready') : el('span', { class: 'badge badge-low' }, 'preparing'))),
      el('strong', null, p.name), el('div', { class: 'small secondary' }, p.tagline)))); };
    paintPersonas();
    body.appendChild(el('div', { class: 'card', 'data-tour': 'personas' }, el('div', { class: 'card-title' }, el('h3', null, 'Demo dataset'), el('span', { class: 'tiny muted' }, (meta.days || 70) + ' nights · today ' + SL.fmt.day(meta.today) + (meta.anchor_mode ? ' (fixed)' : ''))),
      el('p', { class: 'small secondary' }, 'Three simulated people with different lives and different true sensitivities. Same seed, same story, every time.'), cards,
      el('div', { class: 'row', style: { marginTop: '12px' } }, el('label', { class: 'row small' }, 'Seed', seedInput), el('button', { class: 'btn btn-primary', type: 'button', onclick: () => SL.switchPersona(chosen, +seedInput.value || 0) }, SL.icon('refresh', { size: 16 }), 'Regenerate'))));
    // facts + import + delete
    let facts = null;
    try { facts = await SL.api.get('/api/validation'); } catch (e) { facts = null; }
    const hidden = facts && facts.available ? facts.hidden : null;
    body.appendChild(el('div', { class: 'grid grid-2' },
      el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'Bring your own data')),
        el('p', { class: 'small secondary' }, 'The same engine runs on real exports. Stop the server and start it with your files:'),
        el('pre', { class: 'v-data-pre' }, 'python3 run.py \\\n  --import-health ~/Downloads/apple_health_export/export.xml \\\n  --import-ics ~/Downloads/calendar.ics \\\n  --import-timeline ~/Downloads/Takeout/Location\\ History \\\n  --persona-name "You"'),
        el('ul', { class: 'small secondary v-data-list' }, el('li', null, 'Apple Health: Settings → Health → Export All Health Data (export.xml)'), el('li', null, 'Google Calendar: Settings → Import & export → Export (.ics)'), el('li', null, 'Google Maps: Google Takeout → Location History (Semantic Location History or Timeline.json)'))),
      el('div', { class: 'stack' },
        el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'This dataset')),
          el('div', { class: 'row' }, el('span', { class: 'chip' }, (meta.n_nights || 0) + ' nights with watch data'), hidden ? el('span', { class: 'chip' }, (hidden.unworn_nights || []).length + ' unworn nights, ' + (hidden.unworn_social_nights || 0) + ' after social evenings') : null, el('span', { class: 'chip' }, 'generated ' + (meta.generated_at ? SL.fmt.hm(meta.generated_at) : '–'))),
          hidden ? el('p', { class: 'tiny muted', style: { marginTop: '8px' } }, 'Missing nights are not random: forgetting to charge happens more after late evenings, which is exactly what real data does.') : null),
        el('div', { class: 'card' }, el('div', { class: 'card-title' }, el('h3', null, 'Delete everything')),
          el('p', { class: 'small secondary' }, 'Removes the generated dataset, your answers and accepted suggestions from this Mac, then regenerates the default demo.'),
          el('button', { class: 'btn btn-danger', type: 'button', onclick: async () => {
            const ok = await SL.modal.confirm({ title: 'Delete all data?', body: 'This removes the dataset, your reality-check answers and accepted suggestions from this machine. The default demo is regenerated.', confirmLabel: 'Delete and regenerate', danger: true });
            if (!ok) return;
            SL.busy({ title: 'Deleting and regenerating', steps: ['Removing local data', 'Booking a fresh calendar', 'Simulating heart rate and sleep', 'Fitting the model'] });
            try { await SL.api.post('/api/reset'); await SL.refreshMeta(); SL.state.set('historyDays', null); SL.busy(null); SL.toast('All data deleted. Fresh demo ready.', { kind: 'success' }); SL.router.go('#/morning/' + SL.date.today()); }
            catch (e) { SL.busy(null); SL.toast(e.message, { kind: 'error' }); }
          } }, SL.icon('trash', { size: 16 }), 'Delete all data')))));
  }
  SL.router.register('data', { title: 'Data & privacy', render });
})();
