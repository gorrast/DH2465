"""Recurring patterns ranked by their association with sleep, stratified by weekend nights (SPEC §7.6)."""
from __future__ import annotations

import math
import random
import statistics
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..models import DayFeatures, Dataset, Habit, HabitBucket, SleepNight
from . import baselines as bl
from .features import day_features, describe_features

HabitDef = Tuple[str, str, str, str, Callable[[DayFeatures], bool], Optional[str]]

HABIT_DEFS: List[HabitDef] = [
    ("late_meeting", "Late meetings", "A meeting that ends after 18:00", "calendar", lambda f: f.late_meeting_hours > 0, "late_meeting_hours"),
    ("heavy_meetings", "Heavy meeting days", "Five or more meetings in a day", "calendar", lambda f: f.n_meetings >= 5, "meetings_over_3"),
    ("back_to_back", "Back-to-back blocks", "Three or more meetings in a row", "calendar", lambda f: f.max_b2b_run >= 3, "b2b_over_2"),
    ("evening_social", "Evening social", "Dinner or drinks ending after 20:30", "social", lambda f: f.evening_social == 1, "evening_social"),
    ("morning_workout", "Morning workouts", "Training before 10:00", "workout", lambda f: f.workout_slot == "morning", "workout_morning"),
    ("evening_workout", "Evening workouts", "Training between 17:00 and 19:30", "workout", lambda f: f.workout_slot == "evening", None),
    ("late_workout", "Late workouts", "Training late in the evening", "workout", lambda f: f.workout_slot == "late", "workout_late"),
    ("travel", "Travel days", "Flights and long trips", "travel", lambda f: f.travel == 1, "travel"),
    ("early_start", "Early starts", "First commitment before 07:30", "routine", lambda f: f.early_start == 1, "early_start"),
    ("protected_evening", "Protected evenings", "A wind-down block before bed", "routine", lambda f: f.protected_evening == 1, "protected_evening"),
    ("calm_weekday", "Calm workdays", "Two meetings or fewer on a work night", "calendar", lambda f: f.n_meetings <= 2 and not f.is_weekend, None),
    ("weekend_night", "Weekend nights", "Friday and Saturday nights", "routine", lambda f: f.is_weekend == 1, "is_weekend"),
]
CONF_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}


