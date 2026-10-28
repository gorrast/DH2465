"""Lifestyle patterns: links between the data sources. Steps, workouts, the calendar, music, phone use, coffee,
alcohol and sleep rhythm against the night after them (and some against the same day's heart rate), and short
nights against the day after ("on your days under 6 500 steps you sleep 20 min less", "on days you listen to
Radiohead your daytime heart rate is 4 bpm lower").

The report model gets these links ready-made and picks the ones worth telling; it never computes one itself.

Same method as ``habits``: a with/without split stratified by weekend, a bootstrap interval and the same confidence
rule. What differs:

* the split points are the person's own (their lowest or highest third of days), not population numbers;
* each cause is tested against several outcomes (sleep score, time asleep, sleep onset, HRV, resting heart rate, or
  next-day steps and screen time), and the outcome is always measured *after* the cause;
* an outcome reaches the report model in one of two tiers. ``strong``: the 95 % interval excludes zero, the effect
  is big enough to notice and the confidence is medium or high. ``hint``: only the 80 % interval excludes zero (a
  weaker signal, or few days, as with a handful of evenings with alcohol), still big enough to notice; its
  confidence is always low and the report presents it as an early hint worth watching.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..models import Dataset
from ..timeutil import is_weekend_night
from . import baselines as bl
from .features import day_features
from .habits import CONF_WEIGHT, confidence_for, stratified_effect

HISTORY_DAYS = 56                              # days the patterns are computed over
MIN_DAYS = 14                                  # days with the cause measured before a split is made
CHECKIN_MIN_DAYS = 10                          # the same for causes the person logs by hand
MIN_GROUP = 4                                  # days on each side of the split for an outcome to be tested
MIN_CALENDAR_DAYS = 5                          # days with events before a calendar counts as connected
BOOTSTRAP = 400
HINT_LEVEL = 0.80                              # interval that must exclude zero for a hint (95 % for strong)
MIN_STEPS = 100                                # fewer steps in a day means the phone was not carried, not a lazy day
ONSET_HISTORY = 14                             # nights behind a person's usual sleep onset
OFF_RHYTHM_MIN = 60.0                          # sleep onset this far from the usual counts as off-rhythm
SLEEP_DEBT_NIGHTS = 3
SLEEP_DEBT_MIN = 120.0                         # minutes short of the sleep need over SLEEP_DEBT_NIGHTS nights
DAY_HR_FROM, DAY_HR_TO = 8 * 60, 22 * 60       # waking minutes the daytime heart rate is averaged over
DAY_HR_MIN_MINUTES = 240                       # worn minutes needed for a daytime heart rate
WORKOUT_HR_AFTER = 30                          # minutes after a workout left out of the daytime heart rate
LATE_HOUR = 22                                 # listening or streaming from this hour counts as late
MIN_ARTIST_MIN = 5.0                           # minutes of an artist before a day counts as a day with them
MAX_ARTISTS = 6                                # most-played artists and podcasts tested as their own cause
MAX_PAIRS = 4                                  # activity x media pairs ("Einaudi during Study session") tested
PAIR_ACTIVITIES = 5                            # most frequent calendar activities looked at for pairs
AFTER_HOURS = 4                                # media starting this long after an activity ended counts as "after" it
MAX_SERIES = 4                                 # most frequent recurring calendar series tested as their own cause
ACTIVITY_HR_MIN_MINUTES = 30                   # worn minutes of an activity needed for a heart rate during it
ACTIVITY_PHONE_MIN_MINUTES = 30                # minutes of an activity needed for a pickup rate during it
GYM_WORDS = ("gym", "strength", "weight", "functional", "crossfit", "sats", "styrka")
CARDIO_WORDS = ("run", "jog", "cycl", "bik", "ride", "swim", "walk", "hik", "row", "ski", "elliptical", "löp")


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OutcomeDef:
    key: str
    label: str
    unit: str
    good: str                                  # "up" | "down"
    min_effect: float                          # smallest effect worth telling someone about
    more: str                                  # "%s more sleep" style phrases, filled with the formatted size
    less: str
    get: Callable[[Dataset, date], Optional[float]]
    night: bool                                # measured on the night of the day (else on the day itself)
    source: str = "sleep"                      # which data it comes from: sleep | activity | phone | heart
    same_day: bool = False                     # measured on the same day as the cause, not after it


def _steps(ds: Dataset, d: date) -> Optional[float]:
    a = ds.activity_on(d)
    return float(a.steps) if a is not None and a.steps >= MIN_STEPS else None


def _night(key: str) -> Callable[[Dataset, date], Optional[float]]:
    return lambda ds, d: bl.night_metric(ds.night(d), key)


def _metric(key: str) -> Callable[[Dataset, date], Optional[float]]:
    return lambda ds, d: ds.metric_on(d, key)


def _workout_windows(ds: Dataset, d: date) -> List[Tuple[int, int]]:
    """Minutes of day ``d`` (start, end) taken up by a workout, from the watch and the calendar."""
    out = []
    a = ds.activity_on(d)
    spans = [(w.start, w.end) for w in (a.workouts if a else [])]
    spans += [(e.start, e.end) for e in ds.events_on(d) if e.type == "workout"]
    for start, end in spans:
        if start.date() == d:
            out.append((start.hour * 60 + start.minute, end.hour * 60 + end.minute if end.date() == d else 1440))
    return out


def daytime_hr(ds: Dataset, d: date) -> Optional[float]:
    """Mean heart rate over the waking day, leaving out workouts and the half hour after them."""
    hr = ds.hr(d)
    if hr is None:
        return None
    skip = _workout_windows(ds, d)
    vals = [b for m, b in enumerate(hr.bpm[DAY_HR_FROM:DAY_HR_TO], DAY_HR_FROM)
            if b is not None and not any(s <= m < e + WORKOUT_HR_AFTER for s, e in skip)]
    return statistics.fmean(vals) if len(vals) >= DAY_HR_MIN_MINUTES else None


OUTCOMES: Dict[str, OutcomeDef] = {o.key: o for o in (
    OutcomeDef("score", "Sleep score", "points", "up", 1.5, "sleep score %s points higher", "sleep score %s points lower",
               _night("score"), True),
    OutcomeDef("duration_min", "Time asleep", "min", "up", 10, "%s more sleep", "%s less sleep", _night("duration_min"), True),
    OutcomeDef("onset_min", "Sleep onset", "min", "down", 10, "falling asleep %s later", "falling asleep %s earlier",
               _night("onset_min"), True),
    OutcomeDef("hrv_ms", "Overnight HRV", "%", "up", 3, "overnight HRV %s higher", "overnight HRV %s lower",
               _night("hrv_ms"), True),
    OutcomeDef("resting_hr", "Resting heart rate", "bpm", "down", 1, "resting heart rate %s higher",
               "resting heart rate %s lower", _night("resting_hr"), True),
    OutcomeDef("steps", "Steps", "steps", "up", 800, "%s more steps", "%s fewer steps", _steps, False, "activity"),
    OutcomeDef("screen_minutes", "Screen time", "min", "down", 15, "%s more screen time", "%s less screen time",
               _metric("screen.minutes"), False, "phone"),
    OutcomeDef("pickups", "Phone pickups", "count", "down", 5, "%s more phone pickups", "%s fewer phone pickups",
               _metric("screen.pickups"), False, "phone"),
    OutcomeDef("day_hr", "Daytime heart rate", "bpm", "down", 2, "daytime heart rate %s higher",
               "daytime heart rate %s lower", daytime_hr, False, "heart", True),
)}
NIGHT = ("score", "duration_min", "onset_min", "hrv_ms", "resting_hr")
NIGHT_AND_DAY = NIGHT + ("day_hr",)


# --------------------------------------------------------------------------- #
# Causes
# --------------------------------------------------------------------------- #
def _onset_offset(ds: Dataset, d: date) -> Optional[float]:
    """Minutes between the night's sleep onset and the median of the nights before it."""
    v = bl.night_metric(ds.night(d), "onset_min")
    if v is None:
        return None
    prior = [bl.night_metric(ds.night(d - timedelta(days=k)), "onset_min") for k in range(1, ONSET_HISTORY + 1)]
    prior = [p for p in prior if p is not None]
    return abs(v - statistics.median(prior)) if len(prior) >= 5 else None


