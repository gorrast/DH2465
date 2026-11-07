import type { Metadata } from 'next';
import { DemoButton } from '@/components/auth/DemoButton';
import { Icon } from '@/components/ui/Icon';

export const metadata: Metadata = { title: 'The product' };

// Media marks: the bundled Simple Icons in public/brands, coloured as in the app (lib/app-brands.ts).
const MEDIA = [
  { key: 'spotify', name: 'Spotify', color: '#1ed760' },
  { key: 'netflix', name: 'Netflix', color: '#ed4254' },
  { key: 'youtube', name: 'YouTube', color: '#ff5a63' },
];

// How the data comes together: the sources, the two steps, and what comes out (the graphic below the intro).
const SOURCES: { icon: string; title: string; text: string; brands?: typeof MEDIA }[] = [
  { icon: 'calendar', title: 'Calendar', text: 'what you did' },
  { icon: 'watch', title: 'Watch', text: 'sleep, heart rate, HRV, steps' },
  { icon: 'map', title: 'Location', text: 'where you were' },
  { icon: 'screen', title: 'Phone usage', text: 'when you reached for your phone' },
  { icon: 'music', title: 'Media', text: 'what you play and watch', brands: MEDIA },
];
const SOURCE_H = 68;                           // px per source row, and the gap between rows: the links are drawn
const SOURCE_GAP = 12;                         // from each row's middle to the middle of the column
const SOURCES_H = SOURCES.length * SOURCE_H + (SOURCES.length - 1) * SOURCE_GAP;
const INSIGHTS = ['Which meetings weigh on you', 'What helps you wind down', 'When you reach for your phone'];

const FEATURES = [
  { title: 'Daily report', text: 'Each morning: your sleep score, the likely causes from yesterday\'s calendar with their evidence, and one change you can put straight into tonight\'s calendar.' },
  { title: 'Weekly report', text: 'Patterns that repeat across weeks, such as how meeting-heavy days or late workouts affect the next night, ranked by effect.' },
  { title: 'Reality checks', text: 'When the calendar and your location or heart rate disagree, StressLess asks: "Did you actually do this?" Your answer updates the patterns.' },
  { title: 'Fun statistics', text: 'Playful, non-medical correlations with your music, shows, videos and games.' },
  { title: 'Connect your data', text: 'Apple Health through the companion app, Google Calendar, Google Takeout, and media services.' },
  { title: 'Data and privacy', text: 'See what is connected and what is read, and delete everything with one action.' },
];

const SHOTS = [
  { src: '/project/daily.jpg', alt: 'The Daily view with last night\'s sleep score', caption: 'Last night, at a glance' },
  { src: '/project/daily-report.jpg', alt: 'A daily report with three links and a suggestion', caption: 'The daily report: what shaped last night' },
  { src: '/project/daily-patterns.jpg', alt: 'Similar day patterns, sleep stages and recovery markers', caption: 'Similar days, sleep stages and recovery' },
  { src: '/project/daily-heart-rate.jpg', alt: 'Heart rate through the day against the calendar', caption: 'Heart rate against the calendar' },
  { src: '/project/weekly-report.jpg', alt: 'A weekly report with four links, the best and hardest day and a suggestion', caption: 'The weekly report' },
  { src: '/project/weekly-patterns.jpg', alt: 'Recurring patterns ranked by their effect on sleep', caption: 'Recurring patterns, ranked by effect' },
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
      <section className="site-section" aria-labelledby="how">
        <h2 id="how">How it comes together</h2>
        <div className="site-flow">
          <ul className="site-flow-sources" aria-label="Data sources">
            {SOURCES.map((src) => (
              <li key={src.title} className="site-flow-source" style={{ height: SOURCE_H }}>
                <span className="site-flow-icon"><Icon name={src.icon} size={18} /></span>
                <span className="site-flow-copy">
                  <span className="site-flow-title">
                    <strong>{src.title}</strong>
                    {src.brands ? (
                      <span className="site-brands">
                        {src.brands.map((b) => (
                          <span key={b.key} className="site-brand" role="img" aria-label={b.name} title={b.name}
                            style={{ backgroundColor: b.color, maskImage: `url(/brands/${b.key}.svg)`, WebkitMaskImage: `url(/brands/${b.key}.svg)` }} />
                        ))}
                      </span>
                    ) : null}
                  </span>
                  <span className="small muted">{src.text}</span>
                </span>
              </li>
            ))}
          </ul>
          <svg className="site-flow-links" width="72" height={SOURCES_H} viewBox={`0 0 72 ${SOURCES_H}`} aria-hidden="true">
            {SOURCES.map((src, i) => {
              const y = i * (SOURCE_H + SOURCE_GAP) + SOURCE_H / 2;
              return <path key={src.title} d={`M0 ${y} C36 ${y}, 36 ${SOURCES_H / 2}, 72 ${SOURCES_H / 2}`} />;
            })}
          </svg>
          <div className="site-flow-step">
            <span className="site-flow-icon"><Icon name="lab" size={18} /></span>
            <strong>Statistical analysis</strong>
            <span className="small muted">
              Compares the days with and without each meeting, habit and show in your own history, and keeps only the
              links that hold up.
            </span>
          </div>
          <span className="site-flow-arrow" aria-hidden="true" />
          <div className="site-flow-step">
            <span className="site-flow-icon"><Icon name="brain" size={18} /></span>
            <strong>AI</strong>
            <span className="small muted">
              Picks the links worth telling and writes them in plain words, citing the numbers behind each one.
            </span>
          </div>
          <span className="site-flow-arrow" aria-hidden="true" />
          <div className="site-flow-step site-flow-out">
            <span className="site-flow-icon"><Icon name="sparkles" size={18} /></span>
            <strong>Insights</strong>
            <span className="small muted">Your daily and weekly reports:</span>
            <ul className="site-flow-insights">
              {INSIGHTS.map((t) => <li key={t}>{t}</li>)}
            </ul>
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
        <p className="tiny muted">Screenshots from the demo version.</p>
      </section>
    </>
  );
}
