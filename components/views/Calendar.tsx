"use client";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Icon } from "../ui/Icon";
import { ViewHead } from "./common";

type Step = "start" | "providers" | "google" | "connected";
type Connection = { status?: string; email?: string; last_synced_at?: string };

type Action = "status" | "authorize" | "sync" | "disconnect";

/** The Google Calendar routes of the FastAPI backend (backend/stressless/server/calendar.py). */
function calendarRequest(action: Action): Promise<any> {
  const base = "/api/calendar/google";
  return action === "status" ? api.get(base) : api.post(base + "/" + action);
}

function connectedCalendar(payload: any): Connection | null {
  const connections = Array.isArray(payload?.connections)
    ? payload.connections
    : [];
  return (
    connections.find(
      (connection: Connection) => connection.status === "connected",
    ) || null
  );
}

export function CalendarView() {
  const router = useRouter();
  const search = useSearchParams();
  const syncOnReturn = search.get("sync") === "google";
  const failedOnReturn = search.get("error") === "google";
  const [step, setStep] = useState<Step>("start");
  const [email, setEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function loadConnection() {
      try {
        if (syncOnReturn) {
          setPending(true);
          setMessage("Finishing your Google Calendar connection...");
        }
        const status = await calendarRequest("status");
        const current = connectedCalendar(status);
        if (!active) return;
        if (!current) {
          if (syncOnReturn)
            throw new Error(
              "Google did not finish connecting. Please try again.",
            );
          return;
        }
        setConnection(current);
        setStep("connected");
        if (syncOnReturn) {
          const result = await calendarRequest("sync");
          if (!active) return;
          setMessage(
            (result.imported || 0) + " calendar events synced to your account.",
          );
          router.replace("/calendar");
        }
      } catch (cause: any) {
        if (active) setError(cause?.message || String(cause));
      } finally {
        if (active) setPending(false);
      }
    }
    void loadConnection();
    return () => {
      active = false;
    };
  }, [router, syncOnReturn]);

  useEffect(() => {
    if (!failedOnReturn) return;
    setError(
      "Google Calendar was not connected: access was declined or the request expired. Please try again.",
    );
    router.replace("/calendar");
  }, [router, failedOnReturn]);

  async function connectGoogle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    setMessage("");
    try {
      const result = await calendarRequest("authorize");
      const authorizationUrl = new URL(result.authorizationUrl);
      if (
        authorizationUrl.protocol !== "https:" ||
        authorizationUrl.hostname !== "accounts.google.com"
      ) {
        throw new Error(
          "The calendar service returned an invalid Google authorization URL.",
        );
      }
      authorizationUrl.searchParams.set("login_hint", email.trim());
      window.location.assign(authorizationUrl.toString());
    } catch (cause: any) {
      setError(cause?.message || String(cause));
      setPending(false);
    }
  }

  async function syncCalendar() {
    setPending(true);
    setError("");
    setMessage("Syncing calendar events...");
    try {
      const result = await calendarRequest("sync");
      setMessage(
        (result.imported || 0) + " calendar events synced to your account.",
      );
    } catch (cause: any) {
      setError(cause?.message || String(cause));
      setMessage("");
    } finally {
      setPending(false);
    }
  }

  async function disconnectCalendar() {
    setPending(true);
    setError("");
    setMessage("");
    try {
      await calendarRequest("disconnect");
      setConnection(null);
      setStep("start");
      setMessage("Google Calendar disconnected.");
    } catch (cause: any) {
      setError(cause?.message || String(cause));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <ViewHead eyebrow="Calendar" title="Connect your calendar" />
      <section className="card v-calendar" aria-live="polite">
        {step === "start" ? (
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              setError("");
              setStep("providers");
            }}
          >
            <Icon name="calendar" size={17} /> Connect a calendar
          </button>
        ) : null}

        {step === "providers" ? (
          <div className="v-calendar-content">
            <div className="card-title">
              <h2>Choose a calendar</h2>
            </div>
            <div className="row">
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setError("");
                  setStep("google");
                }}
              >
                <Icon name="calendar" size={17} /> Google Calendar
              </button>
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setError("");
                  setMessage("Outlook Calendar is not available yet.");
                }}
              >
                <Icon name="calendar" size={17} /> Outlook Calendar
              </button>
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => {
                  setMessage("");
                  setStep(connection ? "connected" : "start");
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}

        {step === "google" ? (
          <form className="v-calendar-content stack" onSubmit={connectGoogle}>
            <div className="card-title">
              <h2>Connect Google Calendar</h2>
            </div>
            <label className="v-calendar-field">
              <span className="small secondary">Google account email</span>
              <input
                className="input"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <p className="small muted">
              Google will ask you to approve calendar access for this account.
            </p>
            <div className="row">
              <button
                className="btn btn-primary"
                type="submit"
                disabled={pending}
              >
                {pending ? (
                  <span className="spinner" />
                ) : (
                  <Icon name="calendar" size={17} />
                )}
                Continue with Google
              </button>
              <button
                className="btn btn-ghost"
                type="button"
                disabled={pending}
                onClick={() => setStep("providers")}
              >
                Back
              </button>
            </div>
          </form>
        ) : null}

        {step === "connected" ? (
          <div className="v-calendar-content">
            <div className="card-title">
              <h2>Google Calendar connected</h2>
            </div>
            {connection?.email ? (
              <p className="small secondary">{connection.email}</p>
            ) : null}
            {connection?.last_synced_at ? (
              <p className="small muted">
                Last synced{" "}
                {new Date(connection.last_synced_at).toLocaleString()}
              </p>
            ) : null}
            <div className="row">
              <button
                className="btn btn-primary"
                type="button"
                onClick={syncCalendar}
                disabled={pending}
              >
                {pending ? (
                  <span className="spinner" />
                ) : (
                  <Icon name="refresh" size={17} />
                )}
                Sync calendar
              </button>
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setError("");
                  setMessage("");
                  setStep("providers");
                }}
                disabled={pending}
              >
                <Icon name="calendar" size={17} /> Connect another calendar
              </button>
              <button
                className="btn btn-danger"
                type="button"
                onClick={disconnectCalendar}
                disabled={pending}
              >
                Disconnect
              </button>
            </div>
          </div>
        ) : null}

        {message ? (
          <p className="small secondary v-calendar-message" role="status">
            {message}
          </p>
        ) : null}
        {error ? (
          <p className="small v-calendar-error" role="alert">
            {error}
          </p>
        ) : null}
      </section>
    </>
  );
}