def _sleep_debt(ds: Dataset, d: date) -> Optional[float]:
    """Minutes short of the sleep need over the nights before night ``d`` (None unless every one was recorded)."""
    need = float(ds.persona.sleep_need_min)
    durs = [bl.night_metric(ds.night(d - timedelta(days=k)), "duration_min") for k in range(1, SLEEP_DEBT_NIGHTS + 1)]
    if any(v is None for v in durs):
        return None
    return sum(max(0.0, need - v) for v in durs)


def _last_night(ds: Dataset, d: date) -> Optional[float]:
    return bl.night_metric(ds.night(d - timedelta(days=1)), "duration_min")


def _has_calendar(ds: Dataset) -> bool:
    """A calendar is connected: events on a few different days (one stray event says nothing about the others)."""
    return len({e.start.date() for e in ds.events}) >= MIN_CALENDAR_DAYS


def _calendar(get: Callable) -> Callable[[Dataset, date], Optional[float]]:
    """A calendar value for day ``d``; None when no calendar is connected (0 meetings would then mean nothing)."""
    return lambda ds, d: float(get(day_features(ds, d))) if _has_calendar(ds) else None


def _workouts(ds: Dataset, d: date) -> Optional[List[Tuple[str, datetime]]]:
    """(lower-case kind and title, end) of each workout on day ``d``; None when no workout was ever recorded."""
    if not (any(a.workouts for a in ds.activity) or any(e.type == "workout" for e in ds.events)):
        return None
    a = ds.activity_on(d)
    out = [(w.kind.lower(), w.end) for w in (a.workouts if a else [])]
    out += [(" ".join(filter(None, (e.title, e.location_hint))).lower(), e.end) for e in ds.events_on(d) if e.type == "workout"]
    return out


def _workout(pred: Callable[[str, datetime], bool]) -> Callable[[Dataset, date], Optional[float]]:
    def f(ds: Dataset, d: date) -> Optional[float]:
        ws = _workouts(ds, d)
        return None if ws is None else float(any(pred(k, end) for k, end in ws))
    return f


