"""Build the engine's ``Dataset`` from the real-data tables (docs/SCHEMA.md) instead of the simulator.

The derived tables already hold one row per night or day, so this is mostly mapping columns onto the engine's
models. Rows come from ``UserStore.rows`` as PostgREST JSON (ISO strings), read through the user's own token.

The persona of a real user is only a name and a time zone; the personal baselines the engine reads from it
(resting heart rate, usual bed and wake times, sleep need) are computed from the user's history here.
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import (EVENT_TYPES, STAGE_KINDS, CalendarEvent, DailyActivity, Dataset, HeartRateDay, Persona,
                      SleepNight, SleepStage, WatchWorkout, new_id)
from ..reports import SourceStatus
from ..timeutil import DEFAULT_TZ, parse_date, parse_dt
from .base import classify_event
from .build import build_dataset

log = logging.getLogger("stressless.connectors.real_data")
DAYS = 70                                      # history the engine and the reports look at
AHEAD = 7                                      # calendar days after today (planner, suggestions)

HEALTH_SOURCES = ("health_connect", "apple_health")
SOURCE_LABELS = {"health_connect": "Health Connect (Android)", "apple_health": "Apple Health (iPhone)",
                 "google_calendar": "Google Calendar"}


def valid_tz(name: Optional[str]) -> str:
    try:
        ZoneInfo(name or "")
        return name  # type: ignore[return-value]
    except (ZoneInfoNotFoundError, ValueError):
        return DEFAULT_TZ


def _dt(value: Any, tzname: str) -> Optional[datetime]:
    return parse_dt(value, tzname) if value else None


# --------------------------------------------------------------------------- #
# Row -> engine model
# --------------------------------------------------------------------------- #
def night_from_row(row: Dict[str, Any], tzname: str, hrv_key: str) -> SleepNight:
    stages = []
    for st in row.get("stages") or []:
        if st.get("kind") in STAGE_KINDS and st.get("start") and st.get("end"):
            stages.append(SleepStage(kind=st["kind"], start=parse_dt(st["start"], tzname), end=parse_dt(st["end"], tzname)))
    hrv = row.get(hrv_key)
    return SleepNight(
        date=parse_date(row["night_date"]), worn=True,
        in_bed_start=_dt(row.get("in_bed_at"), tzname), sleep_onset=_dt(row.get("onset_at"), tzname),
        wake_time=_dt(row.get("wake_at"), tzname), out_of_bed=_dt(row.get("out_of_bed_at"), tzname), stages=stages,
        interruptions=int(row.get("interruptions") or 0), awake_min=int(row.get("awake_min") or 0),
        duration_min=int(row.get("asleep_min") or 0), deep_min=int(row.get("deep_min") or 0),
        rem_min=int(row.get("rem_min") or 0), core_min=int(row.get("core_min") or 0),
        hrv_ms=None if hrv is None else float(hrv),
        resting_hr=None if row.get("resting_hr") is None else int(row["resting_hr"]),
        resp_rate=None if row.get("resp_rate") is None else float(row["resp_rate"]),
        wrist_temp_dev=None if row.get("skin_temp_dev") is None else float(row["skin_temp_dev"]),
        spo2=None if row.get("spo2") is None else float(row["spo2"]),
        score=None if row.get("score") is None else int(row["score"]),
        score_parts={k: int(v) for k, v in (row.get("score_parts") or {}).items()},
        score_source=row.get("score_source") or "stressless")


def hr_day_from_row(row: Dict[str, Any]) -> HeartRateDay:
    bpm = [None if b is None else int(b) for b in (row.get("bpm") or [])]
    return HeartRateDay(date=parse_date(row["day"]), bpm=(bpm + [None] * 1440)[:1440])


def activity_from_row(row: Dict[str, Any], tzname: str) -> DailyActivity:
    d = parse_date(row["day"])
    workouts = []
    for i, w in enumerate(row.get("workouts") or []):
        if not (w.get("start") and w.get("end")):
            continue
        workouts.append(WatchWorkout(id=new_id("w", d.isoformat(), i), kind=w.get("kind") or "other",
                                     start=parse_dt(w["start"], tzname), end=parse_dt(w["end"], tzname),
                                     avg_hr=int(w.get("avg_hr") or 0), max_hr=int(w.get("max_hr") or 0),
                                     calories=int(w.get("calories") or 0)))
    hourly = [int(h or 0) for h in (row.get("hourly_steps") or [])]
    return DailyActivity(date=d, steps=int(row.get("steps") or 0), active_minutes=int(row.get("active_min") or 0),
                         workouts=workouts, hourly_steps=hourly)


def event_from_row(row: Dict[str, Any], tzname: str) -> CalendarEvent:
    title = row.get("title") or "(no title)"
    kind = row.get("category")
    if kind not in EVENT_TYPES:                # "uncategorized" prototype rows: classify the way the importers do
        kind = classify_event(title, row.get("location"))
    attendees = row.get("attendee_count")
    if attendees is None:                      # before the migration that adds the generated column
        guests = row.get("guests")
        attendees = len(guests) if isinstance(guests, list) else 0
    return CalendarEvent(id=str(row["id"]), title=title, start=parse_dt(row["starts_at"], tzname),
                         end=parse_dt(row["ends_at"], tzname), type=kind, location_hint=row.get("location"),
                         attendees=int(attendees), recurring_key=row.get("recurring_key"),
                         source=row.get("provider") or "user")


# --------------------------------------------------------------------------- #
# Personal baselines
# --------------------------------------------------------------------------- #
def _clock_hours(dt: Optional[datetime], evening: bool) -> Optional[float]:
    if dt is None:
        return None
    h = dt.hour + dt.minute / 60.0
    return h + 24.0 if (evening and h < 12) else h          # bedtime 00:30 -> 24.5, as the persona model expects


def _median(vals: List[Optional[float]], default: float) -> float:
    vals = [v for v in vals if v is not None]
    return float(statistics.median(vals)) if len(vals) >= 3 else default


def persona_from_history(name: str, tzname: str, nights: List[SleepNight]) -> Persona:
    base = Persona(key="real", name=name, tagline="Your own data", description="Your watch and calendar data.", tz=tzname)
    weekday = [n for n in nights if n.date.weekday() < 4]  # Mon-Thu nights lead into workdays
    base.resting_hr = int(round(_median([n.resting_hr for n in nights], base.resting_hr)))
    base.hrv_ms = _median([n.hrv_ms for n in nights], base.hrv_ms)
    base.resp_rate = _median([n.resp_rate for n in nights], base.resp_rate)
    base.usual_bedtime = _median([_clock_hours(n.in_bed_start, True) for n in weekday], base.usual_bedtime)
    base.usual_wake = _median([_clock_hours(n.wake_time, False) for n in weekday], base.usual_wake)
    # Sleep need: what the person gets on nights they slept in (weekends), never below 7 h or above 9 h 30.
    free = [n.duration_min for n in nights if n.date.weekday() >= 4 and n.duration_min]
    base.sleep_need_min = int(min(570, max(420, _median(free, base.sleep_need_min))))
    return base


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #
def load_dataset(store, today: date, days: int = DAYS, name: str = "You") -> Dataset:
    """The user's last ``days`` nights and days, plus calendar events up to a week ahead."""
    tzname = valid_tz(store.time_zone())
    start = today - timedelta(days=days)
    lo, hi = start.isoformat(), today.isoformat()
    night_rows = store.rows("sleep_nights", "night_date", lo, hi)
    # HRV: Health Connect (RMSSD) and HealthKit (SDNN) are different measures; use whichever this user has more of.
    n_rmssd = sum(1 for r in night_rows if r.get("hrv_rmssd_ms") is not None)
    n_sdnn = sum(1 for r in night_rows if r.get("hrv_sdnn_ms") is not None)
    hrv_key = "hrv_sdnn_ms" if n_sdnn >= n_rmssd else "hrv_rmssd_ms"
    nights = [night_from_row(r, tzname, hrv_key) for r in night_rows]
    hr_days = [hr_day_from_row(r) for r in store.rows("heart_rate_days", "day", lo, hi)]
    activity = [activity_from_row(r, tzname) for r in store.rows("daily_activity", "day", lo, hi)]
    # starts_at is a timestamp: bound by dates with a day of margin, build_dataset trims to the window.
    events = [event_from_row(r, tzname) for r in store.rows("calendar_events", "starts_at", (start - timedelta(days=1)).isoformat(),
                                                           (today + timedelta(days=AHEAD + 2)).isoformat())]
    persona = persona_from_history(name, tzname, nights)
    ds = build_dataset(persona, events, [], hr_days, nights, activity, today, days)
    ds.source = "real"
    log.info("loaded real data for %s: %d nights, %d heart-rate days, %d activity days, %d events",
             today, len(nights), len(hr_days), len(activity), len(events))
    return ds


