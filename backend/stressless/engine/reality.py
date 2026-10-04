"""Reality checks: ask only when calendar, location and body disagree (SPEC §7.4)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..models import CalendarEvent, Dataset, Evidence, LocationVisit, RealityCheck, new_id
from ..timeutil import at, day_range, fmt_day, fmt_hm, parse_dt
from .matching import visits_during, workout_signature

log = logging.getLogger("stressless.engine.reality")

EXPECTED = {
    "workout": ("gym", "outdoors"),
    "social": ("restaurant", "bar"),
    "travel": ("airport", "transit", "away", "hotel"),
}
PLACE_WORDS = {"home": "at home", "office": "at the office", "gym": "at the gym", "restaurant": "at a restaurant",
               "bar": "at a bar", "transit": "in transit", "airport": "at the airport", "hotel": "at the hotel",
               "away": "away", "outdoors": "outdoors", "other": "elsewhere"}


def _hm_range(a: datetime, b: datetime) -> str:
    return "%s–%s" % (fmt_hm(a), fmt_hm(b))


def _dominant(visits: List[Tuple[LocationVisit, int]], expected: Tuple[str, ...]) -> Tuple[int, int, Optional[LocationVisit]]:
    exp = other = 0
    dom: Optional[LocationVisit] = None
    for v, ov in visits:
        if v.place_type in expected:
            exp += ov
        else:
            other += ov
            if dom is None:
                dom = v
    return exp, other, dom


def _hr_chip(sig: Dict[str, Any]) -> Optional[Evidence]:
    if not sig.get("n_samples"):
        return Evidence(kind="hr", text="No heart-rate data in that window (watch not worn)")
    if sig["minutes_over_120"] >= 15:
        return Evidence(kind="hr", text="Heart rate %s bpm on average, above 120 for %d min" % (int(sig["mean"]), sig["minutes_over_120"]),
                        value=sig["mean"], unit="bpm")
    return Evidence(kind="hr", text="Heart rate stayed at %d–%d bpm" % (int(sig["min"]), int(sig["max"])), value=sig["mean"], unit="bpm")


def _booked_check(ds: Dataset, ev: CalendarEvent, d: date, visits: List[LocationVisit]) -> Optional[RealityCheck]:
    expected = EXPECTED[ev.type]
    dur = max(1, ev.duration_min)
    during = visits_during(ds, ev.start, ev.end)
    exp_ov, other_ov, dom = _dominant(during, expected)
    sig = workout_signature(ds, ev.start, ev.end)
    hr_confirms = (ev.type == "workout" and sig["minutes_over_120"] >= 0.4 * dur) or \
                  (ev.type == "social" and sig.get("mean") is not None and sig["mean"] >= ds.persona.resting_hr + 20)
    if exp_ov >= 0.5 * dur or hr_confirms:
        return None
    label = {"workout": "the gym" if "gym" in (ev.location_hint or "gym").lower() or ev.title.lower() == "gym" else ev.title.lower(),
             "social": ev.title.lower(), "travel": "the trip"}[ev.type]
    evidence = [Evidence(kind="calendar", text="Booked: %s %s" % (ev.title, _hm_range(ev.start, ev.end)))]
    if other_ov >= 0.5 * dur and (ev.type != "workout" or sig["minutes_over_120"] < 5):
        kind = "location_mismatch" if ev.type == "travel" else "booked_not_seen"
        if dom is not None:
            evidence.append(Evidence(kind="location", text="%s %s (Maps)" % (PLACE_WORDS.get(dom.place_type, "elsewhere").capitalize(), _hm_range(dom.start, dom.end))))
        chip = _hr_chip(sig)
        if chip:
            evidence.append(chip)
    elif ev.type in ("workout", "social") and not visits:
        kind = "booked_not_seen"
        evidence.append(Evidence(kind="location", text="No location data that day (phone off?)"))
        chip = _hr_chip(sig)
        if chip:
            evidence.append(chip)
    else:
        return None
    if ev.type == "workout":
        q = "Did you make it to %s on %s, %s?" % (label, fmt_day(d), fmt_hm(ev.start))
        consequence = "If no, this workout leaves your patterns."
    elif ev.type == "social":
        q = "Did %s on %s happen?" % (ev.title, fmt_day(d))
        consequence = "If no, this evening leaves your patterns."
    else:
        q = "Did the trip on %s (%s) happen?" % (fmt_day(d), ev.title)
        consequence = "If no, this travel day leaves your patterns."
    return RealityCheck(id="rc-%s" % ev.id, date=d, kind=kind, question=q, status="open", event_id=ev.id,
                        evidence=evidence, consequence=consequence)


def _unbooked_checks(ds: Dataset, d: date, events: List[CalendarEvent], visits: List[LocationVisit]) -> List[RealityCheck]:
    out: List[RealityCheck] = []
    for v in visits:
        if v.start.date() != d or v.duration_min < 40:
            continue
        detected_id = new_id("ev", "detected", v.id)   # an event added by answering "yes" keeps its check visible
        if v.place_type == "gym":
            sig = workout_signature(ds, v.start, v.end)
            if sig["minutes_over_120"] < 15:
                continue
            if any(e.type == "workout" and e.id != detected_id and _overlap_frac(e, v) >= 0.3 for e in events):
                continue
            title, etype = "Gym (detected)", "workout"
            q = "Looks like a workout at %s on %s, %s — add it to your calendar?" % (v.place_name, fmt_day(d), _hm_range(v.start, v.end))
            evidence = [Evidence(kind="location", text="At %s %s (Maps)" % (v.place_name, _hm_range(v.start, v.end))), _hr_chip(sig),
                        Evidence(kind="calendar", text="Nothing booked")]
            consequence = "If yes, a workout is added to your calendar and patterns."
        elif v.place_type in ("restaurant", "bar"):
            if v.start.hour < 17:
                continue
            if any(e.type == "social" and e.id != detected_id and _overlap_frac(e, v) >= 0.3 for e in events):
                continue
            title, etype = "Dinner out (detected)" if v.place_type == "restaurant" else "Evening out (detected)", "social"
            q = "Looks like an evening at %s on %s, %s — add it to your calendar?" % (v.place_name, fmt_day(d), _hm_range(v.start, v.end))
            sig = workout_signature(ds, v.start, v.end)
            evidence = [Evidence(kind="location", text="At %s %s (Maps)" % (v.place_name, _hm_range(v.start, v.end))),
                        Evidence(kind="hr", text="Heart rate %s bpm on average" % (int(sig["mean"]) if sig.get("mean") else "–")),
                        Evidence(kind="calendar", text="Nothing booked")]
            consequence = "If yes, an evening out is added to your calendar and patterns."
        else:
            continue
        suggested = CalendarEvent(id=new_id("ev", "detected", v.id), title=title, start=v.start, end=v.end, type=etype,
                                  location_hint=v.place_name, source="user", attended=True, notes="kind=strength" if etype == "workout" else None)
        out.append(RealityCheck(id="rc-%s" % v.id, date=d, kind="seen_not_booked", question=q, status="open", visit_id=v.id,
                                evidence=[e for e in evidence if e is not None], suggested_event=suggested, consequence=consequence))
    return out


def _overlap_frac(e: CalendarEvent, v: LocationVisit) -> float:
    lo, hi = max(e.start, v.start), min(e.end, v.end)
    if hi <= lo:
        return 0.0
    return (hi - lo).total_seconds() / max(60.0, (v.end - v.start).total_seconds())


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
            visits = ds.visits_on(d)
            for ev in events:
                if ev.type == "social" and "home" in (ev.location_hint or "").lower():
                    continue   # cannot be verified by location; never ask
                if ev.type in EXPECTED and ev.end <= at(ds.today, 0, tzname=ds.persona.tz):
                    c = _booked_check(ds, ev, d, visits)
                    if c is not None:
                        checks.append(c)
            checks.extend(_unbooked_checks(ds, d, events, visits))
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
                                visit_id=c.visit_id, evidence=list(c.evidence), suggested_event=c.suggested_event,
                                answered_at=answered_at, consequence=c.consequence))
    out.sort(key=lambda c: (0 if c.status == "open" else 1, -c.date.toordinal()))
    return out