def _media_days(ds: Dataset) -> Optional[Tuple[date, date]]:
    """First and last day of the imported listening history, or None without one."""
    if not ds.media:
        return None
    days = [m.start.date() for m in ds.media]
    return min(days), max(days)


def _media(get: Callable[[List], float], kinds: Tuple[str, ...] = ("music", "podcast")) -> Callable[[Dataset, date], Optional[float]]:
    """A value from day ``d``'s plays of ``kinds``; None outside the span the history covers."""
    def f(ds: Dataset, d: date) -> Optional[float]:
        span = _media_days(ds)
        if span is None or not (span[0] <= d <= span[1]):
            return None
        return float(get([m for m in ds.media_on(d) if m.kind in kinds]))
    return f


def _late(plays: List) -> float:
    return sum(m.minutes for m in plays if m.start.hour >= LATE_HOUR)


@dataclass(frozen=True)
class CauseDef:
    key: str
    title: str
    value: Callable[[Dataset, date], Optional[float]]
    split: str                                 # "low": value <= threshold; "high": value >= threshold
    threshold: Callable[[List[float]], float]  # from the person's own values
    unit: str                                  # of the value, for the description
    describe: str                              # "days under %s steps", filled with the formatted threshold
    lead: str                                  # sentence start; %d = days with, %s = describe
    outcomes: Tuple[str, ...]
    min_days: int = MIN_DAYS
    source: str = "activity"                   # which data the cause comes from (see SOURCES)
    expected: Optional[str] = None             # the direction sleep research expects ("hurt"/"helped"); None: no clear view
    others: Optional[str] = None               # what the days without it are ("days with Study session"); None: days/nights
    hints: bool = True                         # False: only strong links count (causes picked from many candidates)


def _q(p: float, floor: float = 0.0) -> Callable[[List[float]], float]:
    def f(vals: List[float]) -> float:
        s = sorted(vals)
        return max(floor, s[min(len(s) - 1, int(p * len(s)))])
    return f


def _fixed(x: float) -> Callable[[List[float]], float]:
    return lambda vals: x


