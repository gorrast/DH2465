'use strict';
/* StressLess frontend core: hyperscript, API client (with mock fixtures), router,
 * state, formatting, theme, toasts, icons, keyboard shortcuts.
 * Owned by the lead. Views must use window.SL and never touch innerHTML with data. */
(function () {
  const SL = { version: '0.1.0' };
  const params = new URLSearchParams(location.search);
  SL.mock = params.get('mock') === '1';

  // ------------------------------------------------------------------ DOM ---
  function appendChildren(node, children) {
    for (const c of children) {
      if (c === null || c === undefined || c === false) continue;
      if (Array.isArray(c)) { appendChildren(node, c); continue; }
      if (c instanceof Node) { node.appendChild(c); continue; }
      node.appendChild(document.createTextNode(String(c)));
    }
  }
  function applyAttrs(node, attrs) {
    if (!attrs) return;
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class' || k === 'className') node.setAttribute('class', v);
      else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
      else if (k === 'dataset' && typeof v === 'object') Object.assign(node.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v === true) node.setAttribute(k, '');
      else node.setAttribute(k, String(v));
    }
  }
  SL.el = function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    applyAttrs(node, attrs);
    appendChildren(node, children);
    return node;
  };
  const SVG_NS = 'http://www.w3.org/2000/svg';
  SL.svg = function svg(tag, attrs, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    applyAttrs(node, attrs);
    appendChildren(node, children);
    return node;
  };
  SL.clear = function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; };

  // ---------------------------------------------------------------- icons ---
  // Static, trusted SVG path data (no user data ever flows through here).
  const ICON_PATHS = {
    calendar: '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>',
    watch: '<rect x="6" y="6" width="12" height="12" rx="3"/><path d="M9 2h6M9 22h6M12 9v3l2 1"/>',
    map: '<path d="M12 21s-6-5.3-6-11a6 6 0 0 1 12 0c0 5.7-6 11-6 11z"/><circle cx="12" cy="10" r="2"/>',
    brain: '<path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0-2 3 3 3 0 0 0 2 3v1a3 3 0 0 0 3 3h3V4H9zM15 4a3 3 0 0 1 3 3v1a3 3 0 0 1 2 3 3 3 0 0 1-2 3v1a3 3 0 0 1-3 3h-3V4h3z"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    run: '<circle cx="15" cy="4" r="1.6"/><path d="M13 8l-3 3 3 2 1 5 3 3M13 8l4 1 2 3M10 11l-3 6-3 2"/>',
    users: '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20a6 6 0 0 1 12 0M14 20a4.5 4.5 0 0 1 7 -3"/>',
    plane: '<path d="M2 16l20-8-4 12-5-5-6 3 1-6z"/>',
    shield: '<path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4z"/><path d="M9 12l2 2 4-4"/>',
    coffee: '<path d="M4 9h12v6a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4V9zM16 10h2a2 2 0 0 1 0 4h-2M7 3v2M10 3v2M13 3v2"/>',
    flag: '<path d="M5 21V4h11l-1 4 1 4H5"/>',
    focus: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
    briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 12h18"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    check: '<path d="M5 12l5 5L20 7"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    play: '<path d="M7 5v14l11-7z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    'chevron-left': '<path d="M15 5l-7 7 7 7"/>',
    'chevron-right': '<path d="M9 5l7 7-7 7"/>',
    download: '<path d="M12 4v11M7 10l5 5 5-5M4 20h16"/>',
    refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    home: '<path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    heart: '<path d="M12 21s-7-4.6-9-9a5 5 0 0 1 9-3 5 5 0 0 1 9 3c-2 4.4-9 9-9 9z"/>',
    pulse: '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
    week: '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 13h3M13 13h3M8 17h3"/>',
    habits: '<path d="M4 19V9M10 19V5M16 19v-8M22 19H2"/>',
    inbox: '<path d="M3 13l2-8h14l2 8v6H3z"/><path d="M3 13h5l1 2h6l1-2h5"/>',
    planner: '<path d="M4 4h16v16H4z"/><path d="M4 10h16M10 4v16"/>',
    lab: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17h.01"/>',
    sparkles: '<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    bed: '<path d="M3 18v-6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v6M3 18h18M5 10V6h6v4"/>',
    thermometer: '<path d="M10 14V5a2 2 0 1 1 4 0v9a4 4 0 1 1-4 0z"/>',
    lungs: '<path d="M12 4v8M9 12c-3 0-5 3-5 7a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-7zM15 12c3 0 5 3 5 7a1 1 0 0 1-1 1h-3a1 1 0 0 1-1-1v-7z"/>',
    drop: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01"/>',
    dot: '<circle cx="12" cy="12" r="4"/>',
  };
  SL.icons = ICON_PATHS;
  SL.icon = function icon(name, opts) {
    const o = opts || {};
    const size = o.size || 18;
    const wrap = document.createElement('span');
    wrap.className = 'icon' + (o.class ? ' ' + o.class : '');
    wrap.setAttribute('aria-hidden', 'true');
    const path = ICON_PATHS[name] || ICON_PATHS.dot;
    // Trusted constant markup only.
    wrap.innerHTML = '<svg viewBox="0 0 24 24" width="' + size + '" height="' + size + '" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + path + '</svg>';
    return wrap;
  };
  SL.eventIcon = function (type) {
    return { meeting: 'briefcase', focus: 'focus', workout: 'run', social: 'users', travel: 'plane', personal: 'flag', protected: 'shield' }[type] || 'calendar';
  };

  // ------------------------------------------------------------------ API ---
  let fixturesLoaded = null;
  function loadFixtures() {
    if (fixturesLoaded) return fixturesLoaded;
    fixturesLoaded = Promise.all(['fixtures/fixtures-a.js', 'fixtures/fixtures-b.js'].map(src => new Promise(resolve => {
      const s = document.createElement('script');
      s.src = src; s.onload = resolve; s.onerror = resolve; document.head.appendChild(s);
    })));
    return fixturesLoaded;
  }
  async function mockResolve(method, path, body) {
    await loadFixtures();
    const fx = window.__FIXTURES__ || {};
    const bare = path.split('?')[0];
    const keys = [method + ' ' + path, method + ' ' + bare];
    let hit;
    for (const k of keys) if (k in fx) { hit = fx[k]; break; }
    if (hit === undefined) {
      const candidates = Object.keys(fx).filter(k => k.startsWith(method + ' ') && bare.startsWith(k.slice(method.length + 1).split('?')[0]))
        .sort((a, b) => b.length - a.length);
      if (candidates.length) hit = fx[candidates[0]];
    }
    if (hit === undefined) throw new Error('No fixture for ' + method + ' ' + path);
    const value = typeof hit === 'function' ? hit(method, path, body) : hit;
    return JSON.parse(JSON.stringify(value));
  }
  async function request(method, path, body) {
    if (SL.mock) return mockResolve(method, path, body);
    const init = { method, headers: {} };
    if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    const res = await fetch(path, init);
    const ct = res.headers.get('content-type') || '';
    if (!res.ok) {
      let msg = res.status + ' ' + res.statusText;
      try { const j = await res.json(); if (j && j.error) msg = j.error; } catch (e) { /* ignore */ }
      throw new Error(msg);
    }
    if (ct.indexOf('application/json') >= 0) return res.json();
    return res.text();
  }
  SL.api = {
    get: (path) => request('GET', path),
    post: (path, body) => request('POST', path, body === undefined ? {} : body),
  };

  // ---------------------------------------------------------------- state ---
  const store = {}; const listeners = {};
  SL.state = {
    get: (k) => store[k],
    set: (k, v) => { store[k] = v; (listeners[k] || []).forEach(fn => { try { fn(v); } catch (e) { SL.log('error', 'state listener ' + k, e); } }); },
    on: (k, fn) => { (listeners[k] = listeners[k] || []).push(fn); return () => { listeners[k] = (listeners[k] || []).filter(f => f !== fn); }; },
  };
  SL.meta = () => store.meta || {};

  // ------------------------------------------------------------- formatting ---
  const pad2 = (n) => (n < 10 ? '0' : '') + n;
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const DAYS_LONG = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  function parseISODate(iso) { const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); }
  function toISODate(dt) { return dt.getFullYear() + '-' + pad2(dt.getMonth() + 1) + '-' + pad2(dt.getDate()); }
  SL.fmt = {
    score: (n) => (n === null || n === undefined) ? '–' : String(Math.round(n)),
    num: (n, digits) => (n === null || n === undefined || Number.isNaN(n)) ? '–' : Number(n).toFixed(digits === undefined ? 0 : digits),
    signed: (n, digits) => { if (n === null || n === undefined || Number.isNaN(n)) return '–'; const d = digits === undefined ? 0 : digits; const v = Math.abs(Number(n)).toFixed(d); const zero = Number(v) === 0; return (zero ? '' : (n > 0 ? '+' : '−')) + v; },
    pct: (n, digits) => (n === null || n === undefined) ? '–' : SL.fmt.signed(n, digits === undefined ? 0 : digits) + ' %',
    hm: (iso) => { if (!iso) return '–'; const m = String(iso).match(/T(\d{2}):(\d{2})/); return m ? m[1] + ':' + m[2] : String(iso); },
    day: (iso) => { if (!iso) return '–'; const d = parseISODate(iso); return DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()]; },
    dayLong: (iso) => { if (!iso) return '–'; const d = parseISODate(iso); return DAYS_LONG[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear(); },
    minutes: (n) => { if (n === null || n === undefined) return '–'; const m = Math.round(Math.abs(n)); const h = Math.floor(m / 60), r = m % 60; const s = n < 0 ? '−' : ''; if (h && r) return s + h + ' h ' + r + ' min'; if (h) return s + h + ' h'; return s + r + ' min'; },
    bpm: (n) => (n === null || n === undefined) ? '–' : Math.round(n) + ' bpm',
    hourFloat: (h) => { if (h === null || h === undefined) return '–'; const hh = Math.floor(h), mm = Math.round((h - hh) * 60); return pad2(hh % 24) + ':' + pad2(mm); },
  };
  SL.date = {
    parse: parseISODate,
    toISO: toISODate,
    addDays: (iso, n) => { const d = parseISODate(iso); d.setDate(d.getDate() + n); return toISODate(d); },
    today: () => (store.meta && store.meta.today) || toISODate(new Date()),
    isFuture: (iso) => iso > SL.date.today(),
    weekday: (iso) => DAYS[parseISODate(iso).getDay()],
    diffDays: (a, b) => Math.round((parseISODate(b) - parseISODate(a)) / 86400000),
  };

  // -------------------------------------------------------------- palette ---
  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  SL.palette = {
    event: (type) => cssVar('--evt-' + (type || 'meeting')) || cssVar('--evt-meeting'),
    series: (i) => cssVar('--series-' + i),
    status: (kind) => cssVar('--status-' + kind),
    accent: () => cssVar('--accent'),
    ink: (level) => cssVar('--ink-' + (level || 'primary')),
    hairline: () => cssVar('--hairline'),
    var: cssVar,
  };
  SL.EVENT_TYPES = ['meeting', 'focus', 'workout', 'social', 'travel', 'personal', 'protected'];
  SL.EVENT_LABELS = { meeting: 'Meeting', focus: 'Focus', workout: 'Workout', social: 'Social', travel: 'Travel', personal: 'Personal', protected: 'Protected' };

  // ---------------------------------------------------------------- theme ---
  SL.theme = {
    get: () => document.documentElement.getAttribute('data-theme') || 'dark',
    set: (t) => { document.documentElement.setAttribute('data-theme', t); try { localStorage.setItem('sl-theme', t); } catch (e) { /* ignore */ } SL.state.set('theme', t); },
    toggle: () => SL.theme.set(SL.theme.get() === 'dark' ? 'light' : 'dark'),
  };
  (function initTheme() { let t = 'dark'; try { t = localStorage.getItem('sl-theme') || (params.get('theme') || 'dark'); } catch (e) { /* ignore */ } document.documentElement.setAttribute('data-theme', t); })();

  // ---------------------------------------------------------------- toast ---
  SL.toast = function toast(message, opts) {
    const o = opts || {};
    const root = document.getElementById('toasts');
    if (!root) return;
    const node = SL.el('div', { class: 'toast toast-' + (o.kind || 'info'), role: 'status' }, SL.icon(o.kind === 'error' ? 'alert' : (o.kind === 'success' ? 'check' : 'info'), { size: 16 }), SL.el('span', null, message));
    root.appendChild(node);
    setTimeout(() => node.classList.add('show'), 10);
    setTimeout(() => { node.classList.remove('show'); setTimeout(() => node.remove(), 300); }, o.duration || 3200);
  };

  // -------------------------------------------------------------- logging ---
  SL.log = function log(level, message, err) {
    const stack = err && err.stack ? String(err.stack) : (err ? String(err) : '');
    (level === 'error' ? console.error : console.warn)('[StressLess]', message, err || '');
    const box = document.getElementById('sl-errors');
    if (box && level === 'error') { box.appendChild(SL.el('div', { class: 'sl-error-entry', 'data-error': '1' }, message + ' ' + stack)); }
    if (!SL.mock) { try { fetch('/api/log', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level, message, stack }) }).catch(() => {}); } catch (e) { /* ignore */ } }
  };
  window.addEventListener('error', (e) => SL.log('error', e.message, e.error));
  window.addEventListener('unhandledrejection', (e) => SL.log('error', 'Unhandled rejection: ' + (e.reason && e.reason.message ? e.reason.message : String(e.reason)), e.reason));

  // --------------------------------------------------------------- router ---
  const views = {};
  const NAV = [
    { name: 'morning', label: 'Morning', icon: 'moon', key: '1', withDate: true },
    { name: 'replay', label: 'Replay', icon: 'pulse', key: '2', withDate: true, dateOffset: -1 },
    { name: 'week', label: 'Week', icon: 'week', key: '3' },
    { name: 'habits', label: 'Habits', icon: 'habits', key: '4' },
    { name: 'reality', label: 'Reality check', icon: 'inbox', key: '5' },
    { name: 'planner', label: 'Planner', icon: 'planner', key: '6' },
    { name: 'data', label: 'Data & privacy', icon: 'lock', key: '7' },
    { name: 'lab', label: 'Under the hood', icon: 'lab', key: '8' },
  ];
  SL.NAV = NAV;
  let current = { name: null, cleanup: null };
  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, '');
    const [pathPart, queryPart] = raw.split('?');
    const segs = pathPart.split('/').filter(Boolean);
    const query = {};
    if (queryPart) new URLSearchParams(queryPart).forEach((v, k) => { query[k] = v; });
    return { name: segs[0] || 'morning', params: segs.slice(1), query };
  }
  function defaultHashFor(item) {
    if (!item.withDate) return '#/' + item.name;
    const d = item.dateOffset ? SL.date.addDays(SL.date.today(), item.dateOffset) : SL.date.today();
    return '#/' + item.name + '/' + d;
  }
  SL.router = {
    register: (name, view) => { views[name] = view; },
    go: (hash) => { if (location.hash === hash) render(); else location.hash = hash; },
    current: () => parseHash(),
    hashFor: (name) => { const item = NAV.find(n => n.name === name); return item ? defaultHashFor(item) : '#/' + name; },
  };
  function setActiveNav(name) {
    document.querySelectorAll('.rail a[data-view]').forEach(a => a.classList.toggle('active', a.dataset.view === name));
  }
  async function render() {
    const route = parseHash();
    const container = document.getElementById('view');
    if (!container) return;
    if (current.cleanup) { try { current.cleanup(); } catch (e) { SL.log('error', 'cleanup ' + current.name, e); } }
    current = { name: route.name, cleanup: null };
    const view = views[route.name];
    SL.clear(container);
    setActiveNav(route.name);
    document.body.dataset.view = route.name;
    if (!view) {
      container.appendChild(SL.el('div', { class: 'card empty' }, SL.el('h2', null, 'View not found'), SL.el('p', null, 'No view registered for "' + route.name + '".')));
      return;
    }
    document.title = (view.title || route.name) + ' · StressLess';
    container.setAttribute('aria-busy', 'true');
    try {
      const cleanup = await view.render(container, { params: route.params, query: route.query });
      if (typeof cleanup === 'function') current.cleanup = cleanup;
    } catch (e) {
      SL.log('error', 'render ' + route.name + ': ' + (e && e.message), e);
      SL.clear(container);
      container.appendChild(SL.el('div', { class: 'card error-card' },
        SL.el('h2', null, 'Something went wrong'),
        SL.el('p', null, String(e && e.message || e)),
        SL.el('button', { class: 'btn', onclick: () => render() }, 'Retry')));
    } finally {
      container.removeAttribute('aria-busy');
    }
    SL.state.set('route', route);
  }
  window.addEventListener('hashchange', render);

  // ------------------------------------------------------------ shell/nav ---
  function buildRail() {
    const rail = document.getElementById('rail-nav');
    if (!rail) return;
    SL.clear(rail);
    NAV.forEach(item => {
      const a = SL.el('a', { href: defaultHashFor(item), class: 'rail-link', 'data-view': item.name, title: item.label + ' (' + item.key + ')' },
        SL.icon(item.icon, { size: 20 }), SL.el('span', { class: 'rail-label' }, item.label), SL.el('kbd', { class: 'rail-key' }, item.key));
      a.addEventListener('click', (e) => { e.preventDefault(); SL.router.go(defaultHashFor(item)); });
      rail.appendChild(a);
    });
  }
  function buildTopbar() {
    const meta = SL.meta();
    const chip = document.getElementById('persona-chip');
    if (chip) {
      SL.clear(chip);
      chip.appendChild(SL.el('span', { class: 'avatar' }, (meta.persona && meta.persona.name || 'A').slice(0, 1)));
      chip.appendChild(SL.el('span', { class: 'persona-name' }, meta.persona ? meta.persona.name : 'Demo'));
      chip.appendChild(SL.el('span', { class: 'persona-tag' }, meta.source === 'demo' ? (meta.anchor_mode ? 'Demo date ' + SL.fmt.day(meta.today) : 'Demo data') : 'Imported data'));
      chip.appendChild(SL.icon('chevron-right', { size: 14, class: 'chev' }));
      if (!chip.dataset.bound) {
        chip.dataset.bound = '1';
        chip.addEventListener('click', (e) => { e.stopPropagation(); togglePersonaMenu(); });
        document.addEventListener('click', () => togglePersonaMenu(false));
      }
    }
    renderPersonaMenu();
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) {
      const paint = () => { SL.clear(themeBtn); themeBtn.appendChild(SL.icon(SL.theme.get() === 'dark' ? 'sun' : 'moon', { size: 18 })); themeBtn.setAttribute('aria-label', 'Switch to ' + (SL.theme.get() === 'dark' ? 'light' : 'dark') + ' theme'); };
      paint();
      if (!themeBtn.dataset.bound) { themeBtn.dataset.bound = '1'; themeBtn.addEventListener('click', () => { SL.theme.toggle(); paint(); render(); }); }
    }
    const tourBtn = document.getElementById('tour-button');
    if (tourBtn && !tourBtn.dataset.bound) {
      tourBtn.dataset.bound = '1';
      tourBtn.addEventListener('click', () => { if (SL.tour && SL.tour.start) SL.tour.start(); else SL.toast('Tour not available'); });
    }
    const reason = document.getElementById('reasoner-chip');
    if (reason) { SL.clear(reason); reason.appendChild(SL.icon('brain', { size: 14 })); reason.appendChild(SL.el('span', null, meta.reasoning_mode === 'claude' ? 'Reasoning: Claude' : 'Reasoning: on-device rules')); }
    renderHistoryPill();
  }

  function togglePersonaMenu(force) {
    const menu = document.getElementById('persona-menu');
    const chip = document.getElementById('persona-chip');
    if (!menu || !chip) return;
    const open = force === undefined ? menu.hidden : !!force;
    menu.hidden = !open;
    chip.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function renderPersonaMenu() {
    const menu = document.getElementById('persona-menu');
    if (!menu) return;
    const meta = SL.meta();
    SL.clear(menu);
    menu.appendChild(SL.el('div', { class: 'persona-menu-title' }, 'Demo persona', SL.el('span', { class: 'muted tiny' }, ' · seed ' + (meta.seed === undefined ? '–' : meta.seed))));
    (meta.personas || []).forEach(p => {
      const isCurrent = meta.persona && meta.persona.key === p.key;
      const item = SL.el('button', { class: 'persona-item' + (isCurrent ? ' current' : ''), role: 'menuitem', type: 'button', 'data-persona': p.key,
        onclick: (e) => { e.stopPropagation(); togglePersonaMenu(false); if (!isCurrent) SL.switchPersona(p.key); } },
        SL.el('span', { class: 'avatar' }, (p.name || '?').slice(0, 1)),
        SL.el('span', { class: 'persona-item-body' }, SL.el('span', { class: 'persona-item-name' }, p.name), SL.el('span', { class: 'persona-item-tag' }, p.tagline || '')),
        isCurrent ? SL.icon('check', { size: 16 }) : (p.ready === false ? SL.el('span', { class: 'badge badge-low' }, 'preparing') : null));
      menu.appendChild(item);
    });
    menu.appendChild(SL.el('div', { class: 'persona-menu-foot muted tiny' }, 'Same engine, different person. Seed and import options live under Data & privacy.'));
  }
  SL.switchPersona = async function switchPersona(key, seed) {
    const meta = SL.meta();
    const name = ((meta.personas || []).find(p => p.key === key) || {}).name || key;
    SL.busy({ title: 'Simulating 70 days of ' + name + "'s life", steps: ['Booking the calendar', 'Tracing locations with Maps', 'Simulating heart rate and sleep', 'Fitting the personal model'] });
    try {
      await SL.api.post('/api/persona', { persona: key, seed: seed === undefined ? meta.seed : seed });
      await SL.refreshMeta();
      SL.state.set('historyDays', null);
      SL.busy(null);
      SL.router.go('#/morning/' + SL.date.today());
      SL.toast('Now showing ' + name, { kind: 'success' });
    } catch (e) {
      SL.busy(null);
      SL.log('error', 'Persona switch failed: ' + (e && e.message), e);
      SL.toast('Could not switch persona: ' + (e && e.message), { kind: 'error' });
    }
  };

  // -------------------------------------------------------- history pill ---
  function renderHistoryPill() {
    const pill = document.getElementById('history-pill');
    if (!pill) return;
    const hd = SL.state.get('historyDays');
    SL.clear(pill);
    if (hd === null || hd === undefined) { pill.hidden = true; return; }
    pill.hidden = false;
    pill.appendChild(SL.icon('info', { size: 14 }));
    pill.appendChild(SL.el('span', null, 'Using ' + hd + ' nights of history'));
    pill.appendChild(SL.el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => SL.state.set('historyDays', null) }, 'Reset'));
  }
  SL.state.on('historyDays', () => { renderHistoryPill(); render(); });

  // ------------------------------------------------------------- modal ---
  SL.modal = {
    confirm: (opts) => new Promise((resolve) => {
      const o = opts || {};
      const root = document.getElementById('modal-root') || document.body;
      let backdrop;
      const close = (val) => { if (backdrop) backdrop.remove(); document.removeEventListener('keydown', onKey); resolve(val); };
      const onKey = (e) => { if (e.key === 'Escape') { e.preventDefault(); close(false); } };
      const confirmBtn = SL.el('button', { class: 'btn ' + (o.danger ? 'btn-danger' : 'btn-primary'), type: 'button', onclick: () => close(true) }, o.confirmLabel || 'Confirm');
      backdrop = SL.el('div', { class: 'modal-backdrop', onclick: (e) => { if (e.target === backdrop) close(false); } },
        SL.el('div', { class: 'modal card raised', role: 'dialog', 'aria-modal': 'true', 'aria-label': o.title || 'Confirm' },
          SL.el('h3', null, o.title || 'Are you sure?'),
          SL.el('p', { class: 'secondary' }, o.body || ''),
          SL.el('div', { class: 'row modal-actions' },
            SL.el('button', { class: 'btn btn-ghost', type: 'button', onclick: () => close(false) }, o.cancelLabel || 'Cancel'),
            confirmBtn)));
      root.appendChild(backdrop);
      document.addEventListener('keydown', onKey);
      setTimeout(() => confirmBtn.focus(), 20);
    }),
  };

  // -------------------------------------------------------------- busy ---
  let busyTimer = null;
  SL.busy = function busy(opts) {
    const root = document.getElementById('busy-root') || document.body;
    SL.clear(root);
    if (busyTimer) { clearInterval(busyTimer); busyTimer = null; }
    if (!opts) return;
    const o = typeof opts === 'string' ? { title: opts } : opts;
    const steps = o.steps || [];
    const list = SL.el('ol', { class: 'stepper' }, steps.map((t, i) => SL.el('li', { class: i === 0 ? 'active' : '' }, SL.el('span', { class: 'step-dot' }), t)));
    root.appendChild(SL.el('div', { class: 'busy-backdrop', role: 'status', 'aria-live': 'polite' },
      SL.el('div', { class: 'busy card raised' }, SL.el('div', { class: 'row' }, SL.el('span', { class: 'spinner' }), SL.el('h3', { style: { margin: 0 } }, o.title || 'Working…')), steps.length ? list : null)));
    if (steps.length > 1) {
      let idx = 0;
      busyTimer = setInterval(() => {
        idx = Math.min(idx + 1, steps.length - 1);
        Array.from(list.children).forEach((li, i) => { li.classList.toggle('active', i === idx); li.classList.toggle('done', i < idx); });
      }, o.stepMs || 700);
    }
  };
  SL.replay = null;

  // ------------------------------------------------------------- keyboard ---
  document.addEventListener('keydown', (e) => {
    const tag = (e.target && e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.metaKey || e.ctrlKey || e.altKey) return;
    if (SL.tour && SL.tour.active && SL.tour.active()) return; // tour owns keys while open
    const item = NAV.find(n => n.key === e.key);
    if (item) { e.preventDefault(); SL.router.go(defaultHashFor(item)); return; }
    if (e.key === 't' || e.key === 'T') { e.preventDefault(); if (SL.tour && SL.tour.toggle) SL.tour.toggle(); return; }
    if (e.key === '?') { SL.toast('Keys: 1–8 views · ←/→ change day · t tour · d toggle theme'); return; }
    if (e.key === 'd') { SL.theme.toggle(); buildTopbar(); render(); return; }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      const route = parseHash();
      const item2 = NAV.find(n => n.name === route.name);
      if (item2 && item2.withDate) {
        const cur = route.params[0] || SL.date.today();
        const next = SL.date.addDays(cur, e.key === 'ArrowLeft' ? -1 : 1);
        const meta = SL.meta();
        const max = item2.dateOffset ? SL.date.addDays(meta.today || SL.date.today(), item2.dateOffset) : (meta.today || SL.date.today());
        if (next > SL.date.addDays(max, 7) || (meta.start && next < meta.start)) return;
        e.preventDefault();
        SL.router.go('#/' + route.name + '/' + next);
      }
    }
  });

  // ----------------------------------------------------------------- boot ---
  SL.refreshMeta = async function refreshMeta() {
    const meta = await SL.api.get('/api/meta');
    SL.state.set('meta', meta);
    buildRail();
    buildTopbar();
    return meta;
  };
  SL.ready = new Promise((resolve) => {
    document.addEventListener('DOMContentLoaded', async () => {
      store.historyDays = null;
      try {
        await SL.refreshMeta();
      } catch (e) {
        SL.log('error', 'Could not load /api/meta: ' + (e && e.message), e);
        SL.state.set('meta', { today: toISODate(new Date()), persona: { name: 'Demo' }, source: 'demo' });
        buildRail(); buildTopbar();
        SL.toast('Could not reach the StressLess server', { kind: 'error' });
      }
      if (!location.hash) location.hash = '#/morning/' + SL.date.today();
      await render();
      if (params.get('tour') === '1' && SL.tour && SL.tour.start) setTimeout(() => SL.tour.start(), 400);
      resolve(SL);
    });
  });

  window.SL = SL;
})();
