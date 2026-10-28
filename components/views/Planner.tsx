"use client";
/* Planner: what-if on today's (or a coming day's) calendar, with a predicted delta and likely range (SPEC §9.4). */
import { useEffect, useRef, useState } from "react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { ActionButton, calmTransition } from "../ui/Motion";
import { api } from "@/lib/api";
import { dates, fmt, minuteOf } from "@/lib/format";
import { eventIcon } from "@/lib/icons";
import { palette } from "@/lib/palette";
import { Icon } from "../ui/Icon";
import { ScoreChange, ScoreText } from "../ui/ScoreChange";
import { toast } from "../ui/overlays";
import { useApp } from "../shell/AppContext";
import { DateNav, Skeleton, ViewHead, useLoad } from "./common";

interface Mod {
  op: string;
  event_id: string;
  hour?: number;
  hours?: number;
}
const FACTOR_LABEL: Record<string, string> = {
  meetings_over_3: "meeting load",
  b2b_over_2: "back-to-back",
  late_meeting_hours: "late meeting",
  evening_social: "evening social",
  workout_morning: "morning workout",
  workout_late: "late workout",
  travel: "travel",
  early_start: "early start",
  protected_evening: "protected evening",
  is_weekend: "weekend",
};

export function PlannerView({ date: dateParam }: { date?: string }) {
  const { today } = useApp();
  const date = dateParam || today;
  const max = dates.addDays(today, 7);
  const load = useLoad(async () => {
    const day = await api.get("/api/day/" + date);
    let report = null;
    if (date === today) {
      try {
        report = await api.get("/api/report/" + today);
      } catch {
        report = null;
      }
    }
    return { day, report };
  }, [date, today]);
  return (
    <>
      <ViewHead
        eyebrow="Planner"
        title={date === today ? "Tonight" : fmt.dayLong(date)}
      >
        <DateNav
          label={fmt.day(date)}
          prevHref={"/planner/" + dates.addDays(date, -1)}
          nextHref={"/planner/" + dates.addDays(date, 1)}
          prevDisabled={date <= today}
          nextDisabled={date >= max}
        />
      </ViewHead>
      <div className="v-planner stack">
        {load.loading ? (
          <Skeleton height={220} />
        ) : load.error || !load.data ? (
          <div className="card empty">
            <h2>Nothing to plan here</h2>
            <p>{load.error?.message}</p>
          </div>
        ) : (
          <PlannerBody
            date={date}
            today={today}
            initialDay={load.data.day}
            initialReport={load.data.report}
          />
        )}
      </div>
    </>
  );
}