CAUSES: Tuple[CauseDef, ...] = (
    CauseDef("low_steps", "Low-step days", _steps, "low", _q(1 / 3), "steps", "days under %s steps",
             "On the nights after your %d %s", NIGHT, expected="hurt"),
    CauseDef("active_days", "Active days", _steps, "high", _q(2 / 3), "steps", "days over %s steps",
             "On the nights after your %d %s", NIGHT, expected="helped"),
    CauseDef("workout_days", "Workout days", _workout(lambda k, end: True), "high", _fixed(1.0), "count",
             "days with a workout", "On the nights after your %d %s", NIGHT, source="exercise", expected="helped"),
    CauseDef("gym_days", "Gym sessions", _workout(lambda k, end: any(w in k for w in GYM_WORDS)), "high", _fixed(1.0),
             "count", "gym days", "On the nights after your %d %s", NIGHT, source="exercise"),
    CauseDef("cardio_days", "Runs, rides and swims", _workout(lambda k, end: any(w in k for w in CARDIO_WORDS)), "high",
             _fixed(1.0), "count", "days with a run, ride, walk or swim", "On the nights after your %d %s", NIGHT,
             source="exercise", expected="helped"),
    CauseDef("late_workouts", "Late workouts", _workout(lambda k, end: end.hour >= 20), "high", _fixed(1.0), "count",
             "days with a workout ending after 20:00", "On the nights after your %d %s", NIGHT, source="exercise"),
    CauseDef("busy_days", "Meeting-heavy days", _calendar(lambda f: f.meeting_minutes), "high", _q(2 / 3, 120), "min",
             "days with %s or more in meetings", "On the nights after your %d %s", NIGHT_AND_DAY, source="calendar",
             expected="hurt"),
    CauseDef("late_meetings", "Late meetings", _calendar(lambda f: f.late_meeting_hours > 0), "high", _fixed(1.0),
             "count", "days with a meeting ending after 18:00", "On the nights after your %d %s", NIGHT_AND_DAY,
             source="calendar", expected="hurt"),
    CauseDef("back_to_back_days", "Back-to-back meetings", _calendar(lambda f: f.max_b2b_run >= 3), "high", _fixed(1.0),
             "count", "days with three or more meetings in a row", "On the nights after your %d %s", NIGHT_AND_DAY,
             source="calendar", expected="hurt"),
    CauseDef("social_evenings", "Social evenings", _calendar(lambda f: f.evening_social), "high", _fixed(1.0), "count",
             "evenings out ending after 20:30", "On the nights after your %d %s", NIGHT, source="calendar"),
    CauseDef("early_starts", "Early starts", _calendar(lambda f: f.early_start), "high", _fixed(1.0), "count",
             "days starting before 07:30", "On the nights after your %d %s", NIGHT_AND_DAY, source="calendar",
             expected="hurt"),
    CauseDef("big_listening", "Big listening days", _media(lambda ps: sum(m.minutes for m in ps)), "high",
             _q(2 / 3, 60), "min", "days with %s or more of music and podcasts", "On the nights after your %d %s",
             NIGHT_AND_DAY, source="music"),
    CauseDef("late_listening", "Late-night listening", _media(_late), "high", _q(2 / 3, 15), "min",
             "evenings with %s or more of listening after 22:00", "On the nights after your %d %s", NIGHT,
             source="music"),
    CauseDef("podcast_days", "Podcast days", _media(lambda ps: sum(m.minutes for m in ps if m.kind == "podcast") >= 10),
             "high", _fixed(1.0), "count", "days with a podcast", "On the nights after your %d %s", NIGHT_AND_DAY,
             source="music"),
    CauseDef("late_streaming", "Late-evening streaming", _media(lambda ps: _late(ps) >= 30, ("video",)), "high",
             _fixed(1.0), "count", "evenings streaming after 22:00", "On the nights after your %d %s", NIGHT,
             source="streaming", expected="hurt"),
    CauseDef("late_screen", "Late-evening phone use", _metric("screen.late_minutes"), "high", _q(2 / 3, 20), "min",
             "evenings with %s or more on the phone after 22:00", "On the nights after your %d %s", NIGHT, source="phone",
             expected="hurt"),
    CauseDef("heavy_screen", "Heavy phone days", _metric("screen.minutes"), "high", _q(2 / 3, 60), "min",
             "days with %s or more of screen time", "On the nights after your %d %s", NIGHT_AND_DAY, source="phone",
             expected="hurt"),
    CauseDef("many_pickups", "Many phone pickups", _metric("screen.pickups"), "high", _q(2 / 3, 10), "count",
             "days with %s or more phone pickups", "On the nights after your %d %s", NIGHT_AND_DAY, source="phone",
             expected="hurt"),
    CauseDef("off_rhythm", "Off-rhythm bedtimes", _onset_offset, "high", _fixed(OFF_RHYTHM_MIN), "min",
             "nights you fell asleep %s or more away from your usual time", "On your %d %s",
             ("score", "duration_min", "hrv_ms", "resting_hr"), source="sleep", expected="hurt"),
    CauseDef("sleep_debt", "Built-up sleep debt", _sleep_debt, "high", _fixed(SLEEP_DEBT_MIN), "min",
             "nights after 3 nights adding up to %s or more short of your sleep need", "On your %d %s",
             ("hrv_ms", "resting_hr"), source="sleep", expected="hurt"),
    CauseDef("short_night", "Short nights", _last_night, "low", _q(1 / 3), "min", "nights under %s of sleep",
             "On the days after your %d %s", ("steps", "screen_minutes", "pickups", "day_hr"), source="sleep"),
    CauseDef("alcohol", "Evenings with alcohol", _metric("intake.alcohol_units"), "high", _fixed(1.0), "units",
             "evenings with alcohol", "On the nights after your %d %s", NIGHT, CHECKIN_MIN_DAYS, source="check-in",
             expected="hurt"),
    CauseDef("more_coffee", "More coffee than usual", _metric("intake.coffee_cups"), "high", _q(2 / 3, 1), "cups",
             "days with %s or more cups of coffee", "On the nights after your %d %s",
             ("score", "duration_min", "onset_min", "hrv_ms", "day_hr"), CHECKIN_MIN_DAYS, source="check-in",
             expected="hurt"),
)
CAUSES_BY_KEY = {c.key: c for c in CAUSES}
SOURCE_LABELS = {"sleep": "Sleep", "activity": "Steps", "exercise": "Workouts", "calendar": "Calendar", "music": "Music",
                 "streaming": "Streaming", "phone": "Phone", "check-in": "Check-in", "heart": "Heart rate"}


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")[:40] or "x"


def artist_causes(ds: Dataset, days: Sequence[date]) -> List[CauseDef]:
    """The most-played artists and podcasts as causes of their own: 'days you listened to Radiohead'."""
    if _media_days(ds) is None:
        return []
    n_days: Dict[str, int] = {}
    for d in days:
        played: Dict[str, float] = {}
        for m in ds.media_on(d):
            if m.creator and m.kind in ("music", "podcast"):
                played[m.creator] = played.get(m.creator, 0.0) + m.minutes
        for creator, minutes in played.items():
            if minutes >= MIN_ARTIST_MIN:
                n_days[creator] = n_days.get(creator, 0) + 1
    top = sorted((c for c, n in n_days.items() if n >= MIN_GROUP), key=lambda c: -n_days[c])[:MAX_ARTISTS]

    def listened(creator: str) -> Callable[[List], float]:
        return lambda ps: float(sum(m.minutes for m in ps if m.creator == creator) >= MIN_ARTIST_MIN)
    return [CauseDef("artist_" + _slug(c), "Days with " + c, _media(listened(c)), "high", _fixed(1.0), "count",
                     "days you listened to " + c, "On the nights after your %d %s", NIGHT_AND_DAY, source="music")
            for c in top]


def _activity_key(e) -> str:
    """Events that are the same activity: one recurring series, or one title used on many days ("Study session")."""
    return e.recurring_key or "title:" + " ".join(e.title.lower().split())


def _activity_windows(ds: Dataset, d: date, key: str) -> List[Tuple[datetime, datetime]]:
    return [(e.start, e.end) for e in ds.events_on(d) if e.start.date() == d and _activity_key(e) == key]


