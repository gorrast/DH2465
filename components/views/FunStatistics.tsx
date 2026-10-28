"use client";

import {
  createContext,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { gsap } from "gsap";
import { Flip } from "gsap/Flip";

gsap.registerPlugin(Flip);
import { getSupabase } from "@/lib/supabase/client";
import { Icon } from "../ui/Icon";
import { useLoad } from "./common";
import type { AppStatistics } from "./useAppStatistics";
import { WeeklyNumber, useWeeklyMotion } from "./WeeklyMotion";

type EventHeartRate = {
  event_id: string;
  event_title: string | null;
  starts_at: string;
  ends_at: string;
  gets_you_going_score: number;
  avg_bpm: number;
  min_bpm: number;
  max_bpm: number;
  hr_sample_count: number;
};
type SpotifyTrack = {
  song_title: string;
  artist_name: string;
  gets_you_going_score: number;
  avg_bpm: number;
  peak_bpm: number;
  bpm_above_resting: number;
  times_played: number;
};
type FlowCandidate = {
  event_title: string | null;
  event_category: string;
  starts_at: string;
  ends_at: string;
  avg_bpm: number;
  hr_variability_bpm: number;
  hr_sample_count: number;
  screen_minutes: number;
  app_sessions: number;
  unlocks_during_event: number;
};
type WrappedResult = {
  archetype: string;
  item_title: string;
  artist_name: string | null;
  primary_value: number | null;
  comparison_value: number | null;
  sample_count: number;
  plays_count: number;
  note: string;
};
type MeetingHangover = {
  event_id: string;
  event_title: string | null;
  starts_at: string;
  ends_at: string;
  attendee_count: number | null;
  post_meeting_hr_drift: number | null;
  night_resting_hr_delta: number | null;
  deep_sleep_delta_min: number | null;
  post_hr_sample_count: number;
};

async function rpc<T>(name: string): Promise<T[]> {
  const { data, error } = await getSupabase().rpc(name);
  if (error) throw new Error(error.message);
  return (data || []) as T[];
}
const number = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(Number(value))
    ? "—"
    : Number(value).toFixed(digits);
const signed = (value: number | null) =>
  value == null ? "—" : (Number(value) > 0 ? "+" : "") + number(value);
const eventTime = (start: string, end: string) => {
  const from = new Date(start),
    to = new Date(end);
  return (
    from.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " · " +
    from.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) +
    "–" +
    to.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );
};

type LoadState = { loading: boolean; error: Error | null; reload: () => void };
const StatisticFocus = createContext<{
  focused: number | null;
  toggle: (index: number) => void;
}>({ focused: null, toggle: () => {} });