function PlannerBody({
  date,
  today,
  initialDay,
  initialReport,
}: {
  date: string;
  today: string;
  initialDay: any;
  initialReport: any;
}) {
  const reducedMotion = useReducedMotion();
  const [day, setDay] = useState(initialDay);
  const [report, setReport] = useState(initialReport);
  const [mods, setMods] = useState<Mod[]>([]);
  const [w, setW] = useState<any>(null); // the latest what-if result, with the number of changes it was computed for
  const seq = useRef(0);
  const [werr, setWerr] = useState<string | null>(null);
  const [dim, setDim] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [recomputeTick, setRecomputeTick] = useState(0);

  useEffect(() => {
    const id = ++seq.current;
    setDim(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        const res = await api.post("/api/whatif", { date, mods });
        if (id !== seq.current) return; // a newer request is in flight; its answer wins
        setW({ ...res, nMods: mods.length });
        setWerr(null);
      } catch (e: any) {
        if (id !== seq.current) return;
        setW(null);
        setWerr(e.message);
      }
      setDim(false);
    }, 250);
    return () => {
      ++seq.current;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [date, mods, recomputeTick]);

  const hourOf = (iso: string) => (minuteOf(iso, date) as number) / 60;
  const has = (id: string, op: string) =>
    mods.some((m) => m.event_id === id && m.op === op);
  const toggleMod = (id: string, op: string, extra?: Partial<Mod>) => {
    setMods((cur) =>
      cur.some((m) => m.event_id === id && m.op === op)
        ? cur.filter((m) => !(m.event_id === id && m.op === op))
        : [
            ...cur.filter((m) => m.event_id !== id),
            { op, event_id: id, ...(extra || {}) },
          ],
    );
  };
  const controlsFor = (ev: any) => {
    const ctl: React.ReactNode[] = [];
    const b = (label: string, op: string, extra?: Partial<Mod>) =>
      ctl.push(
        <button
          key={op}
          className={
            "btn btn-sm" + (has(ev.id, op) ? " active btn-primary" : "")
          }
          type="button"
          onClick={() => toggleMod(ev.id, op, extra)}
        >
          {label}
        </button>,
      );
    if (ev.type === "meeting") {
      if (hourOf(ev.end) > 18) b("End at 18:00", "end_at", { hour: 18 });
      b("−2 h", "shift", { hours: -2 });
      b("→ Protected", "to_protected");
    } else if (ev.type === "focus") {
      b("→ Protected", "to_protected");
    } else if (ev.type === "workout") {
      if (hourOf(ev.start) >= 10)
        b("Move to 07:00", "shift", { hours: 7 - hourOf(ev.start) });
    }
    b("Remove", "remove");
    return ctl;
  };
  const [proposed, setProposed] = useState(true);
  const evs = day.events
    .filter((e: any) => e.attended !== false)
    .slice()
    .sort((a: any, b: any) => (a.start < b.start ? -1 : 1));

  const acceptSuggestion = async (s: any) => {
    try {
      await api.post("/api/suggestions/" + today + "/" + s.id + "/accept");
      setDay(await api.get("/api/day/" + date));
      setReport(await api.get("/api/report/" + today));
      setRecomputeTick((t) => t + 1);
      toast("Added to your StressLess plan", { kind: "success" });
    } catch (err: any) {
      toast(err.message, { kind: "error" });
    }
  };

  const previewEvents = w && !dim && proposed ? w.events_after : day.events;
  return (
    <LayoutGroup>
      <div className="v-planner-grid">
        <div className="stack">
          <div
            className={"card v-planner-hero" + (dim ? " loading-dim" : "")}
            data-tour="prediction"
          >
            <div className="eyebrow">Predicted change for this night</div>
            <div className="v-planner-delta">
              <ScoreChange value={!w ? null : w.nMods ? w.delta : 0} digits={0}>
                {!w ? "–" : w.nMods ? fmt.signed(w.delta, 0) : "±0"}
              </ScoreChange>
            </div>
            <div className="small secondary">
              {werr ? (
                werr
              ) : !w ? (
                ""
              ) : w.nMods && w.delta_low !== null ? (
                <>
                  Likely <ScoreChange value={w.delta_low} digits={0} /> to{" "}
                  <ScoreChange value={w.delta_high} digits={0} /> points
                </>
              ) : (
                "Change the plan to see the effect"
              )}
            </div>
            {w ? (
              <PredictionRange
                baseline={w.baseline_pred}
                score={w.nMods ? w.modified_pred : w.baseline_pred}
                low={
                  w.nMods && w.delta_low != null
                    ? w.baseline_pred + w.delta_low
                    : null
                }
                high={
                  w.nMods && w.delta_high != null
                    ? w.baseline_pred + w.delta_high
                    : null
                }
              />
            ) : null}
            {werr ? (
              <button
                className="btn btn-sm"
                type="button"
                onClick={() => setRecomputeTick((tick) => tick + 1)}
              >
                Retry estimate
              </button>
            ) : null}
            <div className="v-planner-pred" role="status" aria-live="polite">
              {w ? (
                <>
                  <span className="muted small">Predicted sleep score </span>
                  <strong>{fmt.score(w.baseline_pred)}</strong>
                  {w.nMods ? (
                    <>
                      <span className="muted small"> → </span>
                      <strong>{fmt.score(w.modified_pred)}</strong>
                    </>
                  ) : null}
                  <span className="muted small">
                    {" · typical error ±" + fmt.num(w.rmse, 0)}
                  </span>
                </>
              ) : null}
            </div>
            <div className="row">
              {(w?.changed_factors || []).map((k: string) => (
                <span key={k} className="chip">
                  {FACTOR_LABEL[k] || k}
                </span>
              ))}
            </div>
            <div className="tiny muted">
              From your own within-person model. Ranges come from resampling
              your nights; correlation, not proof.
            </div>
          </div>
          <div className="stack">
            {report && report.suggestions.length ? (
              <>
                <h4>Suggestions for tonight</h4>
                {report.suggestions.map((s: any) => (
                  <motion.div
                    initial={reducedMotion ? false : { opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    layout="position"
                    transition={
                      reducedMotion ? { duration: 0 } : calmTransition
                    }
                    key={s.id}
                    className="card soft v-planner-sugg"
                  >
                    <div className="row between">
                      <strong>{s.title}</strong>
                      {s.gain_low !== null && s.gain_low !== undefined ? (
                        <span className="chip pts">
                          <ScoreChange value={s.gain_low} digits={0} /> to{" "}
                          <ScoreChange value={s.gain_high} digits={0} />
                        </span>
                      ) : null}
                    </div>
                    <p className="small secondary">
                      <ScoreText text={s.body} />
                    </p>
                    <div className="row">
                      {s.accepted ? (
                        <motion.span
                          initial={
                            reducedMotion ? false : { opacity: 0, y: 12 }
                          }
                          animate={{ opacity: 1, y: 0 }}
                          transition={
                            reducedMotion ? { duration: 0 } : calmTransition
                          }
                          className="row small v-planner-added"
                        >
                          <Icon name="check" size={14} />
                          Saved to plan
                        </motion.span>
                      ) : s.proposed_event ? (
                        <AcceptButton onAccept={() => acceptSuggestion(s)} />
                      ) : s.kind === "move_meeting" ? (
                        <button
                          className="btn btn-sm"
                          type="button"
                          onClick={() => {
                            const late = day.events
                              .filter(
                                (e: any) =>
                                  e.type === "meeting" && hourOf(e.end) >= 19.5,
                              )
                              .sort((a: any, b: any) =>
                                a.end < b.end ? 1 : -1,
                              )[0];
                            if (late)
                              toggleMod(late.id, "end_at", { hour: 18 });
                          }}
                        >
                          Try it
                        </button>
                      ) : null}
                    </div>
                  </motion.div>
                ))}
              </>
            ) : null}
          </div>
        </div>
        <div className="card">
          <div className="card-title">
            <h3>{"The plan for " + fmt.day(date)}</h3>
            <button
              className="btn btn-sm"
              type="button"
              disabled={!mods.length}
              onClick={() => setMods([])}
            >
              <Icon name="refresh" size={14} />
              Undo changes
            </button>
          </div>
          <div className="row between v-planner-preview-head">
            <span className="small secondary">Your day at a glance</span>
            <div className="segmented" aria-label="Compare plans">
              <button
                type="button"
                aria-pressed={!proposed}
                className={!proposed ? "active" : ""}
                onClick={() => setProposed(false)}
              >
                Current
              </button>
              <button
                type="button"
                aria-pressed={proposed}
                className={proposed ? "active" : ""}
                onClick={() => setProposed(true)}
              >
                Proposed
              </button>
            </div>
          </div>
          <PlanTimeline events={previewEvents || day.events} date={date} />
          <div className="stack" data-tour="events" aria-busy={dim}>
            {!evs.length ? (
              <p className="muted">An empty day. Add nothing and sleep well.</p>
            ) : (
              evs.map((ev: any) => (
                <motion.div
                  initial={reducedMotion ? false : { opacity: 0, y: 16 }}
                  animate={{ opacity: has(ev.id, "remove") ? 0.5 : 1, y: 0 }}
                  layout="position"
                  transition={reducedMotion ? { duration: 0 } : calmTransition}
                  key={ev.id}
                  className={
                    "v-planner-event" + (has(ev.id, "remove") ? " removed" : "")
                  }
                >
                  <span
                    className="v-planner-swatch"
                    style={{ background: palette.event(ev.type) }}
                  >
                    <Icon name={eventIcon(ev.type)} size={14} />
                  </span>
                  <div className="v-planner-event-body">
                    <div className="row between">
                      <span className="v-planner-title">
                        {ev.title}
                        {ev.source === "user" ? (
                          <span
                            className="badge badge-accent"
                            style={{ marginLeft: "8px" }}
                          >
                            added by you
                          </span>
                        ) : null}
                      </span>
                      <span className="tiny muted tabular">
                        {fmt.hm(ev.start) + "–" + fmt.hm(ev.end)}
                      </span>
                    </div>
                    <div className="row v-planner-controls">
                      {controlsFor(ev)}
                    </div>
                  </div>
                </motion.div>
              ))
            )}
          </div>
          <div className="tiny muted" style={{ marginTop: "10px" }}>
            Change a block and watch the prediction move. These changes preview
            your StressLess plan. Accept a suggestion to save its block;
            download its .ics file from Today to use it in another calendar.
          </div>
        </div>
      </div>
    </LayoutGroup>
  );
}

function AcceptButton({ onAccept }: { onAccept: () => Promise<void> }) {
  const [pending, setPending] = useState(false);
  return (
    <ActionButton
      className="btn btn-sm btn-primary"
      type="button"
      disabled={pending}
      onClick={async () => {
        setPending(true);
        await onAccept();
        setPending(false);
      }}
    >
      Save to plan
    </ActionButton>
  );
}

/** Separate rows keep overlapping events readable without a calendar dependency. */
function PlanTimeline({ events, date }: { events: any[]; date: string }) {
  const reducedMotion = useReducedMotion();
  const entries = events
    .filter((e) => e.attended !== false)
    .slice()
    .sort((a, b) => a.start.localeCompare(b.start));
  const start = Math.min(
    6 * 60,
    ...entries.map((e) => minuteOf(e.start, date) ?? 360),
  );
  const end = Math.max(
    24 * 60,
    ...entries.map((e) => minuteOf(e.end, date) ?? 1440),
  );
  const percent = (minute: number) => ((minute - start) / (end - start)) * 100;
  return (
    <div className="plan-timeline">
      <div className="plan-ticks" aria-hidden="true">
        {[6, 12, 18, 24].map((h) => (
          <span key={h} style={{ left: percent(h * 60) + "%" }}>
            {h === 24 ? "00:00" : h + ":00"}
          </span>
        ))}
      </div>
      {entries.map((ev) => {
        const a = minuteOf(ev.start, date) ?? start;
        const b = minuteOf(ev.end, date) ?? a;
        return (
          <motion.div
            initial={reducedMotion ? false : { opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            layout="position"
            transition={reducedMotion ? { duration: 0 } : calmTransition}
            className="plan-lane"
            key={ev.id}
          >
            <motion.span
              initial={false}
              transition={reducedMotion ? { duration: 0 } : calmTransition}
              className="plan-block"
              animate={{
                left: percent(a) + "%",
                width: Math.max(1, percent(b) - percent(a)) + "%",
              }}
              style={{ background: palette.event(ev.type) }}
            />
            <span className="plan-event-label">
              {ev.title}
              <span className="muted">
                {fmt.hm(ev.start)}–{fmt.hm(ev.end)}
              </span>
            </span>
          </motion.div>
        );
      })}
      {!entries.length ? (
        <p className="small secondary">Room to breathe. No events planned.</p>
      ) : null}
    </div>
  );
}

function PredictionRange({
  baseline,
  score,
  low,
  high,
}: {
  baseline: number;
  score: number;
  low: number | null;
  high: number | null;
}) {
  const clamp = (n: number) => Math.max(0, Math.min(100, n));
  return (
    <div
      className="prediction-range"
      role="img"
      aria-label={`Estimated sleep score ${fmt.score(score)}, current plan ${fmt.score(baseline)}${low !== null && high !== null ? ", likely change " + fmt.signed(low - baseline, 0) + " to " + fmt.signed(high - baseline, 0) + " points" : ""}`}
    >
      <div className="prediction-track">
        {low !== null && high !== null ? (
          <span
            className="prediction-band"
            style={{
              left: clamp(low) + "%",
              width: clamp(high) - clamp(low) + "%",
            }}
          />
        ) : null}
        <i
          className="prediction-baseline"
          style={{ left: clamp(baseline) + "%" }}
        />
        <i className="prediction-marker" style={{ left: clamp(score) + "%" }} />
      </div>
      <div className="row between tiny muted">
        <span>0 · estimated sleep score</span>
        <span>100</span>
      </div>
    </div>
  );
}