def _media_name(m) -> Optional[str]:
    """The artist or podcast, or for a show the part before "Show: Episode"."""
    return m.creator or (m.title.split(":")[0].strip() if m.kind == "video" and m.title else None)


def _paired_minutes(ds: Dataset, d: date, key: str) -> Dict[Tuple[str, str], float]:
    """{(media name, "during" | "after"): minutes} for activity ``key`` on day ``d``."""
    windows = _activity_windows(ds, d, key)
    out: Dict[Tuple[str, str], float] = {}
    if not windows:
        return out
    last_end = max(e for _, e in windows)
    for m in ds.media_on(d):
        name = _media_name(m)
        if not name:
            continue
        end = m.start + timedelta(minutes=m.minutes)
        during = sum(max(0.0, (min(end, e) - max(m.start, s)).total_seconds() / 60.0) for s, e in windows)
        if during >= MIN_ARTIST_MIN:
            out[(name, "during")] = out.get((name, "during"), 0.0) + during
        elif last_end <= m.start < last_end + timedelta(hours=AFTER_HOURS):
            out[(name, "after")] = out.get((name, "after"), 0.0) + m.minutes
    return out


def activity_hr_outcome(key: str, title: str) -> str:
    """Registers (once) and returns the outcome "heart rate during <activity>"."""
    okey = "hr_during_" + _slug(title)
    if okey not in OUTCOMES:
        def get(ds: Dataset, d: date) -> Optional[float]:
            hr = ds.hr(d)
            if hr is None:
                return None
            vals = [b for s, e in _activity_windows(ds, d, key)
                    for b in hr.bpm[s.hour * 60 + s.minute:(e.hour * 60 + e.minute) if e.date() == d else 1440]
                    if b is not None]
            return statistics.fmean(vals) if len(vals) >= ACTIVITY_HR_MIN_MINUTES else None
        OUTCOMES[okey] = OutcomeDef(okey, "Heart rate during " + title, "bpm", "down", 2,
                                    "heart rate during %s %%s higher" % title, "heart rate during %s %%s lower" % title,
                                    get, False, "heart", True)
    return okey


def activity_pickups_outcome(key: str, title: str) -> str:
    """Registers (once) and returns the outcome "phone pickups an hour during <activity>": the unlocks inside the
    activity's calendar windows, per hour of them, so a longer session does not count as more pickups."""
    okey = "pickups_during_" + _slug(title)
    if okey not in OUTCOMES:
        def get(ds: Dataset, d: date) -> Optional[float]:
            # only days the phone reported in full: no daily total means no screen data that day, not zero pickups
            if ds.metric_on(d, "screen.pickups") is None:
                return None
            windows = _activity_windows(ds, d, key)
            hours = sum((e - s).total_seconds() for s, e in windows) / 3600.0
            if hours * 60 < ACTIVITY_PHONE_MIN_MINUTES:
                return None
            return sum(1 for t in ds.unlocks_on(d) if any(s <= t < e for s, e in windows)) / hours
        OUTCOMES[okey] = OutcomeDef(okey, "Phone pickups during " + title, "per hour", "down", 1,
                                    "%%s more phone pickups an hour during %s" % title,
                                    "%%s fewer phone pickups an hour during %s" % title, get, False, "phone")
    return okey


def pair_causes(ds: Dataset, days: Sequence[date]) -> List[CauseDef]:
    """Media played during or after a calendar activity, compared with the same activity without it: "Ludovico Einaudi
    during Study session" (against pickups and heart rate during it, and the day's screen time), "Breaking Bad after
    Tennis practice" (against the night after). Only days with the activity are compared, so the activity itself is not what differs. Picked
    from many possible pairs, so only strong links count."""
    if _media_days(ds) is None or not _has_calendar(ds):
        return []
    act_days: Dict[str, set] = {}
    titles: Dict[str, Dict[str, int]] = {}
    for d in days:
        for e in ds.events_on(d):
            k = _activity_key(e)
            act_days.setdefault(k, set()).add(d)
            t = titles.setdefault(k, {})
            t[e.title] = t.get(e.title, 0) + 1
    acts = sorted((k for k, on in act_days.items() if len(on) >= 2 * MIN_GROUP), key=lambda k: -len(act_days[k]))
    pairs: Dict[Tuple[str, str, str], int] = {}
    for k in acts[:PAIR_ACTIVITIES]:
        for d in act_days[k]:
            for (name, rel), minutes in _paired_minutes(ds, d, k).items():
                if minutes >= MIN_ARTIST_MIN:
                    pairs[(k, name, rel)] = pairs.get((k, name, rel), 0) + 1
    top = sorted((p for p, n in pairs.items() if n >= MIN_GROUP and len(act_days[p[0]]) - n >= MIN_GROUP),
                 key=lambda p: -pairs[p])[:MAX_PAIRS]

    def value(k: str, name: str, rel: str) -> Callable[[Dataset, date], Optional[float]]:
        def f(ds: Dataset, d: date) -> Optional[float]:
            span = _media_days(ds)
            if span is None or not (span[0] <= d <= span[1]) or not _activity_windows(ds, d, k):
                return None
            return float(_paired_minutes(ds, d, k).get((name, rel), 0.0) >= MIN_ARTIST_MIN)
        return f
    out = []
    for k, name, rel in top:
        title = max(titles[k], key=titles[k].get)
        video = any(_media_name(m) == name and m.kind == "video" for m in ds.media)
        verb = "watched" if video else "listened to"
        if rel == "during":
            # pickups inside the activity when the phone sent when each unlock happened; else only the day's total
            pickups = activity_pickups_outcome(k, title) if ds.unlocks else "pickups"
            outcomes = (pickups, "screen_minutes", activity_hr_outcome(k, title))
            lead = "On the %d days you %s"
        else:
            outcomes = NIGHT
            lead = "On the nights after the %d days you %s"
        out.append(CauseDef("pair_%s_%s_%s" % (_slug(name), rel, _slug(title)), "%s %s %s" % (name, rel, title),
                            value(k, name, rel), "high", _fixed(1.0), "count",
                            "%s %s %s %s" % (verb, name, rel, title), lead, outcomes, 2 * MIN_GROUP,
                            source="streaming" if video else "music", others="days with " + title, hints=False))
    return out