function StatisticCard({
  title,
  icon,
  period,
  index,
  load,
  empty,
  children,
  note,
  summary,
}: {
  title: string;
  icon: string;
  period: string;
  index: number;
  load: LoadState;
  empty: boolean;
  children: ReactNode;
  note: string;
  summary?: { value: number | null; unit: string; label: string };
}) {
  const paused = useWeeklyMotion();
  const { focused, toggle } = useContext(StatisticFocus);
  const expanded = focused === index;
  const id = useId();
  const tooltip = useRef<HTMLSpanElement>(null);
  const tipAnimation = useRef<gsap.core.Timeline | null>(null);
  const [hintOpen, setHintOpen] = useState(false);
  useLayoutEffect(() => {
    const context = gsap.context(() => {
      gsap.set(tooltip.current, { autoAlpha: 0, y: 10, scale: 0.88 });
      tipAnimation.current = gsap
        .timeline({ paused: true })
        .to(tooltip.current, {
          autoAlpha: 1,
          y: 0,
          scale: 1,
          duration: paused ? 0 : 0.5,
          ease: "back.out(1.8)",
          easeReverse: "power3.in",
        });
    });
    return () => {
      context.revert();
      tipAnimation.current = null;
    };
  }, [paused]);
  useEffect(() => {
    const animation = tipAnimation.current;
    if (!animation) return;
    if (hintOpen && !expanded) animation.timeScale(1).play();
    else animation.timeScale(2).reverse();
  }, [hintOpen, expanded, paused]);
  return (
    <section
      className={"weekly-stat-card" + (expanded ? " is-focused" : "")}
      aria-label={title}
      aria-busy={load.loading}
      data-flip-id={"statistic-" + index}
    >
      <button
        className="weekly-stat-toggle"
        type="button"
        aria-expanded={expanded}
        aria-controls={id + "-detail"}
        aria-describedby={id + "-tip"}
        onClick={() => {
          setHintOpen(false);
          toggle(index);
        }}
        onPointerEnter={(event) => {
          if (event.pointerType === "mouse") setHintOpen(true);
        }}
        onPointerLeave={() => setHintOpen(false)}
        onFocus={() => setHintOpen(true)}
        onBlur={() => setHintOpen(false)}
      >
        <span className="weekly-stat-icon">
          <Icon name={icon} size={20} />
        </span>
        <span className="weekly-stat-title">{title}</span>
        <span className="weekly-stat-preview">
          <span className="weekly-stat-preview-value">
            {load.loading ? (
              "…"
            ) : summary?.value == null ? (
              "—"
            ) : (
              <WeeklyNumber value={Number(summary.value)} digits={1} />
            )}
            <small>{summary?.unit || ""}</small>
          </span>
          <span className="weekly-stat-preview-label">
            {load.loading
              ? "Loading your insight"
              : load.error
                ? "Unavailable · open to retry"
                : empty
                  ? "Waiting for data"
                  : summary?.label}
          </span>
        </span>
        <span className="weekly-stat-action">
          {expanded ? "Close insight" : "Explore"}
          <Icon name={expanded ? "x" : "chevron-right"} size={14} />
        </span>
        <span
          className="weekly-stat-tooltip"
          id={id + "-tip"}
          role="tooltip"
          ref={tooltip}
        >
          Click to bring this insight into focus
        </span>
      </button>
      <div
        className="weekly-stat-expanded"
        id={id + "-detail"}
        hidden={!expanded}
      >
        <span className="weekly-period">{period}</span>
        <div className="weekly-stat-body">
          {load.loading ? (
            <div className="weekly-stat-loading" role="status">
              <div className="skeleton" />
              <div className="skeleton" />
              <span>Finding your numbers…</span>
            </div>
          ) : load.error ? (
            <div className="weekly-stat-empty" role="alert">
              <p>Couldn’t load this insight.</p>
              <p className="tiny">{load.error.message}</p>
              <button className="btn btn-sm" onClick={load.reload}>
                Try again
              </button>
            </div>
          ) : empty ? (
            <div className="weekly-stat-empty">
              <Icon name={icon} size={26} />
              <p>Waiting for a little more data.</p>
              <span>
                Results will appear here when matching records are available.
              </span>
            </div>
          ) : (
            children
          )}
        </div>
        <p className="weekly-stat-note">{note}</p>
      </div>
    </section>
  );
}

function StatRow({
  title,
  subtitle,
  value,
  unit,
  detail,
  rank,
}: {
  title: string;
  subtitle?: string;
  value: number | null;
  unit: string;
  detail: string;
  rank?: number;
}) {
  return (
    <li className="weekly-stat-row">
      <div className="weekly-stat-row-head">
        <div className="weekly-stat-row-title">
          {rank != null ? (
            <span className="weekly-rank">{String(rank).padStart(2, "0")}</span>
          ) : null}
          <strong>{title}</strong>
        </div>
        <span className="weekly-stat-value">
          {value == null ? (
            "—"
          ) : (
            <WeeklyNumber value={Number(value)} digits={1} />
          )}
          <small>{unit}</small>
        </span>
      </div>
      {subtitle ? <p className="weekly-stat-subtitle">{subtitle}</p> : null}
      <p className="weekly-stat-detail">{detail}</p>
    </li>
  );
}

