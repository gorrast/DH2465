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
    title: 'Prototype 1',
    text: [
      'We started from a gap in wearables: they report a sleep score but not the reason behind it. The first prototype was a web demo that tested the product logic before any calendar or wearable was connected. Three simulated personas, Alex, Sam and Robin, each had a generated calendar, location history, minute-level heart rate, sleep and recovery data, so the statistical engine could be checked against causes we had planted ourselves.',
      'It had a tab for each idea: a morning report with up to four likely causes and a suggested calendar change, a replay of the day, a weekly view, reality checks, a what-if planner, data and privacy, and a look under the hood of the model. Three testers at a legal-tech scale-up found it cluttered and asked for fewer tabs.',
    ],
    shots: [
      { src: '/project/morning-reveal.png', alt: 'Morning report with three likely causes' },
      { src: '/project/replay.png', alt: 'Replay of the evening heart rate against the usual baseline' },
      { src: '/project/reality.png', alt: 'Reality check asking whether a calendar event happened' },
    ],
  },
  {
    title: 'Prototype 2',
    text: [
      'The second prototype runs on real data. An Android app syncs health and screen-time data, Google Calendar connects through a read-only login, Apple Health comes in as an export, and media history comes from Spotify, Netflix and YouTube exports and synced Last.fm and Steam accounts. Coffee and alcohol check-ins cover what the calendar cannot see.',
      'The tabs were cut down to a daily report, a weekly report and connecting your data, plus your account and data and privacy, in a navy and cream design. The reports are written by a language model from statistics the engine has already computed. Nine testers tried it on their own data, and their wish to compare with colleagues led to a sixth tab: Social, a demo of opt-in leaderboards and challenges.',
    ],
    shots: [
      { src: '/project/daily.jpg', alt: 'The daily report with last night\'s sleep score' },
      { src: '/project/weekly-patterns.jpg', alt: 'Recurring patterns ranked by their effect on sleep' },
      { src: '/project/weekly-report.jpg', alt: 'The weekly report' },
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