def _finite(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    return float(x) if math.isfinite(float(x)) else None


def night_pairs(ds: Dataset, upto: date, history_days: Optional[int] = None, cache: Optional[dict] = None) -> List[Tuple[SleepNight, DayFeatures]]:
    key = ("pairs", upto, history_days)
    if cache is not None and key in cache:
        return cache[key]
    pairs = [(n, day_features(ds, n.date)) for n in bl.worn_nights(ds, upto, history_days)]
    if cache is not None:
        cache[key] = pairs
    return pairs


def _mean(xs: Sequence[float]) -> Optional[float]:
    return (sum(xs) / len(xs)) if xs else None


def stratified_effect(groups: Dict[int, Tuple[List[float], List[float]]]) -> Optional[float]:
    """sum_s w_s (mean_with,s - mean_without,s), w_s = n_with,s / n_with over strata with both groups."""
    usable = {s: (w, wo) for s, (w, wo) in groups.items() if w and wo}
    n_with = sum(len(w) for w, _ in usable.values())
    if not n_with:
        return None
    return sum((len(w) / n_with) * (_mean(w) - _mean(wo)) for w, wo in usable.values())


def bootstrap_effect_ci(groups: Dict[int, Tuple[List[float], List[float]]], rng: random.Random, b: int = 800) -> Tuple[Optional[float], Optional[float]]:
    usable = {s: (w, wo) for s, (w, wo) in groups.items() if w and wo}
    if not usable:
        return None, None
    draws = []
    for _ in range(b):
        g = {}
        for s, (w, wo) in usable.items():
            g[s] = ([w[rng.randrange(len(w))] for _ in range(len(w))], [wo[rng.randrange(len(wo))] for _ in range(len(wo))])
        e = stratified_effect(g)
        if e is not None:
            draws.append(e)
    if len(draws) < 20:
        return None, None
    draws.sort()
    return draws[int(0.025 * (len(draws) - 1))], draws[int(0.975 * (len(draws) - 1))]


def _groups(pairs: Sequence[Tuple[SleepNight, DayFeatures]], pred: Callable[[DayFeatures], bool], metric: str,
            stratify: bool = True) -> Dict[int, Tuple[List[float], List[float]]]:
    groups: Dict[int, Tuple[List[float], List[float]]] = {0: ([], []), 1: ([], [])}
    for n, f in pairs:
        v = bl.night_metric(n, metric)
        if v is None:
            continue
        s = int(f.is_weekend) if stratify else 0
        (groups[s][0] if pred(f) else groups[s][1]).append(v)
    return groups


def confidence_for(lo: Optional[float], hi: Optional[float], n_with: int, n_without: int) -> str:
    excludes = lo is not None and hi is not None and (lo > 0 or hi < 0)
    mn = min(n_with, n_without)
    if excludes and mn >= 10:
        return "high"
    if mn >= 6 and (excludes or mn >= 12):
        return "medium"
    return "low"


def rank_habits(ds: Dataset, upto: date, history_days: Optional[int] = None, fit=None, bootstrap: int = 800, seed: int = 0,
                cache: Optional[dict] = None) -> List[Habit]:
    key = ("habits", upto, history_days, bootstrap, id(fit) if fit is not None else None)
    if cache is not None and key in cache:
        return cache[key]
    pairs = night_pairs(ds, upto, history_days, cache)
    rng = random.Random(seed)
    out: List[Habit] = []
    for hkey, title, desc, group, pred, reg_key in HABIT_DEFS:
        stratify = hkey != "weekend_night"
        groups = _groups(pairs, pred, "score", stratify)
        n_with = sum(len(w) for w, _ in groups.values())
        n_without = sum(len(wo) for _, wo in groups.values())
        if n_with == 0:
            continue
        effect = stratified_effect(groups)
        raw_groups = _groups(pairs, pred, "score", False)
        raw = stratified_effect(raw_groups)
        lo, hi = bootstrap_effect_ci(groups, rng, bootstrap) if bootstrap else (None, None)
        mean_with = _mean([v for w, _ in groups.values() for v in w])
        mean_without = _mean([v for _, wo in groups.values() for v in wo])
        adjusted = None
        if fit is not None and reg_key is not None and not getattr(fit, "insufficient", False):
            adjusted = fit.coef.get(reg_key, 0.0) * fit.mean_active_x.get(reg_key, 1.0)
        hrv_groups = _groups(pairs, pred, "hrv_ms", stratify)
        hrv_eff = stratified_effect(hrv_groups)
        hrv_base = _mean([v for _, wo in hrv_groups.values() for v in wo])
        rhr_eff = stratified_effect(_groups(pairs, pred, "resting_hr", stratify))
        conf = confidence_for(lo, hi, n_with, n_without)
        if effect is None:
            direction = "neutral"
        elif abs(effect) < 1.5:
            direction = "neutral"
        else:
            direction = "good" if effect > 0 else "bad"
        excludes = lo is not None and hi is not None and (lo > 0 or hi < 0)
        conservative = min(abs(lo), abs(hi)) if excludes else (0.25 * abs(effect) if effect is not None else 0.0)
        rank_score = conservative * CONF_WEIGHT[conf]
        examples = [n.date for n, f in pairs if pred(f)][-6:]
        out.append(Habit(key=hkey, title=title, description=desc, group=group, n_with=n_with, n_without=n_without,
                         mean_with=_finite(round(mean_with, 1)) if mean_with is not None else None,
                         mean_without=_finite(round(mean_without, 1)) if mean_without is not None else None,
                         effect=_finite(round(effect, 1)) if effect is not None else None,
                         ci_low=_finite(round(lo, 1)) if lo is not None else None, ci_high=_finite(round(hi, 1)) if hi is not None else None,
                         adjusted_effect=_finite(round(adjusted, 1)) if adjusted is not None else None, direction=direction,
                         confidence=conf, example_dates=examples,
                         metric_effects={"hrv_ms_pct": _finite(round(100.0 * hrv_eff / hrv_base, 0)) if (hrv_eff is not None and hrv_base) else None,
                                         "resting_hr": _finite(round(rhr_eff, 1)) if rhr_eff is not None else None},
                         raw_effect=_finite(round(raw, 1)) if raw is not None else None, rank_score=_finite(round(rank_score, 2))))
    out.sort(key=lambda h: -(h.rank_score or 0.0))
    if cache is not None:
        cache[key] = out
    return out


def _bucket_ci(vals: Sequence[float], rng: random.Random, b: int = 600) -> Tuple[Optional[float], Optional[float]]:
    if len(vals) < 3:
        return None, None
    draws = sorted(_mean([vals[rng.randrange(len(vals))] for _ in range(len(vals))]) for _ in range(b))
    return draws[int(0.025 * (b - 1))], draws[int(0.975 * (b - 1))]


def meeting_load_buckets(ds: Dataset, upto: date, weeks: int = 6, cache: Optional[dict] = None, history_days: Optional[int] = None) -> List[HabitBucket]:
    key = ("buckets", upto, weeks, history_days)
    if cache is not None and key in cache:
        return cache[key]
    pairs = night_pairs(ds, upto, history_days, cache)
    lo_date = upto - timedelta(days=7 * weeks)
    rng = random.Random(1)
    defs = [("0 to 2 meetings", lambda f: f.n_meetings <= 2), ("3 to 4 meetings", lambda f: 3 <= f.n_meetings <= 4), ("5+ meetings", lambda f: f.n_meetings >= 5)]
    out = []
    for label, pred in defs:
        vals = [float(n.score) for n, f in pairs if n.date >= lo_date and not f.is_weekend and pred(f)]
        lo, hi = _bucket_ci(vals, rng)
        out.append(HabitBucket(label=label, n=len(vals), mean_score=_finite(round(_mean(vals), 1)) if vals else None,
                               lo=_finite(round(lo, 1)) if lo is not None else None, hi=_finite(round(hi, 1)) if hi is not None else None))
    if cache is not None:
        cache[key] = out
    return out


def weekly_insight(ds: Dataset, upto: date, weeks: int = 6, habits: Optional[List[Habit]] = None, cache: Optional[dict] = None,
                   history_days: Optional[int] = None) -> Dict[str, Any]:
    buckets = meeting_load_buckets(ds, upto, weeks, cache, history_days)
    calm, heavy = buckets[0], buckets[2]
    headline = "Not enough nights in the last %d weeks to compare meeting loads yet." % weeks
    if calm.mean_score is not None and heavy.mean_score is not None:
        diff = heavy.mean_score - calm.mean_score
        pairs = night_pairs(ds, upto, history_days, cache)
        lo_date = upto - timedelta(days=7 * weeks)
        rng = random.Random(2)
        a = [float(n.score) for n, f in pairs if n.date >= lo_date and not f.is_weekend and f.n_meetings >= 5]
        b = [float(n.score) for n, f in pairs if n.date >= lo_date and not f.is_weekend and f.n_meetings <= 2]
        draws = sorted(_mean([a[rng.randrange(len(a))] for _ in a]) - _mean([b[rng.randrange(len(b))] for _ in b]) for _ in range(600)) if (len(a) >= 3 and len(b) >= 3) else []
        excludes = bool(draws) and (draws[int(0.025 * (len(draws) - 1))] > 0 or draws[int(0.975 * (len(draws) - 1))] < 0)
        if excludes and diff < 0:
            headline = "Days with five or more meetings were followed by scores %d points lower than calm days (n = %d vs %d)." % (round(abs(diff)), heavy.n, calm.n)
        elif excludes and diff > 0:
            headline = "Days with five or more meetings were followed by scores %d points higher than calm days (n = %d vs %d)." % (round(diff), heavy.n, calm.n)
        else:
            headline = "Meeting load made little difference in the last %d weeks (difference %d points, n = %d vs %d)." % (weeks, round(diff), heavy.n, calm.n)
    if habits is None:
        habits = rank_habits(ds, upto, history_days, cache=cache)
    strongest = None
    for h in habits:
        if h.confidence != "low" and h.direction != "neutral" and h.effect is not None:
            strongest = "%s: %s%d points on the %d nights it happened (%s confidence)." % (
                h.title, "+" if h.effect > 0 else "−", abs(round(h.effect)), h.n_with, h.confidence)
            break
    last7 = []
    for k in range(7, 0, -1):
        d = upto - timedelta(days=k)
        n = ds.night(d)
        f = day_features(ds, d)
        last7.append({"date": d.isoformat(), "score": n.score if (n and n.worn) else None, "worn": bool(n and n.worn), "chips": describe_features(f)})
    heat = []
    for d in ds.night_dates():
        if d >= upto:
            continue
        n = ds.night(d)
        heat.append({"date": d.isoformat(), "score": n.score if (n and n.worn) else None, "worn": bool(n and n.worn), "is_weekend": bool(day_features(ds, d).is_weekend)})
    return {"buckets": buckets, "headline": headline, "strongest_pattern": strongest, "last7": last7, "heat": heat,
            "n_nights": len(bl.worn_nights(ds, upto, history_days)), "top_habits": habits[:5], "weeks": weeks}
