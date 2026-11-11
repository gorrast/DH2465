"use client";
/* Social: groups of friends who compare a few chosen metrics, this week and over a 4-week season, with team goals
   and opt-in challenges (backend: server/social.py). Only the metrics a group chose are shared. Visual language
   follows the Daily and Weekly tabs: a centered hero with a glow, sliding range toggles, gradient stat cards. */
import { useRef, useState, type CSSProperties } from "react";
import { motion, useReducedMotion } from "motion/react";
import { api } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useApp } from "../shell/AppContext";
import { Icon } from "../ui/Icon";
import { RevealHeading } from "../ui/Motion";
import { SectionNavigation } from "../ui/SectionNavigation";
import { toast } from "../ui/overlays";
import { ErrorCard, Skeleton, useLoad } from "./common";
import {
  WeeklyMotionContext,
  WeeklyNumber,
  WeeklyReveal,
} from "./WeeklyMotion";

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
  metrics: Record<
    string,
    { label: string; unit: string; better: "up" | "down" }
  >;
  groups: Group[];
  challenges: Challenge[];
}

const METRIC_ICON: Record<string, string> = {
  sleep_improved: "sparkles",
  sleep_score: "bed",
  bedtime: "moon",
  focus: "focus",
  screen: "screen",
  evenings: "lock",
  steps: "run",
  recovery: "heart",
};
const GROUP_ICON: Record<string, string> = {
  team: "users",
  focus: "focus",
  padel: "run",
};
const groupIcon = (g: Group) =>
  GROUP_ICON[Object.keys(GROUP_ICON).find((k) => g.id.includes(k)) || ""] ||
  "users";
const CHALLENGE_ICON: Record<string, string> = {
  "phone-down": "screen",
  "two-hours": "focus",
  "lights-out": "moon",
};

const initials = (name: string) =>
  name
    .split(" ")
    .map((p) => p[0])
    .join("");
const ordinal = (n: number) =>
  n +
  (n % 10 === 1 && n !== 11
    ? "st"
    : n % 10 === 2 && n !== 12
      ? "nd"
      : n % 10 === 3 && n !== 13
        ? "rd"
        : "th");

/** First name, plus the surname's initial when two people share it (Hugo Wigh and Hugo Ankarcrona). */
const firstName = (name: string, everyone: string[]) => {
  const [first, last] = name.split(" ");
  return everyone.some((n) => n !== name && n.split(" ")[0] === first) && last
    ? first + " " + last[0] + "."
    : first;
};

/** One steady colour per person, so a friend looks the same in every group; you are always the brand coral. */
const HUES = [262, 168, 205, 32, 128, 300];
function Avatar({
  name,
  me,
  size = 34,
}: {
  name: string;
  me: string;
  size?: number;
}) {
  const hash = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const style = {
    "--avatar-hue": HUES[hash % HUES.length],
    width: size,
    height: size,
    fontSize: Math.round(size * 0.36),
  } as CSSProperties;
  return (
    <span
      className={"social-avatar" + (name === me ? " is-me" : "")}
      style={style}
      aria-hidden="true"
    >
      {initials(name)}
    </span>
  );
}

/** A metric's value as people say it. */
function show(metric: string, v: number): string {
  const sign = (x: number, d = 1) =>
    (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d);
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
function VsUsual({
  metric,
  row,
  better,
}: {
  metric: string;
  row: Row;
  better: "up" | "down";
}) {
  if (row.usual === null) return null;
  const diff = row.value - row.usual;
  const step = metric === "steps" ? 100 : 1;
  if (Math.abs(diff) < step / 2)
    return <span className="social-usual">as usual</span>;
  const good = diff > 0 === (better === "up");
  const size =
    metric === "steps"
      ? (Math.round(Math.abs(diff) / 100) * 100).toLocaleString("sv-SE")
      : metric === "focus" || metric === "screen" || metric === "bedtime"
        ? Math.round(Math.abs(diff)) + " min"
        : String(Math.round(Math.abs(diff)));
  return (
    <span className={"social-usual " + (good ? "is-good" : "is-bad")}>
      <Icon name={diff > 0 ? "arrow-up" : "arrow-down"} size={12} />
      {size} vs usual
    </span>
  );
}

/** A sliding pill toggle, the same control as the Weekly tab's week range. */
function Toggle<T extends string>({
  options,
  value,
  onChange,
  label,
  layoutId,
  paused,
}: {
  options: { value: T; label: React.ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  layoutId: string;
  paused: boolean;
}) {
  return (
    <div className="weekly-range social-toggle" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
        >
          {value === o.value ? (
            <motion.span
              className="weekly-range-indicator"
              layoutId={layoutId}
              transition={
                paused
                  ? { duration: 0 }
                  : { type: "spring", stiffness: 400, damping: 32 }
              }
            />
          ) : null}
          <span>{o.label}</span>
        </button>
      ))}
    </div>
  );
}

