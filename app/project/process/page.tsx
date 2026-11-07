import { existsSync } from 'node:fs';
import path from 'node:path';
import type { Metadata } from 'next';

export const metadata: Metadata = { title: 'The process' };

// Drop the final report at public/project/final-report.pdf; until then the page links the pre-study.
const FINAL_REPORT = existsSync(path.join(process.cwd(), 'public/project/final-report.pdf'));
const REPORT = FINAL_REPORT
  ? { href: '/project/final-report.pdf', label: 'Read the final report' }
  : { href: '/project/DH2465_Pre_Study.pdf', label: 'Read the pre-study' };

const STAGES = [
  {
    title: 'First prototype',
    text: [
      'We started from a gap in wearables: they report a sleep score but not the reason behind it, because the reason usually sits in the calendar. Without shared watch data yet, the first prototype simulates a person whose calendar, location history and watch data are generated from a known causal model.',
      'That let us build and check the core ideas against an answer key: a morning report with the likely causes of last night\'s score, a replay of the evening, reality checks when the calendar and the body disagree, and weekly patterns.',
    ],
    shots: [
      { src: '/project/morning-reveal.png', alt: 'Morning report with three likely causes' },
      { src: '/project/replay.png', alt: 'Replay of the evening heart rate against the usual baseline' },
      { src: '/project/reality.png', alt: 'Reality check asking whether a calendar event happened' },
    ],
  },
  {
    title: 'Second prototype',
    text: [
      'We rebuilt the prototype as a web app with accounts and moved from simulated to real data: a companion phone app that syncs health and screen-time data, Google Calendar, Apple Health and Google Takeout imports, and media services such as Spotify, Netflix, YouTube and Steam.',
      'Daily and weekly reports are now written by a language model from statistics the engine has already computed, so it narrates measured patterns instead of inventing them.',
    ],
    shots: [],
  },
  {
    title: 'Final prototype',
    text: [
      'The final prototype focuses on clarity. A new visual direction, "After Hours", puts the sleep score and one suggestion first and keeps the details a click away. Navigation went down to five tabs: Daily and Weekly reports, connecting data, the account, and data and privacy.',
      'We added check-ins for coffee and alcohol, which the calendar cannot see, and a shared demo account so anyone can try the app without signing up.',
    ],
    shots: [
      { src: '/project/after-hours-desktop.jpg', alt: 'The Daily view in the After Hours design on desktop' },
      { src: '/project/after-hours-mobile.jpg', alt: 'The Daily view on a phone' },
    ],
  },
];

export default function ProcessPage() {
  return (
    <>
      <section className="site-intro">
        <span className="eyebrow">The process</span>
        <h1>How StressLess came together</h1>
      </section>
      {STAGES.map((s) => (
        <section key={s.title} className="site-stage">
          <h2>{s.title}</h2>
          {s.text.map((t) => <p key={t} className="secondary">{t}</p>)}
          {s.shots.length ? (
            <div className="site-gallery">
              {s.shots.map((shot) => <img key={shot.src} src={shot.src} alt={shot.alt} loading="lazy" />)}
            </div>
          ) : null}
        </section>
      ))}
      <section className="site-stage site-report">
        <h2>Report</h2>
        <p className="secondary">The full write-up of the project, its method and results.</p>
        <a className="site-link" href={REPORT.href}>{REPORT.label} (PDF)</a>
      </section>
    </>
  );
}
