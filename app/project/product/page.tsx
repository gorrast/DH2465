import type { Metadata } from 'next';
import { DemoButton } from '@/components/auth/DemoButton';

export const metadata: Metadata = { title: 'The product' };

const SOURCES = [
  { title: 'Calendar', text: 'what you did' },
  { title: 'Watch', text: 'how your body reacted' },
  { title: 'Location', text: 'where you were' },
  { title: 'Reasoning', text: 'works out why' },
];

const FEATURES = [
  { title: 'Daily report', text: 'Each morning: your sleep score, the likely causes from yesterday\'s calendar with their evidence, and one change you can put straight into tonight\'s calendar.' },
  { title: 'Weekly report', text: 'Patterns that repeat across weeks, such as how meeting-heavy days or late workouts affect the next night, ranked by effect.' },
  { title: 'Reality checks', text: 'When the calendar and your location or heart rate disagree, StressLess asks: "Did you actually do this?" Your answer updates the patterns.' },
  { title: 'Fun statistics', text: 'Playful, non-medical correlations with your music, shows, videos and games.' },
  { title: 'Connect your data', text: 'Apple Health through the companion app, Google Calendar, Google Takeout, and media services.' },
  { title: 'Data and privacy', text: 'See what is connected and what is read, and delete everything with one action.' },
];

const SHOTS = [
  { src: '/project/morning.png', alt: 'Morning report', caption: 'The morning report' },
  { src: '/project/morning-reveal.png', alt: 'Morning report with likely causes', caption: 'Three likely causes, with evidence' },
  { src: '/project/replay.png', alt: 'Evening replay', caption: 'Replay of the evening' },
  { src: '/project/habits.png', alt: 'Habits ranked by effect', caption: 'Habits ranked by effect' },
  { src: '/project/planner.png', alt: 'Planner', caption: 'Planning a calmer evening' },
  { src: '/project/data.png', alt: 'Data and privacy', caption: 'Data and privacy' },
];

export default function ProductPage() {
  return (
    <>
      <section className="site-intro">
        <span className="eyebrow">The product</span>
        <h1>Let your calendar explain your body</h1>
        <p className="site-lede">
          Wearables already measure heart rate, HRV and sleep. They cannot see the late meeting, the back-to-back afternoon or
          the evening out. StressLess matches every calendar event to how your body responded that day and the night after,
          learns which patterns repeat, and suggests one concrete change at a time.
        </p>
        <div className="row site-cta">
          <DemoButton label="Try the demo" />
        </div>
      </section>
      <section className="site-section" aria-label="How it works">
        <div className="site-equation">
          {SOURCES.map((s, i) => (
            <div key={s.title} className="site-term">
              {i > 0 ? <span className="site-op" aria-hidden="true">+</span> : null}
              <div>
                <strong>{s.title}</strong>
                <span className="small muted">{s.text}</span>
              </div>
            </div>
          ))}
          <div className="site-term">
            <span className="site-op" aria-hidden="true">=</span>
            <div>
              <strong className="site-accent">StressLess</strong>
              <span className="small muted">the explanation</span>
            </div>
          </div>
        </div>
      </section>
      <section className="site-section" aria-labelledby="features">
        <h2 id="features">What it does</h2>
        <div className="site-cards">
          {FEATURES.map((f) => (
            <div key={f.title} className="card site-card">
              <h3>{f.title}</h3>
              <p className="secondary">{f.text}</p>
            </div>
          ))}
        </div>
      </section>
      <section className="site-section" aria-labelledby="look">
        <h2 id="look">Take a look</h2>
        <div className="site-gallery site-gallery-captioned">
          {SHOTS.map((s) => (
            <figure key={s.src}>
              <img src={s.src} alt={s.alt} loading="lazy" />
              <figcaption className="small muted">{s.caption}</figcaption>
            </figure>
          ))}
        </div>
        <p className="tiny muted">Screenshots use simulated data from the digital twin.</p>
      </section>
    </>
  );
}
