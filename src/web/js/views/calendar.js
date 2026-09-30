'use strict';
(function () {
  const el = SL.el;
  const EDGE_URL = 'https://kxkanzzujcawqcdegmbp.supabase.co/functions/v1/google-calendar';
  const DAY_MS = 86400000;

  function auth() {
    if (!window.StressLessAuth || !StressLessAuth.client || !StressLessAuth.session) throw new Error('Sign in to use Google Calendar');
    return StressLessAuth;
  }
  async function edge(action) {
    const current = auth();
    const sessionResult = await current.client.auth.getSession();
    const session = sessionResult.data.session;
    if (!session) throw new Error('Your session has expired; please sign in again');
    const response = await fetch(EDGE_URL, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + session.access_token,
        apikey: current.anonKey,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ action }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'Google Calendar request failed');
    return payload;
  }
  function windowStart() {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const mondayOffset = (today.getDay() + 6) % 7;
    today.setDate(today.getDate() - mondayOffset - 63);
    return today;
  }
  function weekWindows() {
    const start = windowStart();
    return Array.from({ length: 10 }, (_, index) => {
      const from = new Date(start.getTime() + index * 7 * DAY_MS);
      const to = new Date(from.getTime() + 7 * DAY_MS);
      return { from, to };
    });
  }
  function weekLabel(from, to) {
    const fmt = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
    const end = new Date(to.getTime() - DAY_MS);
    return fmt.format(from) + ' - ' + fmt.format(end);
  }
  function eventTime(event) {
    const start = new Date(event.starts_at);
    const end = new Date(event.ends_at);
    const sameDay = start.toDateString() === end.toDateString();
    const allDay = start.getHours() === 0 && start.getMinutes() === 0 && end.getHours() === 0 && end.getMinutes() === 0 && end > start && (end.getTime() - start.getTime()) <= DAY_MS;
    if (allDay) return 'All day';
    if (!sameDay) return start.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
    return start.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) + ' - ' + end.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }
  function eventDate(event) {
    const date = new Date(event.starts_at);
    return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  }
  function normalizedTitle(title) {
    return String(title || '').toLocaleLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .replace(/\b(restaurante|restaurant|reservation|booking)\b/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
  }
  function cleanEvents(events) {
    const seen = new Set();
    return events.filter(event => {
      const title = String(event.title || '').trim();
      if (/^(week|vecka)\s+\d+\s+(of|av)\s+\d{4}$/i.test(title)) return false;
      const key = [event.starts_at, event.ends_at, normalizedTitle(title)].join('|');
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  async function loadEvents() {
    const current = auth();
    const from = windowStart().toISOString();
    const to = new Date(windowStart().getTime() + 70 * DAY_MS).toISOString();
    const result = await current.client.from('calendar_events')
      .select('id, title, category, starts_at, ends_at, provider')
      .eq('user_id', current.session.user.id)
      .gte('starts_at', from)
      .lt('starts_at', to)
      .order('starts_at', { ascending: true });
    if (result.error) throw new Error('Could not read calendar events: ' + result.error.message);
    return cleanEvents(result.data || []);
  }
  function eventNode(event) {
    return el('li', { class: 'calendar-event' },
      el('div', { class: 'calendar-event-time' }, eventDate(event) + ' · ' + eventTime(event)),
      el('strong', null, event.title || 'Untitled event'),
      event.category && event.category !== 'uncategorized' ? el('span', { class: 'calendar-event-category' }, event.category) : null);
  }
  function renderWeeks(container, events) {
    const byWeek = weekWindows().map(week => ({ week, events: events.filter(event => {
      const start = new Date(event.starts_at);
      return start >= week.from && start < week.to;
    }) }));
    const list = el('div', { class: 'calendar-weeks' });
    byWeek.forEach(({ week, events: weekEvents }) => {
      list.appendChild(el('section', { class: 'card calendar-week' },
        el('div', { class: 'card-title' }, el('h3', null, weekLabel(week.from, week.to)), el('span', { class: 'tiny muted' }, weekEvents.length + ' event' + (weekEvents.length === 1 ? '' : 's'))),
        weekEvents.length ? el('ul', { class: 'calendar-event-list' }, weekEvents.map(eventNode)) : el('p', { class: 'small muted' }, 'No events in this week')));
    });
    container.appendChild(list);
  }
  async function render(container) {
    container.appendChild(el('div', { class: 'view-head' },
      el('div', null, el('div', { class: 'eyebrow' }, 'Calendar'), el('h1', null, 'Your Google Calendar'), el('p', { class: 'secondary' }, 'The last ten weeks of events StressLess can use for context.'))));
    const body = el('div', { class: 'calendar-view stack' });
    container.appendChild(body);
    const controls = el('div', { class: 'card calendar-connection' });
    const statusLine = el('p', { class: 'small secondary' }, 'Checking connection...');
    const actions = el('div', { class: 'row' });
    const eventsRoot = el('div');
    controls.append(statusLine, actions);
    body.append(controls, eventsRoot);
    let connection = null;
    const setBusy = (busy) => actions.querySelectorAll('button').forEach(button => { button.disabled = busy; });
    const showError = error => { SL.clear(eventsRoot); eventsRoot.appendChild(el('div', { class: 'card error-card' }, el('h3', null, 'Calendar unavailable'), el('p', { class: 'small' }, error.message || String(error)))); };
    const paint = async () => {
      try {
        const status = await edge('status');
        connection = (status.connections || []).find(item => item.status === 'connected') || (status.connections || [])[0] || null;
        SL.clear(actions);
        if (!connection || connection.status !== 'connected') {
          statusLine.textContent = 'No Google Calendar is connected to this account.';
          actions.appendChild(el('button', { class: 'btn btn-primary', type: 'button', onclick: async () => {
            setBusy(true);
            try { const result = await edge('authorize'); location.href = result.authorizationUrl; }
            catch (error) { setBusy(false); showError(error); }
          } }, SL.icon('calendar', { size: 16 }), 'Connect Google Calendar'));
          SL.clear(eventsRoot);
          eventsRoot.appendChild(el('div', { class: 'card empty' }, el('h2', null, 'Connect your calendar'), el('p', null, 'Authorize read-only access to show your past ten weeks.')));
          return;
        }
        statusLine.textContent = 'Connected' + (connection.last_synced_at ? ' · last synced ' + new Date(connection.last_synced_at).toLocaleString() : ' · not synced yet');
        actions.append(
          el('button', { class: 'btn btn-primary', type: 'button', onclick: async () => {
            setBusy(true);
            try { const result = await edge('sync'); SL.toast((result.imported || 0) + ' calendar events synced', { kind: 'success' }); await paint(); }
            catch (error) { setBusy(false); showError(error); }
          } }, SL.icon('refresh', { size: 16 }), 'Sync now'),
          el('button', { class: 'btn btn-danger', type: 'button', onclick: async () => {
            if (!window.confirm('Disconnect Google Calendar and remove imported events?')) return;
            setBusy(true);
            try { await edge('disconnect'); await paint(); }
            catch (error) { setBusy(false); showError(error); }
          } }, SL.icon('x', { size: 16 }), 'Disconnect'));
        const events = await loadEvents();
        SL.clear(eventsRoot);
        renderWeeks(eventsRoot, events);
      } catch (error) { statusLine.textContent = 'Could not load calendar connection'; showError(error); }
    };
    await paint();
  }
  SL.router.register('calendar', { title: 'Calendar', render });
})();
