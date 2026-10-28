"""Build the ``ReportInput`` a generated report is written from (see ``stressless.reports``).

Everything here is computed by the engine; the model only puts it into words and picks which links are worth telling.
Only numbers, code-written labels, dates, music names (artists, podcasts, shows) and the titles of recurring calendar
activities that became a link (a series, or a title used on many days: "Statistics lecture", "Study session") go in: no
other event titles, places, people, ids or clock times, because the input is sent to the model as is.

The heart of a report is its links (``Pattern``s from ``lifestyle``): how one data source goes with another in the
person's own history. Links whose cause happened in the period come first, links between two sources before links
within one, and a few strong ones from the background are added so the model has something to choose from.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Dict, List, Optional, Set

from ..models import FACTOR_LABELS
from ..reports import Metric, Pattern, DayPoint, ReportInput
from . import baselines as bl
from .features import day_features, describe_features
from .lifestyle import LifestylePattern, _has_calendar, active_on, day_tags, daytime_hr

HISTORY = 28                                   # nights or days behind a "usual" value
MAX_LIFESTYLE = 6                              # links whose cause happened in the period
MAX_BACKGROUND = 2                             # strongest other links, for context
# Lifestyle links that say the same as one of the daily model's causes (that one is kept: it explains last night)
SAME_AS_CAUSE = {"busy_days": "meetings_over_3", "back_to_back_days": "b2b_over_2", "late_meetings": "late_meeting_hours",
                 "social_evenings": "evening_social", "early_starts": "early_start", "late_workouts": "workout_late"}
# Phone-sync screen time (daily_metrics): key, label, unit; lower is better for all three
SCREEN_DEFS = (("screen.minutes", "Screen time", "min"), ("screen.late_minutes", "Screen time after 22:00", "min"),
               ("screen.pickups", "Phone pickups", "count"))
# Manual check-ins (daily_metrics, source manual): key, label, unit, good direction
CHECKIN_DEFS = (("intake.coffee_cups", "Coffee", "cups", "none"), ("intake.alcohol_units", "Alcohol", "units", "down"))

# Engine recovery metric -> report metric key
RECOVERY_KEYS = {"hrv_ms": "hrv.overnight", "resting_hr": "hr.resting", "wrist_temp_dev": "temp.wrist",
                 "resp_rate": "resp.rate", "spo2": "spo2.overnight"}
# Per-night sleep values: engine key, report key, label, unit, good direction
SLEEP_DEFS = (("duration_min", "sleep.duration", "Time asleep", "min", "up"),
              ("awake_min", "sleep.awake", "Time awake in the night", "min", "down"),
              ("interruptions", "sleep.interruptions", "Times woken", "count", "down"))
WEEK_NIGHT_DEFS = (("score", "sleep.score", "Sleep score", "points", "up"),) + SLEEP_DEFS + (
    ("hrv_ms", "hrv.overnight", "Overnight HRV", "ms", "up"), ("resting_hr", "hr.resting", "Resting heart rate", "bpm", "down"))


def _r(x: Optional[float], nd: int = 1) -> Optional[float]:
    return None if x is None else round(float(x), nd)


def _metric(key: str, label: str, source: str, unit: str, value: Optional[float], history: List[float], good: str) -> Metric:
    """A metric next to the median of ``history``, with a status from the robust z-score."""
    med, scale = bl.robust_baseline(history)
    zv = bl.z(value, {"median": med, "scale": scale})
    delta = (value - med) if (value is not None and med is not None) else None
    return Metric(key=key, label=label, source=source, value=_r(value), unit=unit, baseline=_r(med), delta=_r(delta),
                  status=bl._status(zv, good))


def _scrub(text: str, titles: List[str]) -> str:
    """Engine texts can name calendar events ("Board dinner ran 2 h past 18:00"); the model never sees event names."""
    for t in sorted(titles, key=len, reverse=True):
        if t:
            text = text.replace(t, "an event")
    return text[:1].upper() + text[1:]


def _days_before(d: date, n: int) -> List[date]:
    return [d - timedelta(days=k) for k in range(n, 0, -1)]


def _steps(ds, d: date) -> Optional[float]:
    a = ds.activity_on(d)
    return float(a.steps) if a is not None else None


def _mean(vals: List[float]) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def _day_metric(ds, d: date, key: str) -> Optional[float]:
    return ds.metric_on(d, key)


def _lifestyle_pattern(p: LifestylePattern, happened: int) -> Pattern:
    """A lifestyle pattern as report input: its strongest outcome is the effect, the others are in the detail."""
    o = p.primary
    return Pattern(key="pattern." + p.key, title=p.title, detail=p.detail(), direction=p.direction, effect=o.effect,
                   unit=o.unit, n=o.n_with, confidence=o.confidence, outcome=o.label, effect_low=o.ci_low,
                   effect_high=o.ci_high, n_without=o.n_without, sources=p.sources, happened=happened,
                   against_research=p.against_research)


def _links(lifestyle: List[LifestylePattern], happened: Dict[str, int], skip: Set[str]) -> List[Pattern]:
    """Links for a report: those that happened in the period, then the strongest others; cross-source ones first.
    An early hint that goes against sleep research is most likely noise, so it is left out."""
    usable = [p for p in lifestyle if p.primary is not None and p.key not in skip and not (p.hint and p.against_research)]
    order = lambda p: (not p.cross_source, -p.rank_score)
    now = sorted((p for p in usable if happened.get(p.key)), key=order)[:MAX_LIFESTYLE]
    rest = sorted((p for p in usable if not happened.get(p.key) and p.cross_source and not p.hint), key=order)[:MAX_BACKGROUND]
    return [_lifestyle_pattern(p, happened.get(p.key, 0)) for p in now + rest]


def _music_minutes(ds, d: date) -> Optional[float]:
    if not ds.media:
        return None
    first, last = min(m.start.date() for m in ds.media), max(m.start.date() for m in ds.media)
    if not first <= d <= last:
        return None
    return sum(m.minutes for m in ds.media_on(d) if m.kind in ("music", "podcast"))


def _chips(ds, f) -> List[str]:
    """The calendar chips of a day; without a calendar, "calm day" would claim a free day nobody measured."""
    chips = describe_features(f)
    return chips if _has_calendar(ds) else [c for c in chips if c != "calm day"]


def _cause_day(p: LifestylePattern, night_date: date) -> date:
    """The day a pattern's cause is looked up on for a night: a short night is tested against the day after it."""
    return night_date + timedelta(days=1) if p.key == "short_night" else night_date


