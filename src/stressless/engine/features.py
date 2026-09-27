"""Per-day calendar features — the single vocabulary shared by the simulator and the engine.

The simulator calls ``day_features`` on the *attended* events to drive its causal model; the
engine calls it on ``ds.events_on(d)`` (events not marked ``attended=False``). Because both
sides use this one function, a definitional drift can never masquerade as an engine error.

Conventions (SPEC §3, §7.1):
* hour-of-day values are relative to midnight of the event's calendar day, so an event that
  ends 00:30 the next morning has ``end_hour == 24.5``;
* ``is_weekend`` marks the *night* before a non-workday (Fri/Sat nights);
* ``early_start`` looks only at meetings, travel and personal events (a 07:00 run is not an
  early start);
* a workout is ``late`` when it starts >= 19:30 **or** ends within two hours of the persona's
  usual bedtime.
"""
from __future__ import annotations

import re
from datetime import date
from typing import List, Optional, Sequence

from ..models import CalendarEvent, DayFeatures, Dataset
from ..timeutil import day_hour, hour_label, is_weekend_night

B2B_GAP_MIN = 10
LATE_MEETING_FROM_HOUR = 18.0
SOCIAL_EVENING_FROM_HOUR = 20.5
EARLY_START_BEFORE_HOUR = 7.5
PROTECTED_WINDOW = (20.0, 23.0)
PROTECTED_TITLE_RE = re.compile(r"wind.?down|no meetings|recovery|screen.?free", re.IGNORECASE)
TZ_SHIFT_RE = re.compile(r"tz_shift=([+-]?\d+(?:\.\d+)?)")
EARLY_START_TYPES = ("meeting", "travel", "personal")


def _usual_bedtime_hour(ds: Optional[Dataset]) -> float:
    """Persona bedtime as a day-relative hour (00:15 -> 24.25)."""
    if ds is None or ds.persona is None:
        return 23.0
    h = float(ds.persona.usual_bedtime)
    return h + 24.0 if h < 12.0 else h


def workout_slot_for(start_hour: float, end_hour: float, usual_bedtime_hour: float) -> str:
    if start_hour >= 19.5 or end_hour >= usual_bedtime_hour - 2.0:
        return "late"
    if start_hour < 10.0:
        return "morning"
    if start_hour < 17.0:
        return "midday"
    return "evening"


def day_features(ds: Optional[Dataset], d: date, events: Optional[Sequence[CalendarEvent]] = None) -> DayFeatures:
    """Compute calendar features for day ``d``.

    ``events`` overrides the dataset's events (used by the simulator and what-if). When ``ds``
    is None (pure what-if on a synthetic list) the default bedtime of 23:00 is used.
    """
    if events is None:
        evs = ds.events_on(d) if ds is not None else []
    else:
        evs = list(events)
    evs = sorted(evs, key=lambda e: (e.start, e.end))
    f = DayFeatures(date=d, dow=d.weekday(), is_weekend=1 if is_weekend_night(d) else 0)
    f.n_events = len(evs)
    f.event_ids = [e.id for e in evs]

    meetings = [e for e in evs if e.type == "meeting"]
    f.n_meetings = len(meetings)
    f.meeting_minutes = sum(max(0, e.duration_min) for e in meetings)

    # longest back-to-back chain (gap <= 10 min between consecutive meetings)
    run = best = 1 if meetings else 0
    for prev, nxt in zip(meetings, meetings[1:]):
        gap = (nxt.start - prev.end).total_seconds() / 60.0
        if gap <= B2B_GAP_MIN:
            run += 1
        else:
            run = 1
        best = max(best, run)
    f.max_b2b_run = best

    if meetings:
        f.last_meeting_end_hour = max(day_hour(e.end, d) for e in meetings)
        f.late_meeting_hours = max(0.0, f.last_meeting_end_hour - LATE_MEETING_FROM_HOUR)

    starters = [e for e in evs if e.type in EARLY_START_TYPES]
    if starters:
        f.first_start_hour = min(day_hour(e.start, d) for e in starters)
        f.early_start = 1 if f.first_start_hour < EARLY_START_BEFORE_HOUR else 0

    socials = [e for e in evs if e.type == "social"]
    if socials:
        f.social_end_hour = max(day_hour(e.end, d) for e in socials)
        f.evening_social = 1 if f.social_end_hour >= SOCIAL_EVENING_FROM_HOUR else 0

    workouts = [e for e in evs if e.type == "workout"]
    if workouts:
        last = max(workouts, key=lambda e: e.start)
        f.workout_minutes = sum(max(0, e.duration_min) for e in workouts)
        f.workout_slot = workout_slot_for(day_hour(last.start, d), day_hour(last.end, d), _usual_bedtime_hour(ds))

    travels = [e for e in evs if e.type == "travel"]
    if travels:
        f.travel = 1
        for e in travels:
            m = TZ_SHIFT_RE.search(e.notes or "")
            if m:
                f.tz_shift_hours = float(m.group(1))

    for e in evs:
        if e.type == "protected":
            s, en = day_hour(e.start, d), day_hour(e.end, d)
            if en > PROTECTED_WINDOW[0] and s < PROTECTED_WINDOW[1]:
                f.protected_evening = 1
        elif PROTECTED_TITLE_RE.search(e.title or ""):
            f.protected_evening = 1
    return f


def features_range(ds: Dataset, start: date, end: date) -> List[DayFeatures]:
    from ..timeutil import day_range
    return [day_features(ds, d) for d in day_range(start, end)]


def describe_features(f: DayFeatures) -> List[str]:
    """Short chips for the UI: ['6 meetings', '4 back-to-back', 'ends 20:30', 'late workout']."""
    chips: List[str] = []
    if f.n_meetings:
        chips.append(f"{f.n_meetings} meeting" + ("s" if f.n_meetings != 1 else ""))
    if f.max_b2b_run >= 3:
        chips.append(f"{f.max_b2b_run} back-to-back")
    if f.late_meeting_hours > 0 and f.last_meeting_end_hour is not None:
        chips.append(f"meeting until {hour_label(f.last_meeting_end_hour)}")
    if f.early_start and f.first_start_hour is not None:
        chips.append(f"first event {hour_label(f.first_start_hour)}")
    if f.evening_social and f.social_end_hour is not None:
        chips.append(f"social until {hour_label(f.social_end_hour)}")
    if f.workout_slot != "none":
        chips.append(f"{f.workout_slot} workout")
    if f.travel:
        chips.append("travel day" + (f" ({f.tz_shift_hours:+.0f} h)" if f.tz_shift_hours else ""))
    if f.protected_evening:
        chips.append("protected evening")
    if f.is_weekend:
        chips.append("weekend night")
    if not chips:
        chips.append("calm day")
    return chips