function Leaderboard({
  board,
  social,
  period,
  delay,
}: {
  board: Board;
  social: Social;
  period: string;
  delay: number;
}) {
  const m = social.metrics[board.metric];
  const values = board.rows.map((r) => r.value);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  // bar length: how close to the leader each person is, so the board reads at a glance
  const reach = (v: number) => {
    if (hi === lo) return 1;
    const t = (v - lo) / (hi - lo);
    return 0.12 + 0.88 * (m.better === "up" ? t : 1 - t);
  };
  return (
    <WeeklyReveal className="social-board" delay={delay}>
      <section aria-label={m.label}>
        <header>
          <span className="social-board-icon">
            <Icon name={METRIC_ICON[board.metric] || "dot"} size={18} />
          </span>
          <span className="social-board-period">
            {period}
            <br />
            {m.unit}
          </span>
        </header>
        <h3>{m.label}</h3>
        <ol>
          {board.rows.map((r) => (
            <li
              key={r.name}
              className={r.name === social.me ? "is-me" : undefined}
              style={{ "--reach": reach(r.value) } as CSSProperties}
            >
              <span className={"social-rank rank-" + r.rank}>{r.rank}</span>
              <Avatar name={r.name} me={social.me} />
              <span className="social-name">
                <span>{r.name === social.me ? "You" : r.name}</span>
                <VsUsual metric={board.metric} row={r} better={m.better} />
              </span>
              <strong className="social-value">
                {show(board.metric, r.value)}
              </strong>
              <span className="social-reach" aria-hidden="true" />
            </li>
          ))}
        </ol>
      </section>
    </WeeklyReveal>
  );
}

/** The team goal as a ring, like the sleep score on the Daily tab. */
function GoalRing({ goal }: { goal: Group["goal"] }) {
  const share = Math.max(0, Math.min(1, goal.progress / goal.target));
  const reached = share >= 1;
  const readout =
    goal.metric === "steps"
      ? Math.round(goal.progress / 1000) + "k"
      : goal.metric === "sleep_score"
        ? goal.progress.toFixed(1)
        : String(Math.round(goal.progress));
  const of =
    goal.metric === "steps"
      ? "of " + Math.round(goal.target / 1000) + "k steps"
      : goal.metric === "sleep_score"
        ? "average, aiming for " + goal.target
        : "of " + goal.target;
  return (
    <div className="social-goal-ring">
      <svg
        viewBox="0 0 160 160"
        role="img"
        aria-label={`${goal.label}: ${readout} ${of}`}
      >
        <defs>
          <linearGradient id="social-goal-gradient" x1="0" y1="1" x2="1" y2="0">
            <stop stopColor="var(--interactive)" />
            <stop offset="1" stopColor="var(--recovery)" />
          </linearGradient>
        </defs>
        <circle
          cx="80"
          cy="80"
          r="66"
          fill="none"
          stroke="var(--card-3)"
          strokeWidth="9"
        />
        <motion.circle
          cx="80"
          cy="80"
          r="66"
          pathLength="100"
          fill="none"
          stroke="url(#social-goal-gradient)"
          strokeWidth="9"
          strokeLinecap="round"
          transform="rotate(-90 80 80)"
          initial={{ strokeDasharray: "0 100" }}
          whileInView={{ strokeDasharray: `${share * 100} 100` }}
          viewport={{ once: true }}
          transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }}
        />
        <text x="80" y="82" textAnchor="middle" className="social-goal-value">
          {readout}
        </text>
        <text x="80" y="104" textAnchor="middle" className="social-goal-of">
          {reached ? "reached!" : Math.round(share * 100) + "%"}
        </text>
      </svg>
      <p className="small muted">{of}</p>
    </div>
  );
}