def daily_input(engine, morning: date) -> ReportInput:
    """Last night (the night before ``morning``) explained from the day before it."""
    ds = engine.ds
    r = engine.morning_report(morning, narrate=False)
    night_date = r.night_date
    metrics: List[Metric] = []
    if r.score is not None:
        metrics.append(_metric("sleep.score", "Sleep score", "watch", "points", float(r.score),
                               bl.history(ds, night_date, "score")[-HISTORY:], "up"))
        for key, mkey, label, unit, good in SLEEP_DEFS:
            metrics.append(_metric(mkey, label, "watch", unit, bl.night_metric(r.night, key),
                                   bl.history(ds, night_date, key)[-HISTORY:], good))
    for m in r.recovery:
        if m.value is not None and m.key in RECOVERY_KEYS:
            metrics.append(Metric(key=RECOVERY_KEYS[m.key], label=m.label, source="watch", value=_r(m.value), unit=m.unit,
                                  baseline=_r(m.baseline), delta=_r(m.delta), status=m.status))
    before = _days_before(night_date, HISTORY)
    steps = _steps(ds, night_date)
    if steps is not None:
        metrics.append(_metric("activity.steps", "Steps the day before", "watch", "steps", steps,
                               [_steps(ds, d) for d in before], "up"))
    day_hr = daytime_hr(ds, night_date)
    if day_hr is not None:
        metrics.append(_metric("hr.daytime", "Daytime heart rate the day before", "watch", "bpm", day_hr,
                               [daytime_hr(ds, d) for d in before], "down"))
    music = _music_minutes(ds, night_date)
    if music is not None:
        metrics.append(_metric("music.minutes", "Music and podcasts the day before", "music", "min", music,
                               [_music_minutes(ds, d) for d in before], "none"))
    for key, label, unit in SCREEN_DEFS:
        v = _day_metric(ds, night_date, key)
        if v is not None:
            metrics.append(_metric(key, label + " the day before", "screen_time", unit, v,
                                   [_day_metric(ds, d, key) for d in before], "down"))
    logged = False
    for key, label, unit, good in CHECKIN_DEFS:
        v = _day_metric(ds, night_date, key)
        if v is not None:
            logged = True
            metrics.append(_metric(key, label + " the day before", "checkin", unit, v, [_day_metric(ds, d, key) for d in before], good))
    f = day_features(ds, night_date)
    weekday_before = [d for d in before if d.weekday() < 5] if night_date.weekday() < 5 else [d for d in before if d.weekday() >= 5]
    if _has_calendar(ds):                      # without a calendar, 0 meetings would read as a free day
        metrics.append(_metric("calendar.meetings", "Meetings the day before", "calendar", "count", float(f.n_meetings),
                               [float(day_features(ds, d).n_meetings) for d in weekday_before], "down"))
        metrics.append(_metric("calendar.meeting_time", "Time in meetings the day before", "calendar", "min",
                               float(f.meeting_minutes), [float(day_features(ds, d).meeting_minutes) for d in weekday_before], "down"))

    titles = [ev.title for d in (night_date, morning) for ev in ds.events_on(d, include_unattended=True)]
    patterns: List[Pattern] = []
    for c in r.causes + r.helpers:
        key = "pattern." + c.factor
        if any(p.key == key for p in patterns):
            continue
        patterns.append(Pattern(key=key, title=FACTOR_LABELS.get(c.factor, c.factor), detail=_scrub(c.detail, titles), direction=c.direction, effect=_r(c.points),
                                unit="points", n=c.n_similar, confidence=c.confidence))

    # Links whose cause happened yesterday (or, for a short night, last night), then the strongest others.
    lifestyle = engine.lifestyle(morning)
    happened = {p.key: int(active_on(ds, p, _cause_day(p, night_date))) for p in lifestyle if p.primary is not None}
    causes = {c.factor for c in r.causes + r.helpers}
    patterns += _links(lifestyle, happened, {k for k, f in SAME_AS_CAUSE.items() if f in causes})

    notes = [_scrub(n, titles) for n in (r.missing_data, r.unexplained_note, r.confidence_note) if n]
    if not logged and any(_day_metric(ds, d, k) is not None for d in before for k, _, _, _ in CHECKIN_DEFS):
        notes.append("Coffee and alcohol were not logged for the day before, so the report cannot say whether they played a part.")
    yesterday = DayPoint(day=night_date, score=r.score, tags=_chips(ds, f) + day_tags(ds, night_date, lifestyle))
    return ReportInput(kind="daily", period_start=morning, period_end=morning,
                       n_nights=r.model.n_nights if r.model else 0, metrics=metrics, patterns=patterns, days=[yesterday],
                       suggestions=[_scrub(s.title, titles) for s in r.suggestions], notes=notes)