def series_causes(ds: Dataset, days: Sequence[date]) -> List[CauseDef]:
    """The most frequent recurring calendar series as causes of their own: 'days with Statistics lecture'. Their
    titles reach the report model (a decision for series only: one-off titles, places and guests never do)."""
    if not _has_calendar(ds):
        return []
    n_days: Dict[str, set] = {}
    titles: Dict[str, Dict[str, int]] = {}
    for d in days:
        for e in ds.events_on(d):
            if e.recurring_key and e.type != "workout":   # workouts have causes of their own
                n_days.setdefault(e.recurring_key, set()).add(d)
                t = titles.setdefault(e.recurring_key, {})
                t[e.title] = t.get(e.title, 0) + 1
    top = sorted((k for k, on in n_days.items() if len(on) >= MIN_GROUP), key=lambda k: -len(n_days[k]))[:MAX_SERIES]

    def value(key: str) -> Callable[[Dataset, date], Optional[float]]:
        return lambda ds, d: float(any(e.recurring_key == key for e in ds.events_on(d))) if _has_calendar(ds) else None
    out = []
    for k in top:
        title = max(titles[k], key=titles[k].get)
        out.append(CauseDef("series_" + _slug(title), "Days with " + title, value(k), "high", _fixed(1.0), "count",
                            "days with " + title, "On the nights after your %d %s", NIGHT_AND_DAY, source="calendar"))
    return out


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
@dataclass
class OutcomeEffect:
    key: str
    label: str
    unit: str
    good: str
    n_with: int
    n_without: int
    mean_with: Optional[float]
    mean_without: Optional[float]
    effect: Optional[float]                    # with - without, stratified (HRV in % of the without mean)
    ci_low: Optional[float]
    ci_high: Optional[float]
    confidence: str
    tier: Optional[str]                        # "strong" | "hint" | None (not reported)
    strength: float                            # conservative effect in standard deviations (ranking only)

    @property
    def reportable(self) -> bool:
        return self.tier is not None

    @property
    def direction(self) -> str:
        if self.effect is None or self.effect == 0:
            return "neutral"
        return "helped" if (self.effect > 0) == (self.good == "up") else "hurt"


@dataclass
class LifestylePattern:
    key: str
    title: str
    description: str                           # "days under 6 500 steps"
    threshold: float
    n_with: int                                # days the cause was measured and active
    n_without: int
    outcomes: List[OutcomeEffect] = field(default_factory=list)
    rank_score: float = 0.0
    cause: Optional[CauseDef] = None           # its definition (artist causes are not in CAUSES_BY_KEY)

    @property
    def cause_def(self) -> CauseDef:
        return self.cause or CAUSES_BY_KEY[self.key]

    @property
    def sources(self) -> List[str]:
        """The data sources the link connects, cause first: ['music', 'sleep']."""
        out = [self.cause_def.source]
        for o in self.reportable:
            if OUTCOMES[o.key].source not in out:
                out.append(OUTCOMES[o.key].source)
        return out

    @property
    def cross_source(self) -> bool:
        return len(self.sources) > 1

    @property
    def reportable(self) -> List[OutcomeEffect]:
        return [o for o in self.outcomes if o.reportable]

    @property
    def primary(self) -> Optional[OutcomeEffect]:
        r = self.reportable
        return max(r, key=lambda o: (o.tier == "strong", o.strength)) if r else None

    @property
    def direction(self) -> str:
        p = self.primary
        return p.direction if p else "neutral"

    @property
    def confidence(self) -> str:
        p = self.primary
        return p.confidence if p else "low"

    @property
    def against_research(self) -> bool:
        """It goes the other way than sleep research expects (more late phone use, better sleep): most likely
        something else is going on, such as those days being free days you sleep in after."""
        return self.cause_def.expected is not None and self.direction not in ("neutral", self.cause_def.expected)

    @property
    def hint(self) -> bool:
        """Only an early hint: no outcome is strong."""
        return bool(self.reportable) and all(o.tier == "hint" for o in self.reportable)

    def detail(self) -> str:
        """One or two sentences with the numbers, for the report input. Strong outcomes only, unless all are hints."""
        cause = self.cause_def
        rep = sorted((o for o in self.reportable if self.hint or o.tier == "strong"), key=lambda o: -o.strength)
        if not rep:
            return ""

        def joined(os: List[OutcomeEffect]) -> str:
            parts = [(OUTCOMES[o.key].more if o.effect > 0 else OUTCOMES[o.key].less) % fmt(abs(o.effect), o.unit) for o in os]
            return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        after = [o for o in rep if not OUTCOMES[o.key].same_day]
        same = [o for o in rep if OUTCOMES[o.key].same_day]
        if after:
            text = "%s: %s" % (cause.lead % (self.n_with, self.description), joined(after))
            if same:
                text += ", with a %s during those days" % joined(same)
            other = "nights" if OUTCOMES[after[0].key].night else "days"
        else:
            text = "On your %d %s: a %s" % (self.n_with, self.description, joined(same))
            other = "days"
        text += ", compared with your other %d %s." % (self.n_without, cause.others or other)
        if self.hint:
            text += " An early hint: the difference is small or rests on few days, so it may not hold."
        return text


