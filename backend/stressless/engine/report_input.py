"""Build the ``ReportInput`` a generated report is written from (see ``stressless.reports``).

Everything here is computed by the engine; the model only puts it into words. Only numbers, code-written labels and
dates go in: no event titles, places, people, ids or clock times, because the input is sent to the model as is.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import List, Optional

from ..models import FACTOR_LABELS
from ..reports import Metric, Pattern, DayPoint, ReportInput
from . import baselines as bl
from .features import day_features, describe_features

HISTORY = 28                                   # nights or days behind a "usual" value

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
    f = day_features(ds, night_date)
    weekday_before = [d for d in before if d.weekday() < 5] if night_date.weekday() < 5 else [d for d in before if d.weekday() >= 5]
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

    notes = [_scrub(n, titles) for n in (r.missing_data, r.unexplained_note, r.confidence_note) if n]
    return ReportInput(kind="daily", period_start=morning, period_end=morning,
                       n_nights=r.model.n_nights if r.model else 0, metrics=metrics, patterns=patterns,
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
    feats = [day_features(ds, d) for d in days]
    weekly_meetings = [sum(day_features(ds, monday - timedelta(days=7 * w - k)).n_meetings for k in range(7)) for w in range(1, 5)]
    metrics.append(_metric("calendar.meetings", "Meetings this week", "calendar", "count",
                           float(sum(f.n_meetings for f in feats)), [float(v) for v in weekly_meetings], "down"))

    patterns: List[Pattern] = []
    for h in engine.habits(monday + timedelta(days=7)):
        if h.confidence == "low" or h.direction == "neutral" or h.effect is None:
            continue
        detail = "%+d points on the %d nights it happened, against nights without it." % (round(h.effect), h.n_with)
        patterns.append(Pattern(key="pattern." + h.key, title=h.title, detail=detail,
                                direction="helped" if h.direction == "good" else "hurt", effect=_r(h.effect),
                                unit="points", n=h.n_with, confidence=h.confidence))
        if len(patterns) == 4:
            break

    points = [DayPoint(day=d, score=(n.score if (n is not None and n.worn) else None), tags=describe_features(f))
              for d, n, f in zip(days, nights, feats)]
    notes: List[str] = []
    if len(worn) < 7:
        notes.append("The watch recorded %d of the 7 nights this week." % len(worn))
    n_hist = len(bl.worn_nights(ds, monday))
    if n_hist < 10:
        notes.append("Only %d nights of history before this week, so the usual values are rough." % n_hist)
    return ReportInput(kind="weekly", period_start=monday, period_end=days[-1], n_nights=n_hist, metrics=metrics,
                       patterns=patterns, days=points, notes=notes)
