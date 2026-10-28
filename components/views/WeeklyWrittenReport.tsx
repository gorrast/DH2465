"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { dates, fmt } from "@/lib/format";
import { Icon } from "../ui/Icon";
import { ReportCard, type Overview, type Report } from "./Home";
import { ReportInsights } from "./ReportInsights";
import { Skeleton, useLoad } from "./common";

/** The backend reports on the last complete Monday–Sunday week. */
export function WeeklyWrittenReport({
  end,
  paused,
}: {
  end: string;
  paused: boolean;
}) {
  const period = dates.addDays(end, -((dates.parse(end).getDay() + 6) % 7) - 7);
  const overview = useLoad(() => api.get<Overview>("/api/reports"), []);
  const stored = useLoad(
    () =>
      api.get<{ report: Report | null; status: string }>(
        "/api/reports/weekly/" + period,
      ),
    [period],
  );
  const [generated, setGenerated] = useState<Report | null>(null);
  const [agree, setAgree] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [scrollVersion, setScrollVersion] = useState(0);
  const busy = useRef(false);
  const section = useRef<HTMLElement>(null);
  const scrolled = useRef(0);
  const o = overview.data;
  const report = generated || stored.data?.report;
  const current = o?.weekly.period === period;
  const pending =
    !report &&
    (stored.data?.status === "pending" ||
      (current && o?.weekly.status === "pending"));
  const consentRequired = !!o?.ai && !o.consented;

  useEffect(() => {
    if (!report || scrolled.current === scrollVersion) return;
    scrolled.current = scrollVersion;
    const frame = requestAnimationFrame(() => {
      section.current?.scrollIntoView({
        behavior:
          paused ||
          window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "instant"
            : "smooth",
        block: "start",
      });
      section.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [report, scrollVersion, paused]);

  async function generate(regenerate = false) {
    if (
      busy.current ||
      !o ||
      !current ||
      (consentRequired && !agree) ||
      (regenerate && !o.dev)
    )
      return;
    busy.current = true;
    setWorking(true);
    setError("");
    try {
      if (!o.consented) await api.post("/api/reports/consent");
      const result = await api.post<{ report: Report }>(
        "/api/reports/weekly/" +
          period +
          (regenerate ? "?regenerate=true" : ""),
      );
      setGenerated(result.report);
      overview.setData({
        ...o,
        consented: true,
        weekly: { ...o.weekly, status: "ready" },
      });
      setScrollVersion((version) => version + 1);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Could not generate your weekly report. Please try again.",
      );
    } finally {
      busy.current = false;
      setWorking(false);
    }
  }

  const consentField = consentRequired ? (
    <label className="v-home-consent small">
      <input
        type="checkbox"
        checked={agree}
        disabled={working}
        onChange={(event) => setAgree(event.target.checked)}
      />
      <span>
        I agree that a summary of my data (numbers, short labels and the artists
        and shows you play; no people’s names, calendar titles or places) is
        sent to Anthropic’s Claude to write my reports.
      </span>
    </label>
  ) : null;

  return (
    <section
      data-page-section="Weekly report"
      ref={section}
      className="weekly-written-report written-report"
      tabIndex={-1}
      aria-labelledby="weekly-written-title"
      aria-busy={working}
    >
      <header className="weekly-section-heading">
        <div>
          <span className="eyebrow">Connect the dots</span>
          <h2 id="weekly-written-title">Your weekly report</h2>
        </div>
        <p>
          {fmt.day(period)} — {fmt.day(dates.addDays(period, 6))}
        </p>
      </header>
      {report ? (
        <>
          <ReportCard
            report={report}
            insights={<ReportInsights report={report} paused={paused} />}
          />
          {o?.dev && current ? consentField : null}
          {o?.dev && current ? (
            <button
              className="btn btn-sm"
              type="button"
              disabled={working || (consentRequired && !agree)}
              onClick={() => generate(true)}
            >
              {working ? "Writing your report…" : "Regenerate (dev)"}
            </button>
          ) : null}
        </>
      ) : stored.loading || overview.loading ? (
        <Skeleton height={260} />
      ) : stored.error || overview.error ? (
        <div className="card stack" role="alert">
          <p>
            Could not load your weekly report:{" "}
            {(stored.error || overview.error)?.message}
          </p>
          <button
            className="btn"
            type="button"
            onClick={() => {
              stored.reload();
              overview.reload();
            }}
          >
            Try again
          </button>
        </div>
      ) : (
        <div className="card weekly-report-empty">
          <h3>The story behind your week.</h3>
          <p className="secondary">
            Bring last week’s sleep and activities together: the patterns that
            stood out, your best and hardest days, and a suggestion for next
            week.
          </p>
          {pending ? (
            <p role="status">
              Your weekly report is being written.{" "}
              <button
                className="btn btn-sm"
                type="button"
                onClick={() => {
                  stored.reload();
                  overview.reload();
                }}
              >
                Check again
              </button>
            </p>
          ) : current ? (
            <>
              {consentField}
              <button
                className="btn btn-primary"
                type="button"
                disabled={working || (consentRequired && !agree)}
                onClick={() => generate()}
              >
                <Icon name={working ? "refresh" : "brain"} size={16} />
                {working
                  ? "Writing your report…"
                  : "Generate last week’s report"}
              </button>
            </>
          ) : (
            <p className="secondary">
              No saved report for this week. New reports can only be generated
              for the last complete week.
            </p>
          )}
        </div>
      )}
      {working ? (
        <p className="small secondary" role="status">
          Writing your weekly report. This can take up to a minute.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="v-home-error">
          {error}
        </p>
      ) : null}
    </section>
  );
}
