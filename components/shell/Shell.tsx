'use client';
/* The app frame: rail, top bar, global keyboard shortcuts, persona switching and the overlay hosts. */
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, logClient } from '@/lib/api';
import { dates, fmt } from '@/lib/format';
import { NAV, defaultHref, parsePath } from '@/lib/nav';
import { getSupabase } from '@/lib/supabase/client';
import { Icon } from '../ui/Icon';
import { BusyHost, ModalHost, ToastHost, TooltipHost, busy, toast } from '../ui/overlays';
import { useTour } from '../tour/Tour';
import { AppCtx, type AppState, type Meta, type ReplayControls } from './AppContext';

const FALLBACK_META: Meta = { today: dates.localToday(), persona: { key: 'alex', name: 'Demo' }, personas: [], seed: 7, days: 70, source: 'demo' };

export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [historyDays, setHistoryDays] = useState<number | null>(null);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [menuOpen, setMenuOpen] = useState(false);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const replay = useRef<ReplayControls | null>(null);
  const today = meta?.today || dates.localToday();

  const go = useCallback((href: string) => router.push(href), [router]);

  const refreshMeta = useCallback(async () => {
    const m = await api.get<Meta>('/api/meta');
    setMeta(m);
    return m;
  }, []);

  // boot: theme from the attribute the inline script set, then meta, then the optional tour
  useEffect(() => {
    setTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark');
    getSupabase().auth.getUser().then(({ data }) => setUserEmail(data.user?.email ?? null));
    refreshMeta().catch((e) => {
      logClient('error', 'Could not load /api/meta: ' + (e && e.message), e);
      setMeta(FALLBACK_META);
      toast('Could not reach the StressLess server', { kind: 'error' });
    });
  }, [refreshMeta]);

  useEffect(() => {
    const onError = (e: ErrorEvent) => logClient('error', e.message, e.error);
    const onRejection = (e: PromiseRejectionEvent) => logClient('error', 'Unhandled rejection: ' + (e.reason && e.reason.message ? e.reason.message : String(e.reason)), e.reason);
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onRejection);
    };
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('sl-theme', next); } catch { /* ignore */ }
      return next;
    });
  }, []);

  const switchPersona = useCallback(async (key: string, seed?: number) => {
    const m = meta || FALLBACK_META;
    const name = (m.personas || []).find((p) => p.key === key)?.name || key;
    busy({ title: 'Simulating 70 days of ' + name + "'s life", steps: ['Booking the calendar', 'Tracing locations with Maps', 'Simulating heart rate and sleep', 'Fitting the personal model'] });
    try {
      await api.post('/api/persona', { persona: key, seed: seed === undefined ? m.seed : seed });
      const fresh = await refreshMeta();
      setHistoryDays(null);
      busy(null);
      router.push('/morning/' + fresh.today);
      toast('Now showing ' + name, { kind: 'success' });
    } catch (e: any) {
      busy(null);
      logClient('error', 'Persona switch failed: ' + (e && e.message), e);
      toast('Could not switch persona: ' + (e && e.message), { kind: 'error' });
    }
  }, [meta, refreshMeta, router]);

  const signOut = useCallback(async () => {
    await getSupabase().auth.signOut();
    router.replace('/login');
    router.refresh();
  }, [router]);

  const { controls: tour, element: tourElement } = useTour({ today, go, setHistoryDays, replay });

  // close the persona menu on any outside click
  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [menuOpen]);

  // keyboard: 1–8 views, ←/→ change day, t tour, d theme, ? help
  const route = parsePath(pathname);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = ((e.target as HTMLElement | null)?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.metaKey || e.ctrlKey || e.altKey) return;
      if (tour.active()) return; // the tour owns keys while open
      const item = NAV.find((n) => n.key === e.key);
      if (item) { e.preventDefault(); go(defaultHref(item, today)); return; }
      if (e.key === 't' || e.key === 'T') { e.preventDefault(); tour.toggle(); return; }
      if (e.key === '?') { toast('Keys: 1–8 views · ←/→ change day · t tour · d toggle theme'); return; }
      if (e.key === 'd') { toggleTheme(); return; }
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const item2 = NAV.find((n) => n.name === route.name);
        if (item2 && item2.withDate) {
          const cur = route.params[0] || today;
          const next = dates.addDays(cur, e.key === 'ArrowLeft' ? -1 : 1);
          const max = item2.dateOffset ? dates.addDays(today, item2.dateOffset) : today;
          if (next > dates.addDays(max, 7) || (meta?.start && next < meta.start)) return;
          e.preventDefault();
          go('/' + route.name + '/' + next);
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [go, today, toggleTheme, tour, route.name, route.params, meta?.start]);

  // ?tour=1 starts the presenter tour once the app is ready
  const tourRequested = search.get('tour') === '1';
  useEffect(() => {
    if (meta && tourRequested && !tour.active()) {
      const t = setTimeout(() => tour.start(), 400);
      return () => clearTimeout(t);
    }
  }, [meta, tourRequested]); // eslint-disable-line react-hooks/exhaustive-deps

  const value: AppState | null = useMemo(() => meta && ({
    meta, today: meta.today, refreshMeta, historyDays, setHistoryDays, theme, toggleTheme, switchPersona, replay, tour, go, userEmail, signOut,
  }), [meta, refreshMeta, historyDays, theme, toggleTheme, switchPersona, tour, go, userEmail, signOut]);

  const m = meta || FALLBACK_META;
  return (
    <>
      <div className="app">
        <aside className="rail" aria-label="Primary">
          <div className="brand">
            <span className="pulse-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6" /></svg>
            </span>
            <span className="brand-text">StressLess<small>the watch measures, the calendar explains</small></span>
          </div>
          <nav id="rail-nav" aria-label="Views">
            {NAV.map((item) => (
              <Link key={item.name} href={defaultHref(item, today)} className={'rail-link' + (route.name === item.name ? ' active' : '')} data-view={item.name} title={item.label + ' (' + item.key + ')'}>
                <Icon name={item.icon} size={20} />
                <span className="rail-label">{item.label}</span>
                <kbd className="rail-key">{item.key}</kbd>
              </Link>
            ))}
          </nav>
          <div className="rail-foot">
            {userEmail ? <span className="rail-label rail-user" title={userEmail}>{userEmail}</span> : null}
            <button className="btn btn-sm btn-ghost rail-signout" type="button" onClick={signOut} title="Sign out">
              <Icon name="logout" size={16} /><span className="rail-label">Sign out</span>
            </button>
          </div>
        </aside>
        <header className="topbar">
          <div className="persona-wrap">
            <button className="persona-chip" type="button" data-tour="persona" aria-haspopup="menu" aria-expanded={menuOpen} onClick={(e) => { e.stopPropagation(); setMenuOpen((o) => !o); }}>
              <span className="avatar">{(m.persona?.name || 'A').slice(0, 1)}</span>
              <span className="persona-name">{m.persona ? m.persona.name : 'Demo'}</span>
              <span className="persona-tag">{m.source === 'demo' ? (m.anchor_mode ? 'Demo date ' + fmt.day(m.today) : 'Demo data') : 'Imported data'}</span>
              <Icon name="chevron-right" size={14} className="chev" />
            </button>
            <div className="persona-menu" role="menu" hidden={!menuOpen}>
              <div className="persona-menu-title">Demo persona<span className="muted tiny">{' · seed ' + (m.seed === undefined ? '–' : m.seed)}</span></div>
              {(m.personas || []).map((p) => {
                const isCurrent = m.persona && m.persona.key === p.key;
                return (
                  <button key={p.key} className={'persona-item' + (isCurrent ? ' current' : '')} role="menuitem" type="button" data-persona={p.key}
                    onClick={(e) => { e.stopPropagation(); setMenuOpen(false); if (!isCurrent) switchPersona(p.key); }}>
                    <span className="avatar">{(p.name || '?').slice(0, 1)}</span>
                    <span className="persona-item-body"><span className="persona-item-name">{p.name}</span><span className="persona-item-tag">{p.tagline || ''}</span></span>
                    {isCurrent ? <Icon name="check" size={16} /> : p.ready === false ? <span className="badge badge-low">preparing</span> : null}
                  </button>
                );
              })}
              <div className="persona-menu-foot muted tiny">Same engine, different person. Seed and import options live under Data &amp; privacy.</div>
            </div>
          </div>
          <div className="reasoner-chip" data-tour="reasoner">
            <Icon name="brain" size={14} />
            <span>{m.reasoning_mode === 'claude' ? 'Reasoning: Claude' : 'Reasoning: on-device rules'}</span>
          </div>
          {historyDays !== null ? (
            <div className="history-pill">
              <Icon name="info" size={14} />
              <span>{'Using ' + historyDays + ' nights of history'}</span>
              <button className="btn btn-sm btn-ghost" type="button" onClick={() => setHistoryDays(null)}>Reset</button>
            </div>
          ) : null}
          <div className="spacer" />
          <button className="btn btn-sm" type="button" title="Presenter tour (t)" onClick={() => tour.start()}>Tour <kbd>t</kbd></button>
          <button className="btn btn-icon btn-ghost" type="button" aria-label={'Switch to ' + (theme === 'dark' ? 'light' : 'dark') + ' theme'} onClick={toggleTheme}>
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
          </button>
        </header>
        <main id="view" tabIndex={-1}>
          {value ? <AppCtx.Provider value={value}>{children}</AppCtx.Provider> : <div className="skeleton" style={{ height: '220px' }} />}
        </main>
      </div>
      <ToastHost />
      {tourElement}
      <ModalHost />
      <BusyHost />
      <TooltipHost />
    </>
  );
}
