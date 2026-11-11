import type { Metadata } from 'next';
import Link from 'next/link';
import { DemoButton } from '@/components/auth/DemoButton';

export const metadata: Metadata = { title: 'Project' };

const SECTIONS = [
  { href: '/project/process', title: 'The process', text: 'Two prototypes, from a simulated person to an app that runs on real data, and the report.' },
  { href: '/project/product', title: 'The product', text: 'What StressLess does, how it connects your calendar, watch, location, phone and media, and what it looks like.' },
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
            StressLess connects your calendar, location, phone use and the music and shows you play to the biometrics your
            watch already collects, and explains what in your day shaped your body and your sleep.
          </p>
          <div className="row site-cta">
            <DemoButton label="Try the demo" />
            <Link className="btn" href="/project/product">Read about the product</Link>
          </div>
        </div>
        <img className="site-shot" src="/project/daily.jpg" alt="The StressLess Daily view: last night's sleep score and the button that generates the daily report" />
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