/** Season points as a podium: second, first, third, then everyone else in a quiet list. */
function Podium({
  standings,
  social,
}: {
  standings: Group["standings"];
  social: Social;
}) {
  const top = [standings[1], standings[0], standings[2]].filter(Boolean);
  const rest = standings.slice(3);
  return (
    <>
      <div className="social-podium">
        {top.map((s) => {
          const place = standings.indexOf(s) + 1;
          return (
            <div
              key={s.name}
              className={
                "social-step place-" +
                place +
                (s.name === social.me ? " is-me" : "")
              }
            >
              <Avatar
                name={s.name}
                me={social.me}
                size={place === 1 ? 46 : 38}
              />
              <span className="social-step-name">
                {s.name === social.me
                  ? "You"
                  : firstName(
                      s.name,
                      standings.map((x) => x.name),
                    )}
              </span>
              <div className="social-step-block">
                <strong>{place}</strong>
                <span>
                  <WeeklyNumber value={s.points} /> pts
                </span>
              </div>
            </div>
          );
        })}
      </div>
      {rest.length ? (
        <ol className="social-rest" start={4}>
          {rest.map((s, i) => (
            <li
              key={s.name}
              className={s.name === social.me ? "is-me" : undefined}
            >
              <span className="social-rank">{i + 4}</span>
              <span className="social-name">
                {s.name === social.me ? "You" : s.name}
              </span>
              <span>{s.points} pts</span>
            </li>
          ))}
        </ol>
      ) : null}
    </>
  );
}

function GroupView({
  group,
  social,
  season,
}: {
  group: Group;
  social: Social;
  season: boolean;
}) {
  const boards = season ? group.season : group.week;
  const place = group.standings.findIndex((s) => s.name === social.me) + 1;
  const myPoints =
    group.standings.find((s) => s.name === social.me)?.points ?? 0;
  const podiums = boards.filter(
    (b) => (b.rows.find((r) => r.name === social.me)?.rank ?? 99) <= 3,
  ).length;
  const period = season
    ? fmt.day(social.season.start) + " – " + fmt.day(social.season.end)
    : fmt.day(social.week.start) + " – " + fmt.day(social.week.end);
  return (
    <div className="social-group">
      <div className="social-summary">
        <WeeklyReveal className="social-card social-standing">
          <section aria-label="Your standing">
            <span className="eyebrow">Your standing · season</span>
            <p className="social-big">
              {ordinal(place)}
              <small> of {group.members.length}</small>
            </p>
            <p className="secondary">
              <strong>{myPoints} points</strong> over the last 4 weeks. Top
              three on{" "}
              <strong>
                {podiums} of {boards.length}
              </strong>{" "}
              boards {season ? "over the season" : "this week"}.
            </p>
            <div
              className="social-members"
              aria-label={group.members.length + " members"}
            >
              {group.members.map((n) => (
                <span key={n} title={n === social.me ? "You" : n}>
                  <Avatar name={n} me={social.me} size={30} />
                </span>
              ))}
            </div>
          </section>
        </WeeklyReveal>
        <WeeklyReveal className="social-card social-goal" delay={0.08}>
          <section aria-label="Team goal">
            <span className="eyebrow">Team goal this week</span>
            <h3>{group.goal.label}</h3>
            <GoalRing goal={group.goal} />
          </section>
        </WeeklyReveal>
        <WeeklyReveal className="social-card social-standings" delay={0.14}>
          <section aria-label="Season standings">
            <span className="eyebrow">Season standings · last 4 weeks</span>
            <Podium standings={group.standings} social={social} />
            <p className="tiny muted">
              3, 2 and 1 points for the top three on each weekly board.
            </p>
          </section>
        </WeeklyReveal>
      </div>
      <header className="weekly-section-heading">
        <div>
          <span className="eyebrow">
            {season ? "The longer view" : "This week's boards"}
          </span>
          <h2>{season ? "Over the last 4 weeks" : "Who's ahead this week"}</h2>
        </div>
        <p>
          Bars show how close each person is to the lead.
          <br />
          Arrows compare everyone with their own usual.
        </p>
      </header>
      <div className="social-boards">
        {boards.map((b, i) => (
          <Leaderboard
            key={b.metric + season}
            board={b}
            social={social}
            period={period}
            delay={i * 0.07}
          />
        ))}
      </div>
    </div>
  );
}

