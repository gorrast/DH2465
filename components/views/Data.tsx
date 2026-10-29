"use client";
/* Data & privacy: what is connected, what is read, persona/seed, import, delete (SPEC §9.4). */
import Link from "next/link";
import { api } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Icon } from "../ui/Icon";
import { busy, confirmModal, toast } from "../ui/overlays";
import { useApp } from "../shell/AppContext";
import { ViewHead, useLoad } from "./common";

const DEMO = "demo: regenerated, never stored";
const SYNCED = "your account, until you delete it";

const CLASSES = [
  [
    "Calendar events",
    "title, start, end, venue and description as written in the event; guests' names, emails and replies",
    "to know what your day looked like",
    DEMO,
  ],
  [
    "Location visits",
    "place type and name, start, end",
    "to check whether booked events happened",
    DEMO,
  ],
  [
    "Sleep",
    "bedtime, stages, interruptions, wake time",
    "to compute and explain the sleep score",
    DEMO,
  ],
  [
    "Heart rate",
    "one sample per minute",
    "to see how your body responded during and after events",
    DEMO,
  ],
  [
    "Recovery markers",
    "overnight HRV, resting heart rate, respiratory rate, wrist temperature, blood oxygen",
    "to compare each night with your own baseline",
    DEMO,
  ],
  [
    "Steps",
    "one total per day",
    "to see how active each day was",
    SYNCED,
  ],
  [
    "Screen time",
    "which apps were open and when, screen unlocks (Android app)",
    "to see how evening screen use relates to your sleep",
    SYNCED,
  ],
  [
    "Media history",
    "titles, artists or channels and times from the Spotify, Netflix, YouTube, Steam and Last.fm imports you add",
    "to see how evening listening, watching and gaming relate to your sleep",
    SYNCED,
  ],
  [
    "Check-ins",
    "cups of coffee and units of alcohol you log",
    "to account for what the calendar cannot see",
    SYNCED,
  ],
  [
    "Your answers",
    "yes/no to reality checks, accepted suggestions",
    "to correct the calendar and improve your patterns",
    SYNCED,
  ],
];

function Conn({
  icon,
  title,
  status,
  note,
}: {
  icon: string;
  title: string;
  status: string;
  note: string;
}) {
  return (
    <div className="card v-data-conn">
      <div className="row between">
        <span className="row">
          <span className="v-data-icon">
            <Icon name={icon} size={18} />
          </span>
          <strong>{title}</strong>
        </span>
        <span
          className={
            "badge " +
            (status.startsWith("Demo") ? "badge-accent" : "badge-good")
          }
        >
          {status}
        </span>
      </div>
      <p className="small secondary">{note}</p>
    </div>
  );
}

export function DataView() {
  const { meta, refreshMeta, setHistoryDays, go } = useApp();
  const facts = useLoad(() => api.get("/api/validation").catch(() => null), []);
  const isDemo = meta.source === "demo";
  const hidden = facts.data && facts.data.available ? facts.data.hidden : null;

  const deleteAll = async () => {
    const ok = await confirmModal({
      title: "Delete all data?",
      body: "This permanently removes everything stored in your account: synced sleep, steps and screen time, your calendar, media imports, check-ins, reports, answers and connections. The default demo is regenerated.",
      confirmLabel: "Delete and regenerate",
      danger: true,
    });
    if (!ok) return;
    busy({
      title: "Deleting and regenerating",
      steps: [
        "Removing your data",
        "Booking a fresh calendar",
        "Simulating heart rate and sleep",
        "Fitting the model",
      ],
    });
    try {
      await api.post("/api/reset");
      const m = await refreshMeta();
      setHistoryDays(null);
      busy(null);
      toast("All data deleted. Fresh demo ready.", { kind: "success" });
      go("/daily/" + m.today);
    } catch (e: any) {
      busy(null);
      toast(e.message, { kind: "error" });
    }
  };

  return (
    <>
      <ViewHead
        eyebrow="Data and Privacy"
        title="What StressLess reads, and why"
      />
      <div className="v-data stack" data-tour="privacy">
        <div className="grid grid-3">
          <Conn
            icon="calendar"
            title="Calendar"
            status={isDemo ? "Demo data" : "Connected"}
            note={
              isDemo
                ? "Ten weeks of a simulated calendar. In the product: Google Calendar, read-only, plus one write per accepted suggestion."
                : "Read from your Google Calendar."
            }
          />
          <Conn
            icon="watch"
            title="Watch"
            status={isDemo ? "Demo data" : "Synced"}
            note={
              isDemo
                ? "Simulated smartwatch: heart rate, sleep stages, HRV, resting heart rate, wrist temperature. In the product: Health Connect, synced by the StressLess Android app."
                : "Sleep and steps from Health Connect, synced by the StressLess Android app. Any watch that writes to Health Connect works."
            }
          />
          <Conn
            icon="map"
            title="Maps"
            status={isDemo ? "Demo data" : "Not collected"}
            note={
              isDemo
                ? "Simulated Google Maps timeline, used only to confirm booked events."
                : "Your location is not collected; places only appear in the demo."
            }
          />
        </div>
        <div className="card">
          <div className="card-title">
            <h3>Data classes</h3>
          </div>
          <table className="data">
            <thead>
              <tr>
                {["What", "Fields", "Why", "Retention"].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CLASSES.map((r) => (
                <tr key={r[0]}>
                  {r.map((c, i) => (
                    <td key={i}>{c}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="grid grid-2">
          <div className="card">
            <div className="card-title">
              <h3>Bring your own data</h3>
            </div>
            <p className="small secondary">
              Connect Your Data is the home for imports and optional sync.
              Import Spotify listening history, Netflix viewing CSVs, YouTube
              watch history, or a Steam library JSON. Steam and Last.fm sync are
              available when configured.
            </p>
            <p className="small secondary">
              Health, calendar and location exports cannot currently be uploaded
              through the web app. Each supported source includes its own setup
              instructions and file requirements.
            </p>
            <Link className="btn btn-primary" href="/connect">
              <Icon name="upload" size={16} />
              Connect Your Data
            </Link>
          </div>
          <div className="stack">
            <div className="card">
              <div className="card-title">
                <h3>This dataset</h3>
              </div>
              <div className="row">
                <span className="chip">
                  {(meta.n_nights || 0) + " nights with watch data"}
                </span>
                {hidden ? (
                  <span className="chip">
                    {(hidden.unworn_nights || []).length +
                      " unworn nights, " +
                      (hidden.unworn_social_nights || 0) +
                      " after social evenings"}
                  </span>
                ) : null}
                <span className="chip">
                  {"generated " +
                    (meta.generated_at ? fmt.hm(meta.generated_at) : "–")}
                </span>
              </div>
              {hidden ? (
                <p className="tiny muted" style={{ marginTop: "8px" }}>
                  Missing nights are not random: forgetting to charge happens
                  more after late evenings, which is exactly what real data
                  does.
                </p>
              ) : null}
            </div>
            <div className="card">
              <div className="card-title">
                <h3>Delete everything</h3>
              </div>
              <p className="small secondary">
                Removes everything stored in your account, including synced
                and imported data and your connections, then regenerates the
                default demo.
              </p>
              <button
                className="btn btn-danger"
                type="button"
                onClick={deleteAll}
              >
                <Icon name="trash" size={16} />
                Delete all data
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
