import type { Metadata } from 'next';
import Link from 'next/link';
import { DemoButton } from '@/components/auth/DemoButton';

export const metadata: Metadata = { title: 'Project' };

const SECTIONS = [
  { href: '/project/process', title: 'The process', text: 'Three prototypes, from a simulated person to an app that runs on real data, and the final report.' },
  { href: '/project/product', title: 'The product', text: 'What StressLess does, how it connects calendar, location and watch data, and what it looks like.' },
  { href: '/project/team', title: 'The team', text: 'The six students behind StressLess.' },
];

export default function ProjectStart() {
  return (
    <>
      <section className="site-hero">
        <div>
          <span className="eyebrow">KTH DH2465</span>
          <h1>Wearables give you a score. StressLess tells you why.</h1>
          <p className="site-lede">
            StressLess connects your calendar and location history to the biometrics your watch already collects, and explains
            what in your day shaped your body and your sleep. No logging: the watch measures, the calendar explains.
          </p>
          <div className="row site-cta">
            <DemoButton label="Try the demo" />
            <Link className="btn" href="/project/product">Read about the product</Link>
          </div>
          <p className="tiny muted">The demo signs you in to a shared account with simulated data. No email or password needed.</p>
        </div>
        <img className="site-shot" src="/project/after-hours-desktop.jpg" alt="The StressLess Daily view: a sleep score ring above an evening summary" />
      </section>
      <section className="site-section">
        <div className="site-cards">
          {SECTIONS.map((s) => (
            <Link key={s.href} className="card site-card" href={s.href}>
              <h2>{s.title}</h2>
              <p className="secondary">{s.text}</p>
              <span className="small site-more">Open →</span>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