function ChallengeCard({
  c,
  social,
  delay,
}: {
  c: Challenge;
  social: Social;
  delay: number;
}) {
  const { meta } = useApp();
  const join = () =>
    toast(
      meta.read_only
        ? "This would have signed you up for the challenge, but this demo is read-only."
        : "Joining challenges is coming soon.",
      { kind: "info", duration: 6000 },
    );
  const mine = c.progress.find((p) => p.name === social.me);
  return (
    <WeeklyReveal
      className={
        "social-card social-challenge" + (c.joined ? " is-joined" : "")
      }
      delay={delay}
    >
      <section aria-label={c.title}>
        <header>
          <span className="social-board-icon">
            <Icon name={CHALLENGE_ICON[c.id] || "flag"} size={18} />
          </span>
          {c.joined ? (
            <span className="social-joined">
              <Icon name="check" size={14} /> Joined
            </span>
          ) : (
            <button
              className="btn btn-sm btn-primary"
              type="button"
              onClick={join}
            >
              Join
            </button>
          )}
        </header>
        <h3>{c.title}</h3>
        <p className="small secondary">{c.text}</p>
        {c.joined ? (
          <>
            {mine ? (
              <p className="social-challenge-mine">
                <strong>{mine.days}</strong> of {c.target} nights so far
              </p>
            ) : null}
            <ul className="social-progress">
              {c.progress.map((p) => (
                <li
                  key={p.name}
                  className={p.name === social.me ? "is-me" : undefined}
                >
                  <Avatar name={p.name} me={social.me} size={26} />
                  <span className="social-name">
                    {p.name === social.me
                      ? "You"
                      : firstName(
                          p.name,
                          c.progress.map((x) => x.name).concat(social.me),
                        )}
                  </span>
                  <span
                    className="social-dots"
                    aria-label={p.days + " of 7 days"}
                  >
                    {Array.from({ length: 7 }, (_, i) => (
                      <span key={i} className={i < p.days ? "on" : undefined} />
                    ))}
                  </span>
                  <span
                    className={
                      "small " + (p.days >= c.target ? "is-good" : "muted")
                    }
                  >
                    {p.days >= c.target ? (
                      <Icon name="check" size={14} />
                    ) : (
                      p.days + "/" + c.target
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <div className="social-challenge-foot">
            <span className="social-stack">
              {c.progress.slice(0, 4).map((p) => (
                <Avatar key={p.name} name={p.name} me={social.me} size={26} />
              ))}
            </span>
            <span className="tiny muted">
              {c.people} friends are taking part
            </span>
          </div>
        )}
      </section>
    </WeeklyReveal>
  );
}

export function SocialView() {
  const load = useLoad(() => api.get<Social>("/api/social"), []);
  const paused = !!useReducedMotion();
  const pageRef = useRef<HTMLDivElement>(null);
  const [period, setPeriod] = useState<"week" | "season">("week");
  const [groupId, setGroupId] = useState<string | null>(null);
  const social = load.data;
  const group =
    social?.groups.find((g) => g.id === groupId) || social?.groups[0];
  const everyone = social
    ? [...new Set(social.groups.flatMap((g) => g.members))]
    : [];
  return (
    <WeeklyMotionContext.Provider value={paused}>
      <div
        ref={pageRef}
        className={
          "v-social weekly-dashboard" + (paused ? " is-motion-paused" : "")
        }
      >
        <header className="social-hero" data-page-section="Your groups" data-tour="social">
          <div className="social-hero-glow" aria-hidden="true" />
          {social ? (
            <div className="social-hero-faces" aria-hidden="true">
              {everyone.map((n, i) => (
                <span key={n} style={{ "--i": i } as CSSProperties}>
                  <Avatar name={n} me={social.me} size={44} />
                </span>
              ))}
            </div>
          ) : null}
          <span className="eyebrow">Social Tab</span>
          <RevealHeading as="h1" paused={paused} duration={1.7}>
            Better together.
          </RevealHeading>
          <p>
            Friendly competition on what helps you sleep, with only the numbers
            your groups chose to share.
          </p>
          {social ? (
            <Toggle
              label="Period"
              layoutId="social-period"
              paused={paused}
              value={period}
              onChange={setPeriod}
              options={[
                { value: "week", label: "This week" },
                { value: "season", label: "Last 4 weeks" },
              ]}
            />
          ) : null}
          {social ? (
            <span className="small muted">
              {period === "week"
                ? fmt.day(social.week.start) + " – " + fmt.day(social.week.end)
                : fmt.day(social.season.start) +
                  " – " +
                  fmt.day(social.season.end)}
            </span>
          ) : null}
        </header>
        {load.loading ? (
          <Skeleton height={460} />
        ) : load.error || !social || !group ? (
          <ErrorCard
            view="Social"
            error={load.error || new Error("Could not load your groups.")}
            onRetry={load.reload}
          />
        ) : (
          <>
            <section data-page-section="Leaderboards" aria-label="Your groups">
              <nav className="social-groups" aria-label="Choose a group">
                {social.groups.map((g) => (
                  <button
                    key={g.id}
                    type="button"
                    className={
                      "social-group-tab" + (g.id === group.id ? " active" : "")
                    }
                    aria-pressed={g.id === group.id}
                    onClick={() => setGroupId(g.id)}
                  >
                    {g.id === group.id ? (
                      <motion.span
                        className="social-group-indicator"
                        layoutId="social-group"
                        transition={
                          paused
                            ? { duration: 0 }
                            : { type: "spring", stiffness: 380, damping: 32 }
                        }
                      />
                    ) : null}
                    <span className="social-group-icon">
                      <Icon name={groupIcon(g)} size={18} />
                    </span>
                    <span className="social-group-text">
                      <strong>{g.name}</strong>
                      <span>{g.about}</span>
                    </span>
                    <span className="social-stack">
                      {g.members.slice(0, 4).map((n) => (
                        <Avatar key={n} name={n} me={social.me} size={24} />
                      ))}
                      {g.members.length > 4 ? (
                        <span className="social-more">
                          +{g.members.length - 4}
                        </span>
                      ) : null}
                    </span>
                  </button>
                ))}
              </nav>
              <GroupView
                key={group.id}
                group={group}
                social={social}
                season={period === "season"}
              />
            </section>
            <section
              data-page-section="Challenges"
              className="social-challenges"
              aria-labelledby="challenges-title"
            >
              <header className="weekly-section-heading">
                <div>
                  <span className="eyebrow">Opt in, week by week</span>
                  <h2 id="challenges-title">Challenges</h2>
                </div>
                <p>
                  Pick a goal for the week.
                  <br />
                  Friends see whether you made it, nothing more.
                </p>
              </header>
              <div className="social-challenge-grid">
                {social.challenges.map((c, i) => (
                  <ChallengeCard
                    key={c.id}
                    c={c}
                    social={social}
                    delay={i * 0.07}
                  />
                ))}
              </div>
            </section>
            <p className="social-privacy">
              <Icon name="lock" size={16} />
              <span>
                A group only sees the metrics it chose and each person&rsquo;s
                rank and change against their own usual, never the health data
                behind them.
              </span>
            </p>
          </>
        )}
        <SectionNavigation root={pageRef} paused={paused} />
      </div>
    </WeeklyMotionContext.Provider>
  );
}
