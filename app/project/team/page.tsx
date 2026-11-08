import type { Metadata } from 'next';

export const metadata: Metadata = { title: 'The team' };

const TEAM = ['Hugo Wigh', 'Nima Tehranchi', 'Knut Ovesjö', 'Marcus Pramborg', 'Gustaf Salenius', 'Hugo Ankarcrona'];

export default function TeamPage() {
  return (
    <section className="site-intro">
      <span className="eyebrow">The team</span>
      <h1>The people behind StressLess</h1>
      <p className="site-lede">StressLess is our project in DH2465 at KTH Royal Institute of Technology.</p>
      <ul className="site-team" aria-label="Team members">
        {TEAM.map((name) => (
          <li key={name} className="site-member">
            <span className="site-member-avatar" aria-hidden="true">
              {name.split(' ').map((part) => part[0]).join('')}
            </span>
            <span className="site-member-name">{name}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
