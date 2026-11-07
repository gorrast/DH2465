import type { ReactNode } from 'react';
import Link from 'next/link';
import { SiteNav } from '@/components/site/SiteNav';

/** Public project pages for the course: no sign-in needed. */
export default function ProjectLayout({ children }: { children: ReactNode }) {
  return (
    <div className="site">
      <SiteNav />
      <main className="site-main">{children}</main>
      <footer className="site-footer tiny muted">
        <span>StressLess · KTH DH2465</span>
        <Link href="https://github.com/gorrast/DH2465">Source code on GitHub</Link>
      </footer>
    </div>
  );
}