def weekly_input(engine, monday: date) -> ReportInput:
    """Monday to Sunday: each day and the night after it, against the 28 nights before the week."""
    ds = engine.ds
    days = [monday + timedelta(days=k) for k in range(7)]
    nights = [ds.night(d) for d in days]
    worn = [n for n in nights if n is not None and n.worn and n.score is not None]

    metrics: List[Metric] = []
    for key, mkey, label, unit, good in WEEK_NIGHT_DEFS:
        value = _mean([bl.night_metric(n, key) for n in worn])
        if value is not None:
            metrics.append(_metric(mkey, label + " (week average)", "watch", unit, value,
                                   bl.history(ds, monday, key)[-HISTORY:], good))
    steps = _mean([_steps(ds, d) for d in days])
    if steps is not None:
        metrics.append(_metric("activity.steps", "Steps per day (week average)", "watch", "steps", steps,
                               [_steps(ds, d) for d in _days_before(monday, HISTORY)], "up"))
    for key, label, unit in SCREEN_DEFS:
        value = _mean([_day_metric(ds, d, key) for d in days])
        if value is not None:
            metrics.append(_metric(key, label + " per day (week average)", "screen_time", unit, value,
                                   [_day_metric(ds, d, key) for d in _days_before(monday, HISTORY)], "down"))
    n_logged = sum(1 for d in days if any(_day_metric(ds, d, k) is not None for k, _, _, _ in CHECKIN_DEFS))
    for key, label, unit, good in CHECKIN_DEFS:
        value = _mean([_day_metric(ds, d, key) for d in days])
        if value is not None:
            metrics.append(_metric(key, label + " per logged day (week average)", "checkin", unit, value,
                                   [_day_metric(ds, d, key) for d in _days_before(monday, HISTORY)], good))
    feats = [day_features(ds, d) for d in days]
    weekly_meetings = [sum(day_features(ds, monday - timedelta(days=7 * w - k)).n_meetings for k in range(7)) for w in range(1, 5)]
    if _has_calendar(ds):
        metrics.append(_metric("calendar.meetings", "Meetings this week", "calendar", "count",
                               float(sum(f.n_meetings for f in feats)), [float(v) for v in weekly_meetings], "down"))

    # Links whose cause happened at least once this week, then the strongest others.
    lifestyle = engine.lifestyle(monday + timedelta(days=7))
    happened = {p.key: sum(1 for d in days if active_on(ds, p, _cause_day(p, d))) for p in lifestyle if p.primary is not None}
    patterns = _links(lifestyle, happened, set())

    points = [DayPoint(day=d, score=(n.score if (n is not None and n.worn) else None),
                       tags=_chips(ds, f) + day_tags(ds, d, lifestyle))
              for d, n, f in zip(days, nights, feats)]
    notes: List[str] = []
    if 0 < n_logged < 7:
        notes.append("Coffee and alcohol were logged on %d of the 7 days this week." % n_logged)
    if len(worn) < 7:
        notes.append("The watch recorded %d of the 7 nights this week." % len(worn))
    n_hist = len(bl.worn_nights(ds, monday))
    if n_hist < 10:
        notes.append("Only %d nights of history before this week, so the usual values are rough." % n_hist)
    return ReportInput(kind="weekly", period_start=monday, period_end=days[-1], n_nights=n_hist, metrics=metrics,
                       patterns=patterns, days=points, notes=notes)
