"""Concrete, calendar-ready suggestions derived from causes and habits (SPEC §7.7)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from ..models import CalendarEvent, Cause, Dataset, Habit, Suggestion, new_id
from ..timeutil import at, day_hour, hour_label
from .attribution import FitResult
from .whatif import predict_day

MAX_SUGGESTIONS = 3


def _habit(habits: Sequence[Habit], key: str) -> Optional[Habit]:
    for h in habits:
        if h.key == key:
            return h
    return None


def _gain(ds: Dataset, d: date, mods: List[Dict[str, Any]], fit_: FitResult):
    try:
        r = predict_day(ds, d, mods, fit_)
        return r.delta, r.delta_low, r.delta_high
    except Exception:
        return 0.0, None, None


def _body(text: str, lo: Optional[float], hi: Optional[float]) -> str:
    if lo is None or hi is None:
        return text
    return "%s Likely %+.0f to %+.0f points." % (text, lo, hi)


def suggest(ds: Dataset, morning: date, causes: Sequence[Cause], habits: Sequence[Habit], fit_: FitResult,
            accepted: Dict[str, str], cache: Optional[dict] = None) -> List[Suggestion]:
    tz = ds.persona.tz
    today_events = ds.events_on(morning)
    tomorrow = morning + timedelta(days=1)
    tomorrow_events = ds.events_on(tomorrow)
    cause_keys = {c.factor for c in causes}
    out: List[Suggestion] = []

    def add(kind: str, title: str, body: str, gain, lo, hi, ev: Optional[CalendarEvent], factor: str, for_date: date = morning) -> None:
        sid = "sg-%s-%s" % (morning.isoformat(), kind)
        if any(s.id == sid for s in out) or len(out) >= MAX_SUGGESTIONS:
            return
        out.append(Suggestion(id=sid, kind=kind, title=title, body=body, predicted_gain=round(gain, 1), for_date=for_date,
                              proposed_event=ev, accepted=sid in accepted, related_factor=factor,
                              gain_low=None if lo is None else round(lo, 1), gain_high=None if hi is None else round(hi, 1)))

    late_habit = _habit(habits, "late_meeting")
    late_today = [e for e in today_events if e.type == "meeting" and day_hour(e.end, morning) >= 19.5]
    if "late_meeting_hours" in cause_keys or (late_habit and late_habit.confidence != "low") or late_today or not causes:
        if fit_.n_active.get("protected_evening", 0) >= 3 or True:
            ev = CalendarEvent(id=new_id("ev", "sg", morning, "protect_evening"), title="Wind down (StressLess)",
                               start=at(morning, 21.0, tzname=tz), end=at(morning, 22.0, tzname=tz), type="protected",
                               source="user", notes="Suggested by StressLess")
            gain, lo, hi = _gain(ds, morning, [{"op": "add", "event": {"title": ev.title, "start": ev.start.isoformat(), "end": ev.end.isoformat(), "type": "protected"}}], fit_)
            add("protect_evening", "Protect 21:00 to 22:00 tonight",
                _body("A wind-down block before bed: no screens, no work. On your protected evenings you fell asleep faster.", lo, hi),
                gain, lo, hi, ev, "protected_evening")
        if late_today:
            ev = max(late_today, key=lambda e: e.end)
            gain, lo, hi = _gain(ds, morning, [{"op": "end_at", "event_id": ev.id, "hour": 18.0}], fit_)
            add("move_meeting", "End %s by 18:00" % ev.title,
                _body("It is booked until %s. Late meetings kept your heart rate up long after they ended." % hour_label(day_hour(ev.end, morning)), lo, hi),
                gain, lo, hi, None, "late_meeting_hours")
    if "meetings_over_3" in cause_keys or "b2b_over_2" in cause_keys:
        meetings = sorted([e for e in today_events if e.type == "meeting"], key=lambda e: e.start)
        chain_end = None
        run = 1
        for prev, nxt in zip(meetings, meetings[1:]):
            if (nxt.start - prev.end).total_seconds() <= 600:
                run += 1
                if run >= 3:
                    chain_end = nxt.end
            else:
                run = 1
        if chain_end is not None:
            ev = CalendarEvent(id=new_id("ev", "sg", morning, "buffer"), title="Buffer (StressLess)", start=chain_end,
                               end=chain_end + timedelta(minutes=20), type="focus", source="user", notes="Suggested by StressLess")
            gain, lo, hi = _gain(ds, morning, [{"op": "add", "event": {"title": ev.title, "start": ev.start.isoformat(), "end": ev.end.isoformat(), "type": "focus"}}], fit_)
            add("buffer", "Add a 20-minute buffer after %s" % hour_label(day_hour(chain_end, morning)),
                "Your back-to-back block today ends at %s. A short pause lets your heart rate settle before the next thing." % hour_label(day_hour(chain_end, morning)),
                max(gain, 0.5), lo, hi, ev, "b2b_over_2")
    late_wo = _habit(habits, "late_workout")
    for d, evs in ((morning, today_events), (tomorrow, tomorrow_events)):
        wos = [e for e in evs if e.type == "workout" and day_hour(e.start, d) >= 19.5]
        if wos and (("workout_late" in cause_keys) or (late_wo and late_wo.confidence != "low")):
            ev = wos[-1]
            gain, lo, hi = _gain(ds, d, [{"op": "shift", "event_id": ev.id, "hours": 7.0 - day_hour(ev.start, d)}], fit_)
            add("move_workout", "Move %s to 07:00 %s" % (ev.title, "today" if d == morning else "tomorrow"),
                _body("Late training delays sleep onset for you; mornings do the opposite.", lo, hi), gain, lo, hi, None, "workout_late", d)
            break
    social_today = [e for e in today_events if e.type == "social" and day_hour(e.end, morning) >= 20.5]
    early_tomorrow = [e for e in tomorrow_events if e.type in ("meeting", "travel", "personal") and day_hour(e.start, tomorrow) < 7.5]
    if social_today and early_tomorrow:
        ev = early_tomorrow[0]
        gain, lo, hi = _gain(ds, tomorrow, [{"op": "shift", "event_id": ev.id, "hours": 1.5}], fit_)
        add("later_start", "Start tomorrow at 08:30",
            _body("Tonight is %s and tomorrow starts at %s. A later first meeting protects the sleep you will lose." % (social_today[0].title, hour_label(day_hour(ev.start, tomorrow))), lo, hi),
            gain, lo, hi, None, "early_start", tomorrow)
    trips = [e for e in today_events + tomorrow_events if e.type == "travel"]
    if trips:
        trip = trips[0]
        d = trip.start.date()
        ev = CalendarEvent(id=new_id("ev", "sg", morning, "recovery_day"), title="Recovery evening (StressLess)",
                           start=at(d, 20.0, tzname=tz), end=at(d, 22.0, tzname=tz), type="protected", source="user", notes="Suggested by StressLess")
        gain, lo, hi = _gain(ds, d, [{"op": "add", "event": {"title": ev.title, "start": ev.start.isoformat(), "end": ev.end.isoformat(), "type": "protected"}}], fit_)
        add("recovery_day", "Block a recovery evening after %s" % trip.title, _body("Travel days cost you sleep; keep the evening free.", lo, hi), gain, lo, hi, ev, "travel", d)
    return out


def _fold(line: str) -> str:
    out = []
    data = line.encode("utf-8")
    while len(data) > 75:
        cut = 75
        while cut > 0 and (data[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(data[:cut].decode("utf-8"))
        data = b" " + data[cut:]
    out.append(data.decode("utf-8"))
    return "\r\n".join(out)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def to_ics(ev: CalendarEvent, tzname: str = "Europe/Stockholm") -> str:
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//StressLess//Demo//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-TIMEZONE:%s" % tzname, "BEGIN:VEVENT",
        "UID:%s@stressless.local" % ev.id, "DTSTAMP:%s" % _utc(ev.start), "DTSTART:%s" % _utc(ev.start), "DTEND:%s" % _utc(ev.end),
        "SUMMARY:%s" % ev.title.replace(",", "\\,"), "DESCRIPTION:Suggested by StressLess",
    ]
    if ev.location_hint:
        lines.append("LOCATION:%s" % ev.location_hint.replace(",", "\\,"))
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
