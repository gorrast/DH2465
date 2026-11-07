import type { Metadata } from 'next';

export const metadata: Metadata = { title: 'The team' };

const TEAM = ['Hugo Wigh', 'Knut Ovesjö', 'Marcus Pramborg', 'Nima Tehranchi', 'Gustaf Salenius', 'Hugo Ankarcrona'];

export default function TeamPage() {
  return (
    <section className="site-intro">
      <span className="eyebrow">The team</span>
      <h1>The people behind StressLess</h1>
      <p className="site-lede">StressLess is our project in DH2465 at KTH Royal Institute of Technology.</p>
      <p className="site-byline">By {TEAM.slice(0, -1).join(', ')} and {TEAM[TEAM.length - 1]}.</p>
    </section>
  );
}
