"use client";
/* Habits view: every recurring pattern ranked by effect, with intervals and the adjusted effect. */
import { ScoreChange } from "../ui/ScoreChange";
import { useState } from "react";
import { api } from "@/lib/api";
import { fmt } from "@/lib/format";
import { DataTable } from "../charts/basic";
import { EffectBars } from "../charts/analysis";
import { useApp } from "../shell/AppContext";
import { ErrorCard, Skeleton, useLoad } from "./common";

const GROUPS = [
  "all",
  "good",
  "bad",
  "calendar",
  "workout",
  "social",
  "travel",
  "routine",
];
let filterMemo = "all"; // the filter survives navigating away and back, as before

export function HabitsView() {
  const { historyDays: hd } = useApp();
  const [filter, setFilterState] = useState(filterMemo);
  const [showTable, setShowTable] = useState(false);
  const setFilter = (g: string) => {
    filterMemo = g;
    setFilterState(g);
  };
  const load = useLoad(
    () => api.get("/api/habits" + (hd ? "?history_days=" + hd : "")),
    [hd],
  );
  const data = load.data;
  const items = data
    ? data.habits.filter(
        (h: any) =>
          filter === "all" || h.direction === filter || h.group === filter,
      )
    : [];
  const effectItems = [...items].sort(
    (a: any, b: any) => (a.effect ?? Infinity) - (b.effect ?? Infinity),
  );
  return (
    <>
      <div className="v-habits stack">
        {load.loading ? (
          <Skeleton height={200} />
        ) : load.error || !data ? (
          <ErrorCard error={load.error!} onRetry={load.reload} view="habits" />
        ) : (
          <>
            <div className="row between">
              <div className="row v-habits-filters">
                {GROUPS.map((g) => (
                  <button
                    key={g}
                    className={
                      "btn btn-sm " + (filter === g ? "btn-primary" : "")
                    }
                    type="button"
                    onClick={() => setFilter(g)}
                  >
                    {g === "all" ? "All" : g[0].toUpperCase() + g.slice(1)}
                  </button>
                ))}
              </div>
              <button
                className="btn btn-sm"
                type="button"
                onClick={() => setShowTable(!showTable)}
              >
                {showTable ? "Hide table" : "Table view"}
              </button>
            </div>
            <div className="card" data-tour="effects">
              <div className="card-title">
                <h3>Effect on sleep score</h3>
                <span className="tiny muted">
                  {"model: " +
                    data.model.n_nights +
                    " nights · out-of-sample R² " +
                    fmt.num((data.model.r2_loo || 0) * 100, 0) +
                    " %"}
                </span>
              </div>
              <p className="small secondary">
                Ordered by sleep-score impact: most negative to most positive.
              </p>
              <EffectBars
                items={effectItems.map((h: any) => ({
                  label: h.title,
                  effect: h.effect,
                  lo: h.ci_low,
                  hi: h.ci_high,
                  confidence: h.confidence,
                  direction: h.direction,
                  adjusted: h.adjusted_effect,
                  n: h.n_with,
                }))}
                rowH={36}
              />
              <div hidden={!showTable}>
                {showTable ? (
                  <DataTable
                    columns={[
                      { key: "title", label: "Pattern" },
                      { key: "n", label: "Nights with / without" },
                      { key: "effect", label: "Effect (pts)", num: true },
                      { key: "ci", label: "95 % interval" },
                      { key: "adjusted", label: "Adjusted", num: true },
                      { key: "confidence", label: "Confidence" },
                    ]}
                    rows={effectItems.map((h: any) => ({
                      title: h.title,
                      n: h.n_with + " / " + h.n_without,
                      effect: <ScoreChange value={h.effect} />,
                      ci:
                        h.ci_low == null ? (
                          "–"
                        ) : (
                          <>
                            <ScoreChange value={h.ci_low} /> to{" "}
                            <ScoreChange value={h.ci_high} />
                          </>
                        ),
                      adjusted: <ScoreChange value={h.adjusted_effect} />,
                      confidence: h.confidence,
                    }))}
                  />
                ) : null}
              </div>
            </div>

          </>
        )}
      </div>
    </>
  );
}
