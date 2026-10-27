'use client';
/* The app frame: rail, top bar, global keyboard shortcuts, persona switching and the overlay hosts. */
import Link from 'next/link';
import { motion, useReducedMotion } from 'motion/react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, logClient } from '@/lib/api';
import { dates, fmt } from '@/lib/format';
import { NAV, defaultHref, parsePath } from '@/lib/nav';
import { getSupabase } from '@/lib/supabase/client';
import { quietGroup, quietItem, calmTransition } from '../ui/Motion';
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
  const [moreOpen, setMoreOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [navFocused, setNavFocused] = useState(false);
  useEffect(() => { if (!navOpen) setNavFocused(false); }, [navOpen]);
  const reducedMotion = useReducedMotion();
  useEffect(() => setNavOpen(false), [pathname]);
  const primary = NAV.filter((item) => ['morning', 'replay', 'week', 'planner'].includes(item.name));
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

  useEffect(() => setMoreOpen(false), [pathname]);
  useEffect(() => {
    const dismiss = (event: PointerEvent | KeyboardEvent) => {
      const escape = event instanceof KeyboardEvent && event.key === 'Escape';
      if (event instanceof KeyboardEvent && !escape) return;
      document.querySelectorAll<HTMLDetailsElement>('.persona-wrap[open]').forEach((menu) => {
        if (escape || !menu.contains(event.target as Node)) {
          menu.open = false;
          if (escape) menu.querySelector('summary')?.focus();
        }
      });
      if (escape || !(event.target instanceof Element && event.target.closest('.mobile-more'))) setMoreOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('keydown', dismiss);
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', dismiss); };
  }, []);

  // keyboard: 1–9 views, ←/→ change day, t tour, d theme, ? help
  const route = parsePath(pathname);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = ((e.target as HTMLElement | null)?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.metaKey || e.ctrlKey || e.altKey) return;
      if (tour.active()) return; // the tour owns keys while open
      const item = NAV.find((n) => n.key === e.key);
      if (item) { e.preventDefault(); go(defaultHref(item, today)); return; }
      if (e.key === 't' || e.key === 'T') { e.preventDefault(); tour.toggle(); return; }
      if (e.key === '?') { toast('Keys: 1–9 views · ←/→ change day · t tour · d toggle theme'); return; }
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
      <a className="skip-link" href="#view">Skip to content</a>
      <div className="app">
        <div className={'rail-drawer' + (navOpen ? ' is-open' : '')}
          onPointerEnter={(e) => { if (e.pointerType === 'mouse') setNavOpen(true); }}
          onPointerLeave={(e) => { if (e.pointerType === 'mouse' && !e.currentTarget.contains(document.activeElement)) setNavOpen(false); }}
          onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setNavOpen(false); }}
          onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setNavOpen(false); e.currentTarget.querySelector('button')?.focus(); } }}>
          <button className="btn btn-icon rail-toggle" type="button" aria-label={navOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={navOpen} aria-controls="primary-sidebar" onClick={() => setNavOpen(open => !open)}>
            <Icon name={navOpen ? 'x' : 'menu'} size={20} /><span className="rail-toggle-copy">{navOpen ? 'Close' : 'Menu'}<small>{navOpen ? 'Esc to close' : 'Hover or click'}</small></span>
          </button>
        <motion.aside initial={false} animate={{ x: navOpen ? 0 : '-100%', visibility: navOpen ? 'visible' : 'hidden' }} transition={{ ...(reducedMotion ? { duration: 0 } : { type: 'spring' as const, stiffness: 170, damping: 28 }), visibility: { duration: 0, delay: navOpen || reducedMotion ? 0 : 0.8 } }} className="rail" id="primary-sidebar" aria-label="Primary" inert={!navOpen}>
          <div className="brand">
            <span className="pulse-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6" /></svg>
            </span>
            <span className="brand-text">StressLess<small>the watch measures, the calendar explains</small></span>
          </div>
          <motion.nav id="rail-nav" aria-label="Views" initial={false} animate={navOpen ? 'open' : 'closed'} variants={reducedMotion || navFocused ? undefined : quietGroup} onFocusCapture={() => setNavFocused(true)}>

            {primary.map((item) => (
              <motion.div key={item.name} variants={quietItem} animate={navFocused && navOpen ? 'open' : undefined} transition={{ ...calmTransition, duration: reducedMotion || navFocused ? 0 : 0.45 }}><Link href={defaultHref(item, today)} className={'rail-link' + (route.name === item.name || (item.name === 'week' && route.name === 'habits') || (item.name === 'morning' && route.name === 'reality') ? ' active' : '')} aria-current={route.name === item.name ? 'page' : undefined} data-view={item.name} title={item.label + ' (' + item.key + ')'}>
                <Icon name={item.icon} size={20} />
                <span className="rail-label">{item.label}</span>
                <kbd className="rail-key">{item.key}</kbd>
              </Link></motion.div>
            ))}
          </motion.nav>
          <div className="rail-secondary">
            <span className="nav-caption">Your wellbeing</span>
            {NAV.filter((item) => ['habits', 'reality', 'data'].includes(item.name)).map((item) => (
              <Link key={item.name} className={'rail-link' + (route.name === item.name ? ' active' : '')} href={defaultHref(item, today)} aria-current={route.name === item.name ? 'page' : undefined} title={item.label}>
                <Icon name={item.icon} size={18} /><span className="rail-label">{item.label}</span>
              </Link>
            ))}
            <details className="demo-nav">
              <summary className="rail-link" aria-label="Explore the demo" title="Explore the demo"><Icon name="lab" size={18} /><span className="rail-label">Explore the demo</span></summary>
              <Link className="rail-link" href="/lab" title="Under the hood"><Icon name="lab" size={18} /><span className="rail-label">Under the hood</span></Link>
              <Link className="rail-link" href="/media" title="Media lab"><Icon name="music" size={18} /><span className="rail-label">Media lab</span></Link>
              <Link className="rail-link" href="/fun-statistics" title="Fun statistics"><Icon name="sparkles" size={18} /><span className="rail-label">Fun statistics</span></Link>
            </details>
          </div>
          <div className="rail-foot">
            {userEmail ? <span className="rail-label rail-user" title={userEmail}>{userEmail}</span> : null}
            <button className="btn btn-sm btn-ghost rail-signout" type="button" onClick={signOut} title="Sign out">
              <Icon name="logout" size={16} /><span className="rail-label">Sign out</span>
            </button>
          </div>
        </motion.aside>
        </div>
        <header className="topbar">
          <details className="persona-wrap" key={pathname}>
            <summary className="persona-chip" data-tour="persona">
              <span className="avatar">{(m.persona?.name || 'A').slice(0, 1)}</span>
              <span className="persona-name">{m.persona ? m.persona.name : 'Demo'}</span>
              <span className="persona-tag">{m.source === 'demo' ? (m.anchor_mode ? 'Demo date ' + fmt.day(m.today) : 'Demo data') : 'Imported data'}</span>
              <Icon name="chevron-right" size={14} className="chev" />
            </summary>
            <div className="persona-menu">
              <div className="persona-menu-title">Demo persona<span className="muted tiny">{' · seed ' + (m.seed === undefined ? '–' : m.seed)}</span></div>
              {(m.personas || []).map((p) => {
                const isCurrent = m.persona && m.persona.key === p.key;
                return (
                  <button key={p.key} className={'persona-item' + (isCurrent ? ' current' : '')} type="button" data-persona={p.key}
                    onClick={(e) => { e.currentTarget.closest('details')?.removeAttribute('open'); if (!isCurrent) switchPersona(p.key); }}>
                    <span className="avatar">{(p.name || '?').slice(0, 1)}</span>
                    <span className="persona-item-body"><span className="persona-item-name">{p.name}</span><span className="persona-item-tag">{p.tagline || ''}</span></span>
                    {isCurrent ? <Icon name="check" size={16} /> : p.ready === false ? <span className="badge badge-low">preparing</span> : null}
                  </button>
                );
              })}
              <div className="persona-menu-foot muted tiny">Same engine, different person. Seed and import options live under Data &amp; privacy.</div>
            </div>
          </details>
          <div className="reasoner-chip" data-tour="reasoner" title="How this report was written">
            <Icon name="brain" size={14} />
            <span>{m.reasoning_mode === 'claude' ? 'AI-assisted report' : 'Rule-based report'}</span>
          </div>
          {historyDays !== null ? (
            <div className="history-pill">
              <Icon name="info" size={14} />
              <span>{'Using ' + historyDays + ' nights of history'}</span>
              <button className="btn btn-sm btn-ghost" type="button" onClick={() => setHistoryDays(null)}>Reset</button>
            </div>
          ) : null}
          <div className="spacer" />
          <div className="mobile-more">
            <button className="btn btn-icon btn-ghost" type="button" aria-label="More destinations" aria-expanded={moreOpen} aria-controls="more-destinations" onClick={() => setMoreOpen(!moreOpen)}><Icon name={moreOpen ? 'x' : 'inbox'} size={20} /></button>
            {moreOpen ? <nav id="more-destinations" aria-label="More destinations">{NAV.filter((item) => !primary.includes(item)).map((item) => <Link key={item.name} href={defaultHref(item, today)} onClick={() => setMoreOpen(false)}><Icon name={item.icon} size={18} />{item.label}</Link>)}<button className="btn btn-ghost" type="button" onClick={signOut}>Sign out</button></nav> : null}
          </div>
          <button className="btn btn-sm" type="button" title="Presenter tour (t)" onClick={() => tour.start()}>Tour <kbd>t</kbd></button>
          <button className="btn btn-icon btn-ghost" type="button" aria-label={'Switch to ' + (theme === 'dark' ? 'light' : 'dark') + ' theme'} onClick={toggleTheme}>
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
          </button>
        </header>
        <nav className="mobile-nav" aria-label="Primary mobile navigation">
          {primary.map((item) => { const active = route.name === item.name || (item.name === 'week' && route.name === 'habits') || (item.name === 'morning' && route.name === 'reality'); return <Link key={item.name} href={defaultHref(item, today)} aria-current={active ? 'page' : undefined}><Icon name={item.icon} size={21} /><span>{item.label}</span></Link>; })}
        </nav>
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
