"""Lifestyle patterns: steps, phone use, coffee, alcohol and sleep rhythm against the night after them, and short
nights against the day after ("on your days under 6 500 steps you sleep 20 min less").

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
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..models import Dataset
from ..timeutil import is_weekend_night
from . import baselines as bl
from .habits import CONF_WEIGHT, confidence_for, stratified_effect

HISTORY_DAYS = 56                              # days the patterns are computed over
MIN_DAYS = 14                                  # days with the cause measured before a split is made
CHECKIN_MIN_DAYS = 10                          # the same for causes the person logs by hand
MIN_GROUP = 4                                  # days on each side of the split for an outcome to be tested
BOOTSTRAP = 400
HINT_LEVEL = 0.80                              # interval that must exclude zero for a hint (95 % for strong)
MIN_STEPS = 100                                # fewer steps in a day means the phone was not carried, not a lazy day
ONSET_HISTORY = 14                             # nights behind a person's usual sleep onset
OFF_RHYTHM_MIN = 60.0                          # sleep onset this far from the usual counts as off-rhythm
SLEEP_DEBT_NIGHTS = 3
SLEEP_DEBT_MIN = 120.0                         # minutes short of the sleep need over SLEEP_DEBT_NIGHTS nights


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


def _steps(ds: Dataset, d: date) -> Optional[float]:
    a = ds.activity_on(d)
    return float(a.steps) if a is not None and a.steps >= MIN_STEPS else None


def _night(key: str) -> Callable[[Dataset, date], Optional[float]]:
    return lambda ds, d: bl.night_metric(ds.night(d), key)


def _metric(key: str) -> Callable[[Dataset, date], Optional[float]]:
    return lambda ds, d: ds.metric_on(d, key)


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
    OutcomeDef("steps", "Steps", "steps", "up", 800, "%s more steps", "%s fewer steps", _steps, False),
    OutcomeDef("screen_minutes", "Screen time", "min", "down", 15, "%s more screen time", "%s less screen time",
               _metric("screen.minutes"), False),
    OutcomeDef("pickups", "Phone pickups", "count", "down", 5, "%s more phone pickups", "%s fewer phone pickups",
               _metric("screen.pickups"), False),
)}
NIGHT = ("score", "duration_min", "onset_min", "hrv_ms", "resting_hr")


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


def _q(p: float, floor: float = 0.0) -> Callable[[List[float]], float]:
    def f(vals: List[float]) -> float:
        s = sorted(vals)
        return max(floor, s[min(len(s) - 1, int(p * len(s)))])
    return f


def _fixed(x: float) -> Callable[[List[float]], float]:
    return lambda vals: x


CAUSES: Tuple[CauseDef, ...] = (
    CauseDef("low_steps", "Low-step days", _steps, "low", _q(1 / 3), "steps", "days under %s steps",
             "On the nights after your %d %s", NIGHT),
    CauseDef("active_days", "Active days", _steps, "high", _q(2 / 3), "steps", "days over %s steps",
             "On the nights after your %d %s", NIGHT),
    CauseDef("late_screen", "Late-evening phone use", _metric("screen.late_minutes"), "high", _q(2 / 3, 20), "min",
             "evenings with %s or more on the phone after 22:00", "On the nights after your %d %s", NIGHT),
    CauseDef("heavy_screen", "Heavy phone days", _metric("screen.minutes"), "high", _q(2 / 3, 60), "min",
             "days with %s or more of screen time", "On the nights after your %d %s", NIGHT),
    CauseDef("many_pickups", "Many phone pickups", _metric("screen.pickups"), "high", _q(2 / 3, 10), "count",
             "days with %s or more phone pickups", "On the nights after your %d %s", NIGHT),
    CauseDef("off_rhythm", "Off-rhythm bedtimes", _onset_offset, "high", _fixed(OFF_RHYTHM_MIN), "min",
             "nights you fell asleep %s or more away from your usual time", "On your %d %s",
             ("score", "duration_min", "hrv_ms", "resting_hr")),
    CauseDef("sleep_debt", "Built-up sleep debt", _sleep_debt, "high", _fixed(SLEEP_DEBT_MIN), "min",
             "nights after 3 nights adding up to %s or more short of your sleep need", "On your %d %s",
             ("hrv_ms", "resting_hr")),
    CauseDef("short_night", "Short nights", _last_night, "low", _q(1 / 3), "min", "nights under %s of sleep",
             "On the days after your %d %s", ("steps", "screen_minutes", "pickups")),
    CauseDef("alcohol", "Evenings with alcohol", _metric("intake.alcohol_units"), "high", _fixed(1.0), "units",
             "evenings with alcohol", "On the nights after your %d %s", NIGHT, CHECKIN_MIN_DAYS),
    CauseDef("more_coffee", "More coffee than usual", _metric("intake.coffee_cups"), "high", _q(2 / 3, 1), "cups",
             "days with %s or more cups of coffee", "On the nights after your %d %s",
             ("score", "duration_min", "onset_min", "hrv_ms"), CHECKIN_MIN_DAYS),
)
CAUSES_BY_KEY = {c.key: c for c in CAUSES}


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
    def hint(self) -> bool:
        """Only an early hint: no outcome is strong."""
        return bool(self.reportable) and all(o.tier == "hint" for o in self.reportable)

    def detail(self) -> str:
        """One or two sentences with the numbers, for the report input. Strong outcomes only, unless all are hints."""
        cause = CAUSES_BY_KEY[self.key]
        rep = sorted((o for o in self.reportable if self.hint or o.tier == "strong"), key=lambda o: -o.strength)
        if not rep:
            return ""
        parts = []
        for o in rep:
            od = OUTCOMES[o.key]
            parts.append((od.more if o.effect > 0 else od.less) % fmt(abs(o.effect), o.unit))
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        other = "nights" if OUTCOMES[rep[0].key].night else "days"
        text = "%s: %s, compared with your other %d %s." % (cause.lead % (self.n_with, self.description), joined,
                                                              self.n_without, other)
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
    c = CAUSES_BY_KEY[p.key]
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
    for c in CAUSES:
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
        if not effects:
            continue
        desc = c.describe % _threshold_text(c, t) if "%s" in c.describe else c.describe
        p = LifestylePattern(key=c.key, title=c.title, description=desc, threshold=t,
                             n_with=n_with, n_without=len(active) - n_with, outcomes=effects)
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
    return tags
