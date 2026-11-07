'use client';
/* Header of the public project pages: tabs for the course deliverables, plus the demo and sign-in actions. */
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { DemoButton } from '../auth/DemoButton';

const TABS = [
  { href: '/project', label: 'Start' },
  { href: '/project/process', label: 'The process' },
  { href: '/project/product', label: 'The product' },
  { href: '/project/team', label: 'The team' },
];

export function SiteNav() {
  const path = usePathname();
  return (
    <header className="site-header">
      <Link className="brand site-brand" href="/project">
        <span className="pulse-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6" /></svg>
        </span>
        <span className="brand-text">StressLess</span>
      </Link>
      <nav className="site-tabs" aria-label="Project">
        {TABS.map((t) => (
          <Link key={t.href} href={t.href} aria-current={path === t.href ? 'page' : undefined}>{t.label}</Link>
        ))}
      </nav>
      <div className="site-actions">
        <Link className="btn btn-ghost btn-sm" href="/login">Sign in</Link>
        <DemoButton className="btn btn-primary btn-sm" />
      </div>
    </header>
  );
}
