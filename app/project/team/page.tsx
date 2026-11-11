import type { Metadata } from "next";
import type { CSSProperties } from "react";
import Image from "next/image";
import { existsSync } from "node:fs";
import path from "node:path";

export const metadata: Metadata = { title: "The team" };

const TEAM = [
  {
    name: "Hugo Wigh",
    title: "Chief Executive Officer",
    photo: "hugo-wigh-removebg-preview.png",
    backdrop: "#0085ff",
    backdropEnd: "#0465c9",
  },
  {
    name: "Nima Tehranchi",
    title: "Chief of Dentistry",
    photo: "nima-dentist-nobg.png",
    backdrop: "#ffcc00",
    backdropEnd: "#ff9f00",
  },
  {
    name: "Knut Ovesjö",
    title: "Chief Technology Officer",
    photo: "knut-ovesjo-removebg-preview.png",
    backdrop: "#94efc4",
    backdropEnd: "#53cfa1",
  },
  {
    name: "Marcus Pramborg",
    title: "Chief Information Security Officer",
    photo: "marcus-pramborg-removebg-preview.png",
    backdrop: "#c4b0ff",
    backdropEnd: "#9474ef",
  },
  {
    name: "Gustaf Salenius",
    title: "Chief Creative Officer",
    photo: "gustaf-salenius-removebg-preview.png",
    backdrop: "#ffb2cb",
    backdropEnd: "#ef7da3",
  },
  {
    name: "Hugo Ankarcrona",
    title: "Chief Data Officer",
    photo: "hugo-ankarcrona-removebg-preview.png",
    backdrop: "#a9dff5",
    backdropEnd: "#64badf",
  },
];

export default function TeamPage() {
  return (
    <section className="site-intro">
      <span className="eyebrow">The team</span>
      <h1>The people behind StressLess</h1>
      <p className="site-lede">
        StressLess is our project in DH2465 at KTH Royal Institute of
        Technology.
      </p>
      <ul className="site-team" aria-label="Team members">
        {TEAM.map(({ name, title, photo, backdrop, backdropEnd }) => {
          const hasPhoto = existsSync(
            path.join(process.cwd(), "public", "team", photo),
          );
          return (
            <li
              key={name}
              className="site-member"
              data-portrait={photo}
              style={{
                "--portrait-background": backdrop,
                "--portrait-background-end": backdropEnd,
              } as CSSProperties}
            >
              <span className="site-member-avatar" aria-hidden="true">
                {hasPhoto ? (
                  <Image
                    src={`/team/${photo}`}
                    alt=""
                    width={640}
                    height={640}
                    sizes="(max-width: 600px) 85vw, (max-width: 900px) 42vw, 30vw"
                  />
                ) : (
                  name
                    .split(" ")
                    .map((part) => part[0])
                    .join("")
                )}
              </span>
              <div className="site-member-caption">
                <span className="site-member-name">{name}</span>
                <span className="site-member-title">{title}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