# --------------------------------------------------------------------------- #
# Readiness dialog
# --------------------------------------------------------------------------- #
def _latest(values: List[Any]) -> Optional[datetime]:
    out = [datetime.fromisoformat(str(v).replace("Z", "+00:00")) for v in values if v]
    return max(out) if out else None


def real_sources(store, ds: Dataset, morning: date) -> List[SourceStatus]:
    """One entry per connected source, plus a required health entry when no health source is connected.

    ``data_until`` and ``synced_at`` come from the sync bookkeeping (``connection_streams``); whether the health
    source is ``ready`` comes from the data itself: is there a scored night before ``morning``?
    """
    connections = store.rows("provider_connections")
    streams = store.rows("connection_streams")
    night = ds.night(morning - timedelta(days=1))
    night_ready = bool(night and night.worn and night.score is not None)
    out: List[SourceStatus] = []
    for provider in sorted({c["provider"] for c in connections}):
        conns = [c for c in connections if c["provider"] == provider]
        ids = {c["id"] for c in conns}
        mine = [s for s in streams if s.get("connection_id") in ids]
        main_type = "sleep_session" if provider in HEALTH_SOURCES else "calendar_event"
        main = [s for s in mine if s.get("data_type") == main_type] or mine
        health = provider in HEALTH_SOURCES
        connected = any(c.get("status") == "connected" for c in conns)
        out.append(SourceStatus(
            key=provider, label=SOURCE_LABELS.get(provider, provider.replace("_", " ").capitalize()), connected=connected,
            data_until=_latest([s.get("data_until") for s in main]),
            synced_at=_latest([s.get("last_synced_at") for s in mine] + [c.get("last_synced_at") for c in conns]),
            required=health, ready=night_ready if health else connected))
    if not any(s.required for s in out):
        out.insert(0, SourceStatus(key="health", label="Health data from your phone", connected=False, required=True,
                                   ready=night_ready))
    return out