export function FunStatisticsView({
  embedded = false,
  appStatistics,
}: {
  embedded?: boolean;
  appStatistics: AppStatistics;
}) {
  const paused = useWeeklyMotion();
  const [focused, setFocused] = useState<number | null>(null);
  const grid = useRef<HTMLDivElement>(null);
  const snapshot = useRef<ReturnType<typeof Flip.getState> | null>(null);
  const flipAnimation = useRef<gsap.core.Timeline | null>(null);
  const toggle = (index: number) => {
    const cards = grid.current?.querySelectorAll(".weekly-stat-card");
    if (cards) {
      Flip.killFlipsOf(cards, true);
      snapshot.current = paused ? null : Flip.getState(cards);
    }
    setFocused((current) => (current === index ? null : index));
  };
  useLayoutEffect(() => {
    if (focused != null && grid.current) grid.current.scrollLeft = 0;
    if (paused) {
      if (grid.current)
        Flip.killFlipsOf(
          grid.current.querySelectorAll(".weekly-stat-card"),
          true,
        );
      snapshot.current = null;
      return;
    }
    if (!snapshot.current) return;
    flipAnimation.current = Flip.from(snapshot.current, {
      duration: 0.75,
      ease: "power3.inOut",
      scale: true,
      prune: true,
    });
    snapshot.current = null;
  }, [focused, paused]);
  useEffect(
    () => () => {
      flipAnimation.current?.progress(1).kill();
    },
    [],
  );
  // Each insight loads independently: a slow or unavailable source never blocks the others.
  const { apps, appHR } = appStatistics;
  const eventHR = useLoad(
    () => rpc<EventHeartRate>("top_calendar_events_by_heart_rate"),
    [],
  );
  const spotify = useLoad(
    () => rpc<SpotifyTrack>("top_spotify_tracks_by_gets_you_going"),
    [],
  );
  const flow = useLoad(
    async () =>
      Array.from(
        new Map(
          (await rpc<FlowCandidate>("flow_state_candidates")).map((block) => [
            `${block.event_category}:${block.event_title}:${block.starts_at}:${block.ends_at}`,
            block,
          ]),
        ).values(),
      ),
    [],
  );
  const wrapped = useLoad(async () => {
    const [archetypes, tracks] = await Promise.all([
      rpc<WrappedResult>("cardiac_wrapped"),
      rpc<SpotifyTrack>("top_spotify_track_gets_you_going_this_week"),
    ]);
    return { archetypes, track: tracks[0] };
  }, []);
  const meetings = useLoad(
    () => rpc<MeetingHangover>("meeting_hangover_index"),
    [],
  );
  return (
    <section
      data-page-section={embedded ? "Your week in numbers" : undefined}
      className="weekly-numbers"
      aria-labelledby="weekly-numbers-title"
    >
      <header className="weekly-section-heading">
        <div>
          <span className="eyebrow">The little things add up</span>
          {embedded ? (
            <h2 id="weekly-numbers-title">Your week in numbers</h2>
          ) : (
            <h1 id="weekly-numbers-title">Your week in numbers</h1>
          )}
        </div>
        <p>
          Music, moments, and the way you move.
          <br />
          Seven insights. Click a card to explore.
        </p>
      </header>
      <p className="weekly-stat-instruction">
        <Icon name="info" size={14} />
        Select any card to bring it into focus. Press Escape to return.
      </p>
      <StatisticFocus.Provider value={{ focused, toggle }}>
        <div
          ref={grid}
          className={
            "weekly-stat-grid" + (focused != null ? " has-focused" : "")
          }
          onKeyDown={(event) => {
            if (event.key === "Escape" && focused != null) {
              event.preventDefault();
              event.stopPropagation();
              const button = grid.current?.querySelectorAll<HTMLButtonElement>(
                ".weekly-stat-toggle",
              )[focused];
              toggle(focused);
              button?.focus();
            }
          }}
        >
          <StatisticCard
            title="Your most-used apps"
            icon="screen"
            period="Last 7 days"
            index={0}
            summary={{
              value: apps.data?.[0]?.minutes ?? null,
              unit: "min",
              label: apps.data?.[0]?.appName || "Most-used app",
            }}
            load={apps}
            empty={!apps.data?.length}
            note="Your five most-used apps, ranked by recorded screen time."
          >
            <ol>
              {apps.data?.map((app, i) => (
                <StatRow
                  key={app.packageName}
                  rank={i + 1}
                  title={app.appName}
                  value={app.minutes}
                  unit="min"
                  detail={`${number(app.minutes / 60)} hours of recorded use`}
                />
              ))}
            </ol>
          </StatisticCard>
          <StatisticCard
            title="Apps that get you going"
            icon="pulse"
            period="All recorded sessions"
            index={1}
            summary={{
              value: appHR.data?.[0]?.gets_you_going_score ?? null,
              unit: "/100",
              label: appHR.data?.[0]?.app_name || "Top app response",
            }}
            load={appHR}
            empty={!appHR.data?.length}
            note="Arousal score out of 100. Higher means a stronger measured response, not better health."
          >
            <ol>
              {appHR.data?.map((app, i) => (
                <StatRow
                  key={app.package_name}
                  rank={i + 1}
                  title={app.app_name}
                  value={app.gets_you_going_score}
                  unit="/100"
                  detail={`${number(app.avg_bpm)} bpm avg · ${number(app.peak_bpm)} peak · ${number(app.total_minutes)} min · ${app.sessions_measured} sessions · ${number(app.peak_session_score)}/100 best session`}
                />
              ))}
            </ol>
          </StatisticCard>
          <StatisticCard
            title="Your liveliest events"
            icon="calendar"
            period="All recorded events"
            index={2}
            summary={{
              value: eventHR.data?.[0]?.gets_you_going_score ?? null,
              unit: "/100",
              label: eventHR.data?.[0]?.event_title || "Top event response",
            }}
            load={eventHR}
            empty={!eventHR.data?.length}
            note="Calendar events ranked by measured arousal. At least two heart-rate samples per event."
          >
            <ol>
              {eventHR.data?.map((event, i) => (
                <StatRow
                  key={event.event_id}
                  rank={i + 1}
                  title={event.event_title || "Untitled event"}
                  subtitle={eventTime(event.starts_at, event.ends_at)}
                  value={event.gets_you_going_score}
                  unit="/100"
                  detail={`${number(event.avg_bpm)} bpm avg · ${number(event.min_bpm)}–${number(event.max_bpm)} range · ${event.hr_sample_count} samples`}
                />
              ))}
            </ol>
          </StatisticCard>
          <StatisticCard
            title="Songs that move you"
            icon="music"
            period="All recorded plays"
            index={3}
            summary={{
              value: spotify.data?.[0]?.gets_you_going_score ?? null,
              unit: "/100",
              label: spotify.data?.[0]?.song_title || "Top song response",
            }}
            load={spotify}
            empty={!spotify.data?.length}
            note="Spotify tracks ranked by arousal during recorded playback."
          >
            <ol>
              {spotify.data?.map((track, i) => (
                <StatRow
                  key={track.song_title + track.artist_name}
                  rank={i + 1}
                  title={track.song_title}
                  subtitle={track.artist_name}
                  value={track.gets_you_going_score}
                  unit="/100"
                  detail={`${number(track.avg_bpm)} bpm avg · ${number(track.peak_bpm)} peak · ${signed(track.bpm_above_resting)} above resting · ${track.times_played} plays`}
                />
              ))}
            </ol>
          </StatisticCard>
          <StatisticCard
            title="Find your flow"
            icon="focus"
            period="Last 30 days"
            index={4}
            summary={{
              value: flow.data?.[0]?.avg_bpm ?? null,
              unit: "bpm",
              label: flow.data?.[0]?.event_title || "Your calmest moment",
            }}
            load={flow}
            empty={!flow.data?.length}
            note="Calmer, steadier heart rate and less recorded screen use. Associations, not proof of cause."
          >
            <ol>
              {flow.data?.map((block, i) => (
                <StatRow
                  key={`${block.event_category}:${block.event_title}:${block.starts_at}:${block.ends_at}`}
                  rank={i + 1}
                  title={block.event_title || "Untitled event"}
                  subtitle={`${block.event_category} · ${eventTime(block.starts_at, block.ends_at)}`}
                  value={block.avg_bpm}
                  unit="bpm"
                  detail={`${number(block.hr_variability_bpm)} bpm variation · ${number(block.screen_minutes)} screen min · ${block.app_sessions} app sessions · ${block.unlocks_during_event} unlocks · ${block.hr_sample_count} HR samples`}
                />
              ))}
            </ol>
          </StatisticCard>
          <StatisticCard
            title="Your Cardiac Wrapped"
            icon="sparkles"
            period="Last 7 days"
            index={5}
            summary={{
              value:
                wrapped.data?.track?.gets_you_going_score ??
                wrapped.data?.archetypes[0]?.primary_value ??
                null,
              unit: wrapped.data?.track ? "/100" : "bpm",
              label:
                wrapped.data?.track?.song_title ||
                wrapped.data?.archetypes[0]?.archetype ||
                "Your music response",
            }}
            load={wrapped}
            empty={!wrapped.data?.archetypes.length && !wrapped.data?.track}
            note="Stationary = ≤2,000 recorded daily steps. Calmer is compared with non-Spotify heart rate, not verified silence."
          >
            <ul>
              {wrapped.data?.track ? (
                <StatRow
                  title={wrapped.data.track.song_title}
                  subtitle={`Gets You Going · ${wrapped.data.track.artist_name}`}
                  value={wrapped.data.track.gets_you_going_score}
                  unit="/100"
                  detail={`${number(wrapped.data.track.avg_bpm)} bpm avg · ${number(wrapped.data.track.peak_bpm)} peak · ${signed(wrapped.data.track.bpm_above_resting)} above resting · ${wrapped.data.track.times_played} plays`}
                />
              ) : null}
              {wrapped.data?.archetypes.map((result) => (
                <StatRow
                  key={result.archetype}
                  title={
                    (result.archetype === "True Calmer"
                      ? result.artist_name
                      : result.item_title) || result.archetype
                  }
                  subtitle={[
                    result.archetype,
                    result.archetype !== "True Calmer" && result.artist_name,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  value={result.primary_value}
                  unit={
                    result.archetype === "True Calmer"
                      ? "bpm below"
                      : result.archetype === "Cardiac Anthem"
                        ? "bpm surge"
                        : "bpm variation"
                  }
                  detail={`${result.archetype === "Cardiac Anthem" ? "Peak HR" : result.archetype === "True Calmer" ? "Artist-play average" : "Average HR"} ${number(result.comparison_value)} bpm · ${result.sample_count} samples · ${result.plays_count} plays. ${result.note}`}
                />
              ))}
            </ul>
          </StatisticCard>
          <StatisticCard
            title="Meeting Hangover Index"
            icon="briefcase"
            period="Last 30 days"
            index={6}
            summary={{
              value: meetings.data?.[0]?.post_meeting_hr_drift ?? null,
              unit: "bpm drift",
              label: meetings.data?.[0]?.event_title || "After your meetings",
            }}
            load={meetings}
            empty={!meetings.data?.length}
            note="Heart-rate drift in the three hours after each meeting vs the hour before. Sleep changes use your 30-day baseline."
          >
            <ol>
              {meetings.data?.map((meeting, i) => (
                <StatRow
                  key={meeting.event_id}
                  rank={i + 1}
                  title={meeting.event_title || "Untitled meeting"}
                  subtitle={eventTime(meeting.starts_at, meeting.ends_at)}
                  value={meeting.post_meeting_hr_drift}
                  unit="bpm drift"
                  detail={`Resting HR ${signed(meeting.night_resting_hr_delta)} bpm · deep sleep ${signed(meeting.deep_sleep_delta_min)} min · ${meeting.attendee_count ?? 0} attendees · ${meeting.post_hr_sample_count} post-meeting samples`}
                />
              ))}
            </ol>
          </StatisticCard>
        </div>
      </StatisticFocus.Provider>
    </section>
  );
}