def fmt(v: float, unit: str) -> str:
    if unit == "min":
        m = int(round(v))
        if m < 60:
            return "%d min" % m
        return "%d h" % (m // 60) if m % 60 == 0 else "%d h %02d min" % (m // 60, m % 60)
    if unit == "steps":
        return "{:,}".format(int(round(v / 100.0) * 100)).replace(",", " ")
    if unit == "%":
        return "%d%%" % round(v)
    if unit == "bpm":
        return ("%.1f" % v).rstrip("0").rstrip(".") + " bpm"
    if unit == "per hour":
        return ("%.1f" % v).rstrip("0").rstrip(".")
    return "%d" % round(v)


def _threshold_text(c: CauseDef, t: float) -> str:
    return fmt(t, c.unit)


def _round_threshold(c: CauseDef, t: float) -> float:
    if c.unit == "steps":
        return float(round(t / 100.0) * 100)
    if c.unit == "min":
        return float(round(t / 5.0) * 5)
    return float(round(t))


def is_active(c: CauseDef, value: Optional[float], threshold: float) -> Optional[bool]:
    if value is None:
        return None
    return value <= threshold if c.split == "low" else value >= threshold


def active_on(ds: Dataset, p: LifestylePattern, d: date) -> bool:
    """Whether pattern ``p``'s cause happened on day ``d`` (for night causes: night ``d``)."""
    c = p.cause_def
    return bool(is_active(c, c.value(ds, d), p.threshold))


def _bootstrap(groups: Dict[int, Tuple[List[float], List[float]]], rng: random.Random, b: int) -> List[float]:
    """Sorted resampled effects (``habits.bootstrap_effect_ci`` gives one interval; here two levels are read)."""
    usable = {s: (w, wo) for s, (w, wo) in groups.items() if w and wo}
    draws = []
    for _ in range(b if usable else 0):
        g = {s: ([w[rng.randrange(len(w))] for _ in w], [wo[rng.randrange(len(wo))] for _ in wo]) for s, (w, wo) in usable.items()}
        e = stratified_effect(g)
        if e is not None:
            draws.append(e)
    return sorted(draws)


def _interval(draws: List[float], level: float) -> Tuple[Optional[float], Optional[float]]:
    if len(draws) < 20:
        return None, None
    a = (1.0 - level) / 2.0
    return draws[int(a * (len(draws) - 1))], draws[int((1.0 - a) * (len(draws) - 1))]


def _outcome_effect(ds: Dataset, od: OutcomeDef, active: Dict[date, bool], rng: random.Random, bootstrap: int) -> Optional[OutcomeEffect]:
    groups: Dict[int, Tuple[List[float], List[float]]] = {0: ([], []), 1: ([], [])}
    for d, on in active.items():
        y = od.get(ds, d)
        if y is None or not math.isfinite(y):
            continue
        s = int(is_weekend_night(d)) if od.night else int(d.weekday() >= 5)
        (groups[s][0] if on else groups[s][1]).append(y)
    n_with = sum(len(w) for w, _ in groups.values())
    n_without = sum(len(wo) for _, wo in groups.values())
    if min(n_with, n_without) < MIN_GROUP:
        return None
    effect = stratified_effect(groups)
    if effect is None:
        return None
    draws = _bootstrap(groups, rng, bootstrap)
    lo, hi = _interval(draws, 0.95)
    hlo, hhi = _interval(draws, HINT_LEVEL)
    all_y = [v for w, wo in groups.values() for v in w + wo]
    mean_with = statistics.fmean([v for w, _ in groups.values() for v in w])
    mean_without = statistics.fmean([v for _, wo in groups.values() for v in wo])
    sd = statistics.pstdev(all_y) or 1.0
    excludes = lo is not None and hi is not None and (lo > 0 or hi < 0)
    hint_excludes = hlo is not None and hhi is not None and (hlo > 0 or hhi < 0)
    strength = (min(abs(lo), abs(hi)) / sd) if excludes else (min(abs(hlo), abs(hhi)) / sd if hint_excludes else 0.0)
    if od.unit == "%":                         # HRV: ms differ by device, so say it in % of the person's usual
        if not mean_without:
            return None
        scale = 100.0 / mean_without
        effect, lo, hi = effect * scale, (lo * scale if lo is not None else None), (hi * scale if hi is not None else None)
    conf = confidence_for(lo, hi, n_with, n_without)
    tier = None
    if abs(effect) >= od.min_effect:
        if excludes and conf != "low":
            tier = "strong"
        elif hint_excludes:
            tier, conf = "hint", "low"
    r = lambda x: None if x is None else round(x, 1)
    return OutcomeEffect(key=od.key, label=od.label, unit=od.unit, good=od.good, n_with=n_with, n_without=n_without,
                         mean_with=r(mean_with), mean_without=r(mean_without), effect=r(effect), ci_low=r(lo), ci_high=r(hi),
                         confidence=conf, tier=tier, strength=round(strength, 3))


def lifestyle_patterns(ds: Dataset, upto: date, history_days: Optional[int] = None, bootstrap: int = BOOTSTRAP,
                       seed: int = 0, cache: Optional[dict] = None) -> List[LifestylePattern]:
    """Every cause with enough data, best first. Uses days strictly before ``upto`` (and the nights after them)."""
    key = ("lifestyle", upto, history_days, bootstrap)
    if cache is not None and key in cache:
        return cache[key]
    window = min(history_days or HISTORY_DAYS, HISTORY_DAYS)
    start = max(ds.start, upto - timedelta(days=window))
    days = [start + timedelta(days=k) for k in range((upto - start).days)]
    rng = random.Random(seed)
    out: List[LifestylePattern] = []
    for c in CAUSES + tuple(artist_causes(ds, days) + pair_causes(ds, days) + series_causes(ds, days)):
        values = {d: c.value(ds, d) for d in days}
        known = [v for v in values.values() if v is not None]
        if len(known) < c.min_days:
            continue
        t = _round_threshold(c, c.threshold(known))
        active = {d: bool(is_active(c, v, t)) for d, v in values.items() if v is not None}
        n_with = sum(1 for on in active.values() if on)
        if min(n_with, len(active) - n_with) < MIN_GROUP:
            continue
        effects = [e for e in (_outcome_effect(ds, OUTCOMES[o], active, rng, bootstrap) for o in c.outcomes) if e is not None]
        for e in effects:
            if e.tier == "hint" and not c.hints:
                e.tier = None
        if not effects:
            continue
        desc = c.describe % _threshold_text(c, t) if "%s" in c.describe else c.describe
        p = LifestylePattern(key=c.key, title=c.title, description=desc, threshold=t,
                             n_with=n_with, n_without=len(active) - n_with, outcomes=effects, cause=c)
        prim = p.primary
        p.rank_score = round(prim.strength * CONF_WEIGHT[prim.confidence], 3) if prim else 0.0
        out.append(p)
    out.sort(key=lambda p: -p.rank_score)
    if cache is not None:
        cache[key] = out
    return out


def day_tags(ds: Dataset, d: date, patterns: Sequence[LifestylePattern]) -> List[str]:
    """Chips for a weekly report's day: 'low-step day (3 900)', 'late phone use (45 min)'."""
    tags: List[str] = []
    by_key = {p.key: p for p in patterns}
    steps = _steps(ds, d)
    for k, label in (("low_steps", "low-step day"), ("active_days", "active day")):
        p = by_key.get(k)
        if p is not None and steps is not None and active_on(ds, p, d):
            tags.append("%s (%s steps)" % (label, fmt(steps, "steps")))
    for k, key, text in (("alcohol", "intake.alcohol_units", "alcohol (%s units)"), ("more_coffee", "intake.coffee_cups", "%s cups of coffee")):
        v, p = ds.metric_on(d, key), by_key.get(k)
        if p is not None and v is not None and active_on(ds, p, d):
            tags.append(text % ("%g" % v))
    late = ds.metric_on(d, "screen.late_minutes")
    p = by_key.get("late_screen")
    if p is not None and late is not None and active_on(ds, p, d):
        tags.append("phone after 22:00 (%s)" % fmt(late, "min"))
    return tags + media_tags(ds, d)


def media_tags(ds: Dataset, d: date) -> List[str]:
    """What day ``d`` sounded like: '1 h 20 min of music, mostly Radiohead', 'podcast: Sommar i P1'."""
    tags: List[str] = []
    plays = ds.media_on(d)
    music = [m for m in plays if m.kind == "music"]
    if music:
        by: Dict[str, float] = {}
        for m in music:
            if m.creator:
                by[m.creator] = by.get(m.creator, 0.0) + m.minutes
        top = max(by, key=by.get) if by else None
        tags.append("%s of music%s" % (fmt(sum(m.minutes for m in music), "min"), (", mostly " + top) if top else ""))
    shows = sorted({m.creator or m.title for m in plays if m.kind == "podcast"})
    if shows:
        tags.append("podcast: " + ", ".join(shows[:2]))
    video = [m for m in plays if m.kind == "video"]
    if video:
        tags.append("%s of streaming%s" % (fmt(sum(m.minutes for m in video), "min"),
                                           " after 22:00" if any(m.start.hour >= LATE_HOUR for m in video) else ""))
    if _late(music + [m for m in plays if m.kind == "podcast"]) >= 15:
        tags.append("listening after 22:00")
    return tags
