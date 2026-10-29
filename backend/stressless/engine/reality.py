"""Reality checks: ask only when the calendar and the watch disagree about a workout (SPEC §7.4).

Only workouts are checked. Exercise lifts heart rate far above resting; a dinner, a trip or a meeting
does not leave a mark the watch can tell apart from a quiet evening, so those are never asked about.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..models import CalendarEvent, Dataset, Evidence, RealityCheck, WatchWorkout, new_id
from ..timeutil import at, day_range, fmt_day, fmt_hm, parse_dt
from .matching import workout_signature

log = logging.getLogger("stressless.engine.reality")

ACTIVE_LIFT_BPM = 50            # a 5-min rolling mean this far above resting is exercise, not a stressful meeting
MIN_HR_SESSION_MIN = 30         # raised heart rate alone must last this long (a brisk walk between meetings does not)
MIN_WATCH_WORKOUT_MIN = 20
MIN_COVERAGE = 0.6              # below this share of the booked window on the wrist, the watch cannot disagree; never ask
MOVED_WINDOW = timedelta(hours=2)   # a session this close to a booked workout is that workout, done earlier or later

Session = Tuple[datetime, datetime, Optional[WatchWorkout]]


def _hm_range(a: datetime, b: datetime) -> str:
    return "%s–%s" % (fmt_hm(a), fmt_hm(b))


def _hr_chip(sig: Dict[str, Any]) -> Evidence:
    if sig["minutes_over_120"] >= 15:
        return Evidence(kind="hr", text="Heart rate %s bpm on average, above 120 for %d min" % (int(sig["mean"]), sig["minutes_over_120"]),
                        value=sig["mean"], unit="bpm")
    return Evidence(kind="hr", text="Heart rate stayed at %d–%d bpm" % (int(sig["min"]), int(sig["max"])), value=sig["mean"], unit="bpm")


def _watch_workouts(ds: Dataset, d: date) -> List[WatchWorkout]:
    act = ds.activity_on(d)
    return list(act.workouts) if act else []


def _sessions(ds: Dataset, d: date) -> List[Session]:
    """Stretches of exercise on ``d``: sustained raised heart rate, plus whatever the watch logged itself."""
    out: List[Session] = []
    hr = ds.hr(d)
    if hr is not None:
        level = ds.persona.resting_hr + ACTIVE_LIFT_BPM
        m = 0
        while m < len(hr.bpm):
            window = [b for b in hr.bpm[max(0, m - 4):m + 1] if b is not None]
            if hr.bpm[m] is not None and window and sum(window) / len(window) > level:
                s = m
                while m < len(hr.bpm) and hr.bpm[m] is not None:
                    window = [b for b in hr.bpm[max(0, m - 4):m + 1] if b is not None]
                    if sum(window) / len(window) <= level:
                        break
                    m += 1
                if m - s >= MIN_HR_SESSION_MIN:
                    out.append((at(d, s / 60.0, tzname=ds.persona.tz), at(d, m / 60.0, tzname=ds.persona.tz), None))
            m += 1
    for w in _watch_workouts(ds, d):
        hit = next((i for i, (s, e, _) in enumerate(out) if s < w.end and w.start < e), None)
        if hit is not None:
            s, e, _ = out[hit]
            out[hit] = (min(s, w.start), max(e, w.end), w)
        elif (w.end - w.start).total_seconds() >= MIN_WATCH_WORKOUT_MIN * 60:
            out.append((w.start, w.end, w))
    return sorted(out, key=lambda t: t[0])


def _near(ev: CalendarEvent, s: datetime, e: datetime) -> bool:
    return s < ev.end + MOVED_WINDOW and ev.start - MOVED_WINDOW < e


def _booked_check(ds: Dataset, ev: CalendarEvent, d: date) -> Optional[RealityCheck]:
    dur = max(1, ev.duration_min)
    sig = workout_signature(ds, ev.start, ev.end)
    if sig["n_samples"] < MIN_COVERAGE * dur:
        return None
    if sig["minutes_over_120"] >= 0.4 * dur or any(_near(ev, s, e) for s, e, _ in _sessions(ds, d)):
        return None
    evidence = [Evidence(kind="calendar", text="Booked: %s %s" % (ev.title, _hm_range(ev.start, ev.end))), _hr_chip(sig)]
    label = "the gym" if "gym" in (ev.location_hint or "gym").lower() or ev.title.lower() == "gym" else ev.title.lower()
    q = "Did you make it to %s on %s, %s?" % (label, fmt_day(d), fmt_hm(ev.start))
    return RealityCheck(id="rc-%s" % ev.id, date=d, kind="booked_not_seen", question=q, status="open", event_id=ev.id,
                        evidence=evidence, consequence="If no, this workout leaves your patterns.")


def _unbooked_checks(ds: Dataset, d: date, events: List[CalendarEvent]) -> List[RealityCheck]:
    out: List[RealityCheck] = []
    workouts = [e for e in events if e.type == "workout"]
    for s, e, w in _sessions(ds, d):
        key = w.id if w is not None else new_id("act", d, fmt_hm(s))
        detected_id = new_id("ev", "detected", key)   # an event added by answering "yes" keeps its check visible
        if any(ev.id != detected_id and _near(ev, s, e) for ev in workouts):
            continue
        q = "Looks like a workout on %s, %s — add it to your calendar?" % (fmt_day(d), _hm_range(s, e))
        sig = workout_signature(ds, s, e)
        if w is not None:
            evidence = [Evidence(kind="hr", text="Watch logged a %s workout, %d bpm on average" % (w.kind, w.avg_hr), value=w.avg_hr, unit="bpm")]
        else:
            evidence = [Evidence(kind="hr", text="Heart rate %d bpm on average for %d min" % (int(sig["mean"] or 0), (e - s).total_seconds() // 60),
                                 value=sig["mean"], unit="bpm")]
        evidence.append(Evidence(kind="calendar", text="Nothing booked"))
        suggested = CalendarEvent(id=detected_id, title="Workout (detected)", start=s, end=e, type="workout",
                                  source="user", attended=True, notes="kind=%s" % (w.kind if w is not None else "strength"))
        out.append(RealityCheck(id="rc-%s" % key, date=d, kind="seen_not_booked", question=q, status="open",
                                workout_id=w.id if w is not None else None, evidence=evidence, suggested_event=suggested,
                                consequence="If yes, a workout is added to your calendar and patterns."))
    return out


def reality_checks(ds: Dataset, start: date, end: date, answers: Dict[str, Dict[str, Any]], cache: Optional[dict] = None) -> List[RealityCheck]:
    """All checks for nights ``start..end`` (past days only), answers applied, open first (newest first)."""
    key = ("reality", start, end)
    checks: List[RealityCheck]
    if cache is not None and key in cache:
        checks = cache[key]
    else:
        checks = []
        for d in day_range(start, min(end, ds.today - timedelta(days=1))):
            events = ds.events_on(d, include_unattended=True)
            for ev in events:
                if ev.type == "workout" and ev.end <= at(ds.today, 0, tzname=ds.persona.tz):
                    c = _booked_check(ds, ev, d)
                    if c is not None:
                        checks.append(c)
            checks.extend(_unbooked_checks(ds, d, events))
        if cache is not None:
            cache[key] = checks
    out: List[RealityCheck] = []
    for c in checks:
        a = answers.get(c.id)
        status, answered_at = "open", None
        if a and a.get("answer") in ("yes", "no"):
            status = a["answer"]
            ts = a.get("ts")
            try:
                answered_at = parse_dt(ts, ds.persona.tz) if ts else None
            except Exception:
                answered_at = None
        out.append(RealityCheck(id=c.id, date=c.date, kind=c.kind, question=c.question, status=status, event_id=c.event_id,
                                workout_id=c.workout_id, evidence=list(c.evidence), suggested_event=c.suggested_event,
                                answered_at=answered_at, consequence=c.consequence))
    out.sort(key=lambda c: (0 if c.status == "open" else 1, -c.date.toordinal()))
    return out
