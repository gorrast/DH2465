"use client";
/* Social: groups of friends who compare a few chosen metrics, this week and over a 4-week season, with team goals
   and opt-in challenges (backend: server/social.py). Only the metrics a group chose are shared. */
import { useState } from "react";
import { api } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useApp } from "../shell/AppContext";
import { Icon } from "../ui/Icon";
import { toast } from "../ui/overlays";
import { ErrorCard, Skeleton, ViewHead, useLoad } from "./common";

interface Row {
  name: string;
  value: number;
  usual: number | null;
  rank: number;
}
interface Board {
  metric: string;
  rows: Row[];
}
interface Group {
  id: string;
  name: string;
  about: string;
  members: string[];
  metrics: string[];
  week: Board[];
  season: Board[];
  standings: { name: string; points: number }[];
  goal: { label: string; target: number; progress: number; metric: string };
}
interface Challenge {
  id: string;
  title: string;
  text: string;
  target: number;
  joined: boolean;
  people: number;
  progress: { name: string; days: number }[];
}
interface Social {
  me: string;
  week: { start: string; end: string };
  season: { start: string; end: string };
  metrics: Record<string, { label: string; unit: string; better: "up" | "down" }>;
  groups: Group[];
  challenges: Challenge[];
}

const initials = (name: string) =>
  name
    .split(" ")
    .map((p) => p[0])
    .join("");

/** A metric's value as people say it. */
function show(metric: string, v: number): string {
  const sign = (x: number, d = 1) => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d);
  switch (metric) {
    case "sleep_improved":
      return sign(v) + " pts";
    case "recovery":
      return sign(v) + " %";
    case "sleep_score":
      return String(Math.round(v));
    case "bedtime":
      return "±" + Math.round(v) + " min";
    case "focus":
    case "screen":
      return fmt.minutes(v);
    case "evenings":
      return Math.round(v) + " of 7";
    case "steps":
      return Math.round(v).toLocaleString("sv-SE");
    default:
      return String(v);
  }
}

/** The change against the person's own usual, coloured by whether it is the better way. */
function VsUsual({ metric, row, better }: { metric: string; row: Row; better: "up" | "down" }) {
  if (row.usual === null) return null;
  const diff = row.value - row.usual;
  const step = metric === "steps" ? 100 : metric === "evenings" ? 1 : 1;
  if (Math.abs(diff) < step / 2) return <span className="social-usual">as usual</span>;
  const good = (diff > 0) === (better === "up");
  const size =
    metric === "steps"
      ? Math.round(Math.abs(diff) / 100) * 100
      : metric === "focus" || metric === "screen" || metric === "bedtime"
        ? Math.round(Math.abs(diff)) + " min"
        : Math.round(Math.abs(diff));
  return (
    <span className={"social-usual " + (good ? "is-good" : "is-bad")}>
      {diff > 0 ? "▲" : "▼"} {typeof size === "number" ? size.toLocaleString("sv-SE") : size} vs usual
    </span>
  );
}

function Leaderboard({ board, social }: { board: Board; social: Social }) {
  const m = social.metrics[board.metric];
  return (
    <section className="card social-board" aria-label={m.label}>
      <header>
        <h3>{m.label}</h3>
        <span className="tiny muted">{m.unit}</span>
      </header>
      <ol>
        {board.rows.map((r) => (
          <li key={r.name} className={r.name === social.me ? "is-me" : undefined}>
            <span className={"social-rank rank-" + r.rank}>{r.rank}</span>
            <span className="social-avatar" aria-hidden="true">
              {initials(r.name)}
            </span>
            <span className="social-name">
              {r.name === social.me ? "You" : r.name}
              <VsUsual metric={board.metric} row={r} better={m.better} />
            </span>
            <strong className="social-value">{show(board.metric, r.value)}</strong>
          </li>
        ))}
      </ol>
    </section>
  );
}

function GroupView({ group, social, season }: { group: Group; social: Social; season: boolean }) {
  const goal = group.goal;
  const share = Math.min(1, goal.progress / goal.target);
  return (
    <div className="social-group">
      <header className="social-group-head">
        <div>
          <h2>{group.name}</h2>
          <p className="secondary">{group.about}</p>
        </div>
        <div className="social-members" aria-label={group.members.length + " members"}>
          {group.members.map((n) => (
            <span key={n} className="social-avatar" title={n === social.me ? "You" : n}>
              {initials(n)}
            </span>
          ))}
        </div>
      </header>
      <div className="social-boards">
        {(season ? group.season : group.week).map((b) => (
          <Leaderboard key={b.metric} board={b} social={social} />
        ))}
      </div>
      <div className="social-extras">
        <section className="card social-goal" aria-label="Team goal">
          <div className="eyebrow">Team goal this week</div>
          <h3>{goal.label}</h3>
          <div className="social-bar" role="progressbar" aria-valuemin={0} aria-valuemax={goal.target} aria-valuenow={goal.progress}>
            <span style={{ width: share * 100 + "%" }} />
          </div>
          <p className="small muted">
            {goal.metric === "steps"
              ? Math.round(goal.progress).toLocaleString("sv-SE") + " of " + goal.target.toLocaleString("sv-SE")
              : goal.metric === "sleep_score"
                ? "Average " + goal.progress.toFixed(1) + " of " + goal.target
                : Math.round(goal.progress) + " of " + goal.target}
            {share >= 1 ? " · reached together" : ""}
          </p>
        </section>
        <section className="card social-standings" aria-label="Season standings">
          <div className="eyebrow">Season standings · last 4 weeks</div>
          <ol>
            {group.standings.map((s, i) => (
              <li key={s.name} className={s.name === social.me ? "is-me" : undefined}>
                <span className={"social-rank rank-" + (i + 1)}>{i + 1}</span>
                <span className="social-name">{s.name === social.me ? "You" : s.name}</span>
                <strong>{s.points} pts</strong>
              </li>
            ))}
          </ol>
          <p className="tiny muted">3, 2 and 1 points for the top three on each weekly board.</p>
        </section>
      </div>
    </div>
  );
}

function ChallengeCard({ c, social }: { c: Challenge; social: Social }) {
  const { meta } = useApp();
  const join = () =>
    toast(
      meta.read_only
        ? "This would have signed you up for the challenge, but this demo is read-only."
        : "Joining challenges is coming soon.",
      { kind: "info", duration: 6000 },
    );
  return (
    <section className={"card social-challenge" + (c.joined ? " is-joined" : "")} aria-label={c.title}>
      <header>
        <div>
          <h3>{c.title}</h3>
          <p className="small secondary">{c.text}</p>
        </div>
        {c.joined ? (
          <span className="badge badge-high">Joined</span>
        ) : (
          <button className="btn btn-sm" type="button" onClick={join}>
            Join
          </button>
        )}
      </header>
      {c.joined ? (
        <ul className="social-progress">
          {c.progress.map((p) => (
            <li key={p.name} className={p.name === social.me ? "is-me" : undefined}>
              <span className="social-name">{p.name === social.me ? "You" : p.name}</span>
              <span className="social-dots" aria-label={p.days + " of 7 days"}>
                {Array.from({ length: 7 }, (_, i) => (
                  <span key={i} className={i < p.days ? "on" : undefined} />
                ))}
              </span>
              <span className={"small " + (p.days >= c.target ? "is-good" : "muted")}>
                {p.days >= c.target ? "done" : p.days + "/" + c.target}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="tiny muted">{c.people} friends are taking part.</p>
      )}
    </section>
  );
}

export function SocialView() {
  const load = useLoad(() => api.get<Social>("/api/social"), []);
  const [season, setSeason] = useState(false);
  const [groupId, setGroupId] = useState<string | null>(null);
  const social = load.data;
  const group = social?.groups.find((g) => g.id === groupId) || social?.groups[0];
  return (
    <>
      <ViewHead eyebrow="Social" title="Better together">
        {social ? (
          <div className="segmented" role="tablist" aria-label="Period">
            <button type="button" role="tab" aria-selected={!season} className={!season ? "active" : ""} onClick={() => setSeason(false)}>
              This week · {fmt.day(social.week.start)} – {fmt.day(social.week.end)}
            </button>
            <button type="button" role="tab" aria-selected={season} className={season ? "active" : ""} onClick={() => setSeason(true)}>
              Last 4 weeks
            </button>
          </div>
        ) : null}
      </ViewHead>
      {load.loading ? (
        <Skeleton height={420} />
      ) : load.error || !social || !group ? (
        <ErrorCard view="Social" error={load.error || new Error("Could not load your groups.")} onRetry={load.reload} />
      ) : (
        <div className="v-social stack">
          <nav className="social-tabs" aria-label="Your groups">
            {social.groups.map((g) => (
              <button
                key={g.id}
                type="button"
                className={"social-tab" + (g.id === group.id ? " active" : "")}
                aria-pressed={g.id === group.id}
                onClick={() => setGroupId(g.id)}
              >
                <Icon name="users" size={16} />
                {g.name}
                <span className="tiny muted">{g.members.length}</span>
              </button>
            ))}
          </nav>
          <GroupView group={group} social={social} season={season} />
          <section className="social-challenges" aria-labelledby="challenges-title">
            <header className="social-section-head">
              <h2 id="challenges-title">Challenges</h2>
              <p className="secondary">Opt in to a goal for the week. Your friends see whether you made it, nothing more.</p>
            </header>
            <div className="social-challenge-grid">
              {social.challenges.map((c) => (
                <ChallengeCard key={c.id} c={c} social={social} />
              ))}
            </div>
          </section>
          <p className="tiny muted social-privacy">
            <Icon name="lock" size={14} /> A group only sees the metrics it chose and each person&rsquo;s rank and change
            against their own usual, never the health data behind them.
          </p>
        </div>
      )}
    </>
  );
}
