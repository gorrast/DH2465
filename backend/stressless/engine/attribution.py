"""Within-person attribution: LOO-CV ridge, block bootstrap, active-only contributions (SPEC §7.5).

Pure Python. The only function that reads ``Dataset.truth`` is ``validation`` (Lab only).
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..models import (Cause, Coefficient, Dataset, Evidence, FACTOR_LABELS, ModelSummary, REGRESSOR_KEYS)
from ..timeutil import at, day_hour, fmt_minutes, hour_label
from . import baselines as bl
from .features import day_features
from .matching import event_response

LAMBDA_GRID = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0)
MIN_NIGHTS = 10
MIN_ACTIVE = 3
BLOCK = 5


def _finite(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return xf if math.isfinite(xf) else None


@dataclass
class FitResult:
    keys: List[str]
    coef: Dict[str, float]
    intercept: float
    x_mean: Dict[str, float]
    x_sd: Dict[str, float]
    y_mean: float
    r2: float
    rmse: float
    r2_loo: float
    rmse_loo: float
    ridge_lambda: float
    n: int
    n_total: int
    n_unworn: int
    ci: Dict[str, Optional[Tuple[float, float]]]
    n_active: Dict[str, int]
    boot: List[Dict[str, float]]
    loo_residuals: Dict[date, float]
    hat: Dict[date, float]
    dates: List[date]
    insufficient: bool
    calm_day_pred: float
    target: str = "score"
    history_days: Optional[int] = None
    exclude: Optional[date] = None
    mean_active_x: Dict[str, float] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# linear algebra (tiny, dense)
# --------------------------------------------------------------------------- #
def mat_inv(a: List[List[float]]) -> List[List[float]]:
    n = len(a)
    m = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("singular matrix")
        m[col], m[piv] = m[piv], m[col]
        pv = m[col][col]
        m[col] = [v / pv for v in m[col]]
        for r in range(n):
            if r != col and m[r][col] != 0.0:
                f = m[r][col]
                m[r] = [rv - f * cv for rv, cv in zip(m[r], m[col])]
    return [row[n:] for row in m]


def _ridge(xtx: List[List[float]], xty: List[float], lam: float) -> Tuple[List[float], List[List[float]]]:
    p = len(xty)
    a = [[xtx[i][j] + (lam if i == j else 0.0) for j in range(p)] for i in range(p)]
    inv = mat_inv(a)
    beta = [sum(inv[i][j] * xty[j] for j in range(p)) for i in range(p)]
    return beta, inv


# --------------------------------------------------------------------------- #
# design and fit
# --------------------------------------------------------------------------- #
def design(ds: Dataset, upto: date, history_days: Optional[int] = None, exclude: Optional[date] = None,
           include_unattended: bool = False, target: str = "score"
           ) -> Tuple[List[Dict[str, float]], List[float], List[date], int, int]:
    lo = (upto - timedelta(days=int(history_days))) if history_days else None
    rows, y, dates = [], [], []
    n_total = n_unworn = 0
    for d in ds.night_dates():
        if d >= upto or (lo is not None and d < lo):
            continue
        n_total += 1
        night = ds.night(d)
        if night is None or not night.worn or night.score is None:
            n_unworn += 1
            continue
        if exclude is not None and d == exclude:
            continue
        yv = bl.night_metric(night, target)
        if yv is None:
            continue
        events = ds.events_on(d, include_unattended=True) if include_unattended else None
        rows.append(day_features(ds, d, events=events).regressors())
        y.append(float(yv))
        dates.append(d)
    return rows, y, dates, n_total, n_unworn


def fit(ds: Dataset, upto: date, exclude: Optional[date] = None, history_days: Optional[int] = None, target: str = "score",
        ridge: Optional[float] = None, bootstrap: int = 500, seed: int = 0, cache: Optional[dict] = None,
        include_unattended: bool = False) -> FitResult:
    key = ("fit", upto, exclude, history_days, target, ridge, bootstrap, include_unattended)
    if cache is not None and key in cache:
        return cache[key]
    rows, y, dates, n_total, n_unworn = design(ds, upto, history_days, exclude, include_unattended, target)
    keys = list(REGRESSOR_KEYS)
    n = len(y)
    n_active = {k: sum(1 for r in rows if r.get(k, 0.0) != 0.0) for k in keys}
    mean_active = {k: (sum(r[k] for r in rows if r.get(k, 0.0) != 0.0) / n_active[k]) if n_active[k] else 0.0 for k in keys}
    y_mean = (sum(y) / n) if n else 0.0
    x_mean = {k: (sum(r[k] for r in rows) / n) if n else 0.0 for k in keys}
    x_sd = {k: (math.sqrt(sum((r[k] - x_mean[k]) ** 2 for r in rows) / n) if n else 0.0) for k in keys}
    sd_y = math.sqrt(sum((v - y_mean) ** 2 for v in y) / n) if n else 10.0

    if n < MIN_NIGHTS:
        res = FitResult(keys=keys, coef={k: 0.0 for k in keys}, intercept=y_mean, x_mean=x_mean, x_sd=x_sd, y_mean=y_mean,
                        r2=0.0, rmse=sd_y or 10.0, r2_loo=0.0, rmse_loo=sd_y or 10.0, ridge_lambda=0.0, n=n, n_total=n_total,
                        n_unworn=n_unworn, ci={k: None for k in keys}, n_active=n_active, boot=[], loo_residuals={}, hat={},
                        dates=dates, insufficient=True, calm_day_pred=y_mean, target=target, history_days=history_days,
                        exclude=exclude, mean_active_x=mean_active)
        if cache is not None:
            cache[key] = res
        return res

    active = [k for k in keys if x_sd[k] > 1e-9 and n_active[k] >= MIN_ACTIVE]
    p = len(active)
    xs = [[(r[k] - x_mean[k]) / x_sd[k] for k in active] for r in rows]
    yc = [v - y_mean for v in y]
    sst = sum(v * v for v in yc) or 1e-9
    xtx = [[sum(xs[i][a] * xs[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    xty = [sum(xs[i][a] * yc[i] for i in range(n)) for a in range(p)]

    best = None
    grid = (ridge,) if ridge is not None else LAMBDA_GRID
    for lam in grid:
        beta, inv = _ridge(xtx, xty, lam)
        e_loo, e, h = [], [], []
        for i in range(n):
            xi = xs[i]
            pred = sum(xi[a] * beta[a] for a in range(p))
            hi = sum(xi[a] * sum(inv[a][b] * xi[b] for b in range(p)) for a in range(p))
            hi = min(hi, 0.999)
            ei = yc[i] - pred
            e.append(ei)
            h.append(hi)
            e_loo.append(ei / (1.0 - hi))
        sse_loo = sum(v * v for v in e_loo)
        if best is None or sse_loo < best[0]:
            best = (sse_loo, lam, beta, inv, e, h, e_loo)
    sse_loo, lam, beta, inv, e, h, e_loo = best
    sse = sum(v * v for v in e)
    coef = {k: 0.0 for k in keys}
    for a, k in enumerate(active):
        coef[k] = beta[a] / x_sd[k]
    r2 = max(0.0, min(1.0, 1.0 - sse / sst))
    r2_loo = max(0.0, min(1.0, 1.0 - sse_loo / sst))
    rmse = math.sqrt(sse / n)
    rmse_loo = math.sqrt(sse_loo / n)
    calm = y_mean - sum(coef[k] * x_mean[k] for k in keys)

    # moving-block bootstrap with precomputed block sums (blocks of consecutive nights)
    boot: List[Dict[str, float]] = []
    ci: Dict[str, Optional[Tuple[float, float]]] = {k: None for k in keys}
    if bootstrap and p and n >= BLOCK:
        rng = random.Random(seed)
        n_blocks = n - BLOCK + 1
        blk_xtx, blk_xy, blk_y, blk_x = [], [], [], []
        for s in range(n_blocks):
            idx = range(s, s + BLOCK)
            blk_xtx.append([[sum(xs[i][a] * xs[i][b] for i in idx) for b in range(p)] for a in range(p)])
            blk_xy.append([sum(xs[i][a] * y[i] for i in idx) for a in range(p)])
            blk_y.append(sum(y[i] for i in idx))
            blk_x.append([sum(xs[i][a] for i in idx) for a in range(p)])
        k_blocks = int(math.ceil(n / float(BLOCK)))
        for _ in range(bootstrap):
            picks = [rng.randrange(n_blocks) for _ in range(k_blocks)]
            m = k_blocks * BLOCK
            sxtx = [[0.0] * p for _ in range(p)]
            sxy = [0.0] * p
            sy = 0.0
            sx = [0.0] * p
            for b in picks:
                bx = blk_xtx[b]
                for a in range(p):
                    row = sxtx[a]
                    brow = bx[a]
                    for c in range(p):
                        row[c] += brow[c]
                    sxy[a] += blk_xy[b][a]
                    sx[a] += blk_x[b][a]
                sy += blk_y[b]
            ybar = sy / m
            xty_b = [sxy[a] - ybar * sx[a] for a in range(p)]
            try:
                beta_b, _ = _ridge(sxtx, xty_b, lam)
            except ValueError:
                continue
            draw = {k: 0.0 for k in keys}
            for a, k in enumerate(active):
                draw[k] = beta_b[a] / x_sd[k]
            boot.append(draw)
        for k in active:
            vals = sorted(d[k] for d in boot)
            if len(vals) >= 20:
                lo_i = int(0.025 * (len(vals) - 1))
                hi_i = int(0.975 * (len(vals) - 1))
                ci[k] = (vals[lo_i], vals[hi_i])

    res = FitResult(keys=keys, coef=coef, intercept=y_mean, x_mean=x_mean, x_sd=x_sd, y_mean=y_mean, r2=r2, rmse=rmse,
                    r2_loo=r2_loo, rmse_loo=rmse_loo, ridge_lambda=lam, n=n, n_total=n_total, n_unworn=n_unworn, ci=ci,
                    n_active=n_active, boot=boot, loo_residuals={d: e_loo[i] for i, d in enumerate(dates)},
                    hat={d: h[i] for i, d in enumerate(dates)}, dates=dates, insufficient=False, calm_day_pred=calm,
                    target=target, history_days=history_days, exclude=exclude, mean_active_x=mean_active)
    if cache is not None:
        cache[key] = res
    return res


def predict(fit_: FitResult, reg: Dict[str, float]) -> float:
    v = fit_.intercept + sum(fit_.coef[k] * (reg.get(k, 0.0) - fit_.x_mean.get(k, 0.0)) for k in fit_.keys)
    return max(0.0, min(100.0, v))


def predict_interval(fit_: FitResult, before: Dict[str, float], after: Dict[str, float]) -> Tuple[float, float]:
    delta = sum(fit_.coef[k] * (after.get(k, 0.0) - before.get(k, 0.0)) for k in fit_.keys)
    if not fit_.boot:
        return delta, delta
    draws = sorted(sum(b[k] * (after.get(k, 0.0) - before.get(k, 0.0)) for k in fit_.keys) for b in fit_.boot)
    lo = draws[int(0.025 * (len(draws) - 1))]
    hi = draws[int(0.975 * (len(draws) - 1))]
    return lo, hi


def contribution_interval(fit_: FitResult, k: str, x: float) -> Tuple[Optional[float], Optional[float]]:
    if not fit_.boot:
        return None, None
    draws = sorted(b[k] * x for b in fit_.boot)
    return draws[int(0.025 * (len(draws) - 1))], draws[int(0.975 * (len(draws) - 1))]


def summary(fit_: FitResult) -> ModelSummary:
    coefs = []
    for k in fit_.keys:
        c = fit_.ci.get(k)
        coefs.append(Coefficient(key=k, label=FACTOR_LABELS.get(k, k), value=round(fit_.coef[k], 3),
                                 ci_low=round(c[0], 3) if c else 0.0, ci_high=round(c[1], 3) if c else 0.0,
                                 n_active=fit_.n_active.get(k, 0)))
    return ModelSummary(n_nights=fit_.n, r2=round(fit_.r2, 3), rmse=round(fit_.rmse, 2), intercept=round(fit_.intercept, 2),
                        coefficients=coefs, history_days=fit_.history_days, target=fit_.target, ridge_lambda=fit_.ridge_lambda,
                        r2_loo=round(fit_.r2_loo, 3), rmse_loo=round(fit_.rmse_loo, 2), insufficient=fit_.insufficient,
                        calm_day_pred=round(fit_.calm_day_pred, 1), n_total_nights=fit_.n_total, n_unworn=fit_.n_unworn)


# --------------------------------------------------------------------------- #
# explanations
# --------------------------------------------------------------------------- #
def confidence_for(fit_: FitResult, k: str) -> str:
    n_act = fit_.n_active.get(k, 0)
    if n_act < 4 or fit_.n < 20 or fit_.insufficient:
        return "low"
    c = fit_.ci.get(k)
    excludes = bool(c and (c[0] > 0 or c[1] < 0))
    strong = abs(fit_.coef[k] * fit_.mean_active_x.get(k, 1.0)) >= 1.0
    if excludes and n_act >= 8 and strong:
        return "high"
    if (excludes and n_act >= 4) or n_act >= 8:
        return "medium"
    return "low"


def _pct(v: Optional[float]) -> str:
    return "–" if v is None else "%+.0f %%" % v


def explain_night(ds: Dataset, morning: date, fit_: FitResult, norm: Sequence[Optional[float]], cache: Optional[dict] = None
                  ) -> Tuple[List[Cause], List[Cause], List[Evidence], Dict[str, Any]]:
    night_date = morning - timedelta(days=1)
    f = day_features(ds, night_date)
    reg = f.regressors()
    night = ds.night(night_date)
    worn = night is not None and night.worn and night.score is not None
    events = ds.events_on(night_date)
    recovery = {m.key: m for m in bl.recovery_metrics(ds, night_date)}
    bed_base = bl.baseline_for(ds, night_date, "bedtime_min")
    dur_base = bl.baseline_for(ds, night_date, "duration_min")
    int_base = bl.baseline_for(ds, night_date, "interruptions")
    bed_v = bl.night_metric(night, "bedtime_min")
    dur_v = bl.night_metric(night, "duration_min")
    bed_shift = (bed_v - bed_base["median"]) if (bed_v is not None and bed_base["median"] is not None) else None

    contribs: List[Tuple[str, float]] = []
    if not fit_.insufficient:
        for k in fit_.keys:
            if k == "is_weekend" or reg.get(k, 0.0) == 0.0 or fit_.n_active.get(k, 0) < MIN_ACTIVE:
                continue
            contribs.append((k, fit_.coef[k] * reg[k]))
    causes: List[Cause] = []
    helpers: List[Cause] = []

    def hrv_text() -> str:
        m = recovery.get("hrv_ms")
        return "Overnight HRV %s vs your baseline" % _pct(m.delta_pct if m else None)

    def build(k: str, c: float) -> Cause:
        title, detail, evidence, ev_ids = FACTOR_LABELS.get(k, k), "", [], []
        if k == "late_meeting_hours":
            meetings = [e for e in events if e.type == "meeting" and day_hour(e.end, night_date) > 18.0]
            ev = max(meetings, key=lambda e: e.end) if meetings else None
            if ev is not None:
                ev_ids = [ev.id]
                title = "Meeting until %s" % hour_label(day_hour(ev.end, night_date))
                resp = event_response(ds, ev, norm)
                d60 = resp.get("delta_post60")
                if d60 is not None and resp.get("elevated_until") is not None:
                    detail = "Heart rate %+.0f bpm above your evening norm until %s" % (d60, resp["elevated_until"].strftime("%H:%M"))
                elif d60 is not None:
                    detail = "Heart rate %+.0f bpm above your evening norm for the rest of the evening" % d60
                else:
                    detail = "%s ran %s past 18:00" % (ev.title, fmt_minutes(reg[k] * 60))
                evidence.append(Evidence(kind="hr", text=detail, value=d60, unit="bpm", series=resp["series"],
                                         series_baseline=resp["series_norm"], series_start=resp["series_start"], series_step_min=5))
        elif k == "meetings_over_3":
            title = "%d meetings, %d back-to-back" % (f.n_meetings, f.max_b2b_run) if f.max_b2b_run >= 3 else "%d meetings" % f.n_meetings
            detail = hrv_text()
            m = recovery.get("hrv_ms")
            evidence.append(Evidence(kind="hrv", text=detail, value=m.value if m else None, baseline=m.baseline if m else None, unit="ms",
                                     series=m.series if m else None))
            ev_ids = [e.id for e in events if e.type == "meeting"]
        elif k == "b2b_over_2":
            title = "%d meetings back-to-back" % f.max_b2b_run
            detail = hrv_text()
            ev_ids = [e.id for e in events if e.type == "meeting"]
        elif k == "evening_social":
            socials = [e for e in events if e.type == "social"]
            ev = max(socials, key=lambda e: e.end) if socials else None
            if ev is not None:
                title = "%s until %s" % (ev.title, hour_label(day_hour(ev.end, night_date)))
                ev_ids = [ev.id]
            rhr = recovery.get("resting_hr")
            parts = []
            if bed_shift is not None:
                parts.append("Bedtime %s %s than usual" % (fmt_minutes(abs(bed_shift)), "later" if bed_shift > 0 else "earlier"))
            if rhr and rhr.delta is not None:
                parts.append("resting heart rate %+.0f bpm" % rhr.delta)
            detail = "; ".join(parts) or "A late evening"
            if bed_shift is not None:
                evidence.append(Evidence(kind="bedtime", text=parts[0], value=bed_v, baseline=bed_base["median"], unit="min"))
            if rhr and rhr.delta is not None:
                evidence.append(Evidence(kind="rhr", text="Resting heart rate %+.0f bpm vs baseline" % rhr.delta, value=rhr.value, baseline=rhr.baseline, unit="bpm", series=rhr.series))
            temp = recovery.get("wrist_temp_dev")
            hrv = recovery.get("hrv_ms")
            if (rhr and rhr.z is not None and rhr.z >= 1.0) or (temp and temp.z is not None and temp.z >= 1.0) or (hrv and hrv.z is not None and hrv.z <= -1.0):
                evidence.append(Evidence(kind="temp", text="Body signals (RHR %+.0f bpm, wrist temp %+.1f °C) suggest more than the late evening itself — e.g. alcohol, which the calendar cannot see" % (
                    rhr.delta if (rhr and rhr.delta is not None) else 0.0, temp.value if (temp and temp.value is not None) else 0.0)))
        elif k == "workout_late":
            wos = [e for e in events if e.type == "workout"]
            ev = max(wos, key=lambda e: e.start) if wos else None
            act = ds.activity_on(night_date)
            ww = None
            if act and ev is not None:
                for w in act.workouts:
                    if w.start < ev.end and w.end > ev.start:
                        ww = w
            if ev is not None:
                title = "Workout at %s" % hour_label(day_hour(ev.start, night_date))
                ev_ids = [ev.id]
            onset = bl.night_metric(night, "onset_min")
            onset_txt = fmt_minutes(onset - bed_v) if (onset is not None and bed_v is not None) else "a while"
            if ww is not None:
                detail = "Watch logged %d bpm for %d min; you fell asleep %s after going to bed" % (ww.avg_hr, int((ww.end - ww.start).total_seconds() // 60), onset_txt)
            else:
                detail = "You fell asleep %s after going to bed" % onset_txt
            evidence.append(Evidence(kind="hr", text=detail))
        elif k == "workout_morning":
            title = "Morning workout"
            detail = "On the %d mornings you trained, scores averaged %+.0f points (adjusted)" % (fit_.n_active.get(k, 0), fit_.coef[k] * fit_.mean_active_x.get(k, 1.0))
            ev_ids = [e.id for e in events if e.type == "workout"]
        elif k == "travel":
            trips = [e for e in events if e.type == "travel"]
            title = trips[0].title if trips else "Travel day"
            ev_ids = [e.id for e in trips]
            detail = "On your %d travel days, scores averaged %+.0f points (adjusted)" % (fit_.n_active.get(k, 0), fit_.coef[k] * fit_.mean_active_x.get(k, 1.0))
        elif k == "early_start":
            title = "First event %s" % (hour_label(f.first_start_hour) if f.first_start_hour is not None else "early")
            detail = "Slept %s vs your usual %s" % (fmt_minutes(dur_v) if dur_v is not None else "–", fmt_minutes(dur_base["median"]) if dur_base["median"] is not None else "–")
            evidence.append(Evidence(kind="duration", text=detail, value=dur_v, baseline=dur_base["median"], unit="min"))
            ev_ids = [e.id for e in events if e.type in ("meeting", "travel", "personal") and day_hour(e.start, night_date) < 7.5]
        elif k == "protected_evening":
            title = "Protected evening"
            detail = ("Bedtime %s earlier than usual" % fmt_minutes(abs(bed_shift))) if (bed_shift is not None and bed_shift < 0) else "A calm evening before bed"
            ev_ids = [e.id for e in events if e.type == "protected"]
        lo, hi = contribution_interval(fit_, k, reg[k])
        return Cause(rank=0, factor=k, title=title, detail=detail, points=round(c, 1), direction="hurt" if c < 0 else "helped",
                     confidence=confidence_for(fit_, k), evidence=evidence, event_ids=ev_ids, n_similar=fit_.n_active.get(k, 0),
                     points_low=_finite(lo) if lo is None else round(lo, 1), points_high=_finite(hi) if hi is None else round(hi, 1))

    for k, c in sorted(contribs, key=lambda t: t[1]):
        if c < -0.75 and len(causes) < 3:
            causes.append(build(k, c))
    for k, c in sorted(contribs, key=lambda t: -t[1]):
        if c > 0.75 and len(helpers) < 2:
            helpers.append(build(k, c))
    for i, c in enumerate(causes):
        c.rank = i + 1
    for i, c in enumerate(helpers):
        c.rank = i + 1

    proximal: List[Evidence] = []
    if worn:
        if bed_shift is not None and abs(bed_shift) >= 10:
            proximal.append(Evidence(kind="bedtime", text="Bedtime %s %s than usual" % (fmt_minutes(abs(bed_shift)), "later" if bed_shift > 0 else "earlier"), value=bed_v, baseline=bed_base["median"], unit="min"))
        if dur_v is not None:
            need = ds.persona.sleep_need_min
            proximal.append(Evidence(kind="duration", text="Asleep %s (you need about %s)" % (fmt_minutes(dur_v), fmt_minutes(need)), value=dur_v, baseline=float(need), unit="min"))
        if int_base["median"] is not None and night.interruptions is not None:
            proximal.append(Evidence(kind="interruptions", text="%d interruptions (usually %d)" % (night.interruptions, int(round(int_base["median"]))), value=float(night.interruptions), baseline=int_base["median"]))
        for key in ("hrv_ms", "resting_hr"):
            m = recovery.get(key)
            if m and m.delta is not None:
                if key == "hrv_ms":
                    proximal.append(Evidence(kind="hrv", text="HRV %s vs baseline" % _pct(m.delta_pct), value=m.value, baseline=m.baseline, unit="ms"))
                else:
                    proximal.append(Evidence(kind="rhr", text="Resting heart rate %+.0f bpm vs baseline" % m.delta, value=m.value, baseline=m.baseline, unit="bpm"))

    predicted = predict(fit_, reg) if not fit_.insufficient else None
    residual = None
    if worn and predicted is not None:
        residual = fit_.loo_residuals.get(night_date, night.score - predicted)
    note = None
    if residual is not None and fit_.rmse_loo:
        temp = recovery.get("wrist_temp_dev")
        if residual <= -1.5 * fit_.rmse_loo:
            note = ("About %d points are not explained by your calendar. Hidden factors like alcohol, caffeine, screens, "
                    "a short night before, or illness may matter." % int(round(abs(residual))))
            if temp and temp.z is not None and temp.z >= 1.5 and temp.value is not None:
                note += " Wrist temperature is %+.1f °C above baseline — a sign of illness or alcohol." % temp.value
        elif residual >= 1.5 * fit_.rmse_loo:
            note = "You slept better than your calendar predicts."
    meta = {"predicted": _finite(predicted), "calm_day_pred": _finite(fit_.calm_day_pred) if not fit_.insufficient else None,
            "residual": _finite(residual), "unexplained_note": note, "features": f, "regressors": reg}
    return causes, helpers, proximal, meta


# --------------------------------------------------------------------------- #
# statistics helpers
# --------------------------------------------------------------------------- #
def _ranks(vals: Sequence[float]) -> List[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return _finite(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy))


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    return pearson(_ranks(xs), _ranks(ys))


# --------------------------------------------------------------------------- #
# validation against planted truth (Lab only)
# --------------------------------------------------------------------------- #
def validation(ds: Dataset, fit_: FitResult, fit_before: Optional[FitResult], checks: Sequence[Any],
               cache: Optional[dict] = None) -> Dict[str, Any]:
    truth = ds.truth
    if truth is None:
        return {"available": False, "reason": "No planted truth: this dataset was imported from real sources."}
    planted_keys = [k for k in REGRESSOR_KEYS if k != "is_weekend"]
    coefficients = []
    est, tot, direct_vals = [], [], []
    for k in planted_keys:
        c = fit_.ci.get(k)
        total = truth.effect_table.get(k)
        direct = truth.effect_table_direct.get(k)
        design_v = truth.effect_table_design.get(k, 0.0)
        covers = bool(c and c[0] <= 0.0 <= c[1])
        coefficients.append({"key": k, "label": FACTOR_LABELS.get(k, k), "estimated": _finite(round(fit_.coef[k], 2)),
                             "ci_low": _finite(round(c[0], 2)) if c else None, "ci_high": _finite(round(c[1], 2)) if c else None,
                             "planted_total": _finite(round(total, 2)) if total is not None else None,
                             "planted_direct": _finite(round(direct, 2)) if direct is not None else None,
                             "design": _finite(design_v), "n_active": fit_.n_active.get(k, 0),
                             "null_planted": design_v == 0.0, "ci_covers_zero": covers})
        if total is not None and direct is not None:
            est.append(fit_.coef[k])
            tot.append(total)
            direct_vals.append(direct)
    # pooled (night, factor) pairs
    engine_c, true_c = [], []
    totals_true, totals_engine = [], []
    truth_by_date = {tn.date: tn for tn in truth.nights}
    for d in fit_.dates:
        tn = truth_by_date.get(d)
        if tn is None:
            continue
        reg = day_features(ds, d).regressors()
        for k in planted_keys:
            if reg.get(k, 0.0) != 0.0 and k in tn.contributions:
                engine_c.append(fit_.coef[k] * reg[k])
                true_c.append(tn.contributions[k])
        totals_true.append(sum(v for kk, v in tn.contributions.items() if not kk.startswith("hidden:")))
        totals_engine.append(predict(fit_, reg) - fit_.calm_day_pred)
    # hold-out: fit on nights <= end-14, predict the last 14 worn nights
    holdout = None
    cut = ds.end - timedelta(days=13)
    try:
        f_train = fit(ds, cut, cache=cache, bootstrap=0)
        train_scores = [ds.night(d).score for d in f_train.dates]
        naive = statistics.median(train_scores) if train_scores else None
        errs, errs_naive = [], []
        for d in ds.night_dates():
            if d < cut or d > ds.end:
                continue
            night = ds.night(d)
            if night is None or not night.worn or night.score is None:
                continue
            pred = predict(f_train, day_features(ds, d).regressors())
            errs.append((night.score - pred) ** 2)
            if naive is not None:
                errs_naive.append((night.score - naive) ** 2)
        if errs and errs_naive and not f_train.insufficient:
            rmse_h = math.sqrt(sum(errs) / len(errs))
            rmse_n = math.sqrt(sum(errs_naive) / len(errs_naive))
            holdout = {"rmse_holdout": round(rmse_h, 2), "rmse_naive": round(rmse_n, 2),
                       "skill": _finite(round(1.0 - rmse_h / rmse_n, 3)) if rmse_n else None, "n_test": len(errs), "n_train": f_train.n}
    except Exception:
        holdout = None
    # reality confusion
    positives = set()
    wfh = set()
    for te in truth.events:
        ev = ds.event(te.event_id)
        if ev is None or ev.type not in ("workout", "social", "travel"):
            continue
        if te.attended is False:
            positives.add(te.event_id)
        if te.reason == "wfh":
            wfh.add(te.event_id)
    predicted = {c.event_id for c in checks if c.kind in ("booked_not_seen", "location_mismatch") and c.event_id}
    tp = len(predicted & positives)
    fp = len(predicted - positives - wfh)
    fn = len(positives - predicted)
    unbooked = set(truth.unbooked)
    seen = {c.visit_id for c in checks if c.kind == "seen_not_booked" and c.visit_id}
    tp_u = len(seen & unbooked)
    fn_u = len(unbooked - seen)
    reality = {"booked_not_seen": {"tp": tp, "fp": fp, "fn": fn,
                                   "precision": _finite(round(tp / (tp + fp), 2)) if (tp + fp) else None,
                                   "recall": _finite(round(tp / (tp + fn), 2)) if (tp + fn) else None},
               "seen_not_booked": {"tp": tp_u, "fn": fn_u, "recall": _finite(round(tp_u / (tp_u + fn_u), 2)) if (tp_u + fn_u) else None}}
    # hidden factors vs flagged nights
    hidden_dates = {tn.date for tn in truth.nights if (tn.hidden.get("alcohol_units") or 0) > 0 or tn.hidden.get("caffeine_late")
                    or tn.hidden.get("screens_late") or tn.hidden.get("illness")}
    flagged = {d for d, r in fit_.loo_residuals.items() if fit_.rmse_loo and r <= -1.5 * fit_.rmse_loo}
    tp_h = len(flagged & hidden_dates)
    hidden = {"nights_with_hidden": len(hidden_dates), "flagged": len(flagged),
              "precision": _finite(round(tp_h / len(flagged), 2)) if flagged else None,
              "recall": _finite(round(tp_h / len(hidden_dates), 2)) if hidden_dates else None,
              "illness_nights": truth.hidden_summary.get("illness_nights", []),
              "unworn_nights": truth.hidden_summary.get("unworn_nights", []),
              "unworn_social_nights": truth.hidden_summary.get("unworn_social_nights", 0),
              "alcohol_nights": truth.hidden_summary.get("alcohol_nights", 0),
              "caffeine_days": truth.hidden_summary.get("caffeine_days", 0),
              "screens_nights": truth.hidden_summary.get("screens_nights", 0),
              "sleep_debt_mean": truth.hidden_summary.get("debt_mean", 0.0),
              "mean_hidden_effect": truth.hidden_summary.get("mean_hidden_effect", {})}
    n_events_past = sum(1 for te in truth.events)
    stressors = {"pct_booked_not_attended": _finite(round(100.0 * sum(1 for te in truth.events if te.attended is False) / n_events_past, 1)) if n_events_past else None,
                 "pct_nights_hidden": _finite(round(100.0 * len(hidden_dates) / len(truth.nights), 1)) if truth.nights else None,
                 "pct_unworn": _finite(round(100.0 * sum(1 for n in ds.nights if not n.worn) / len(ds.nights), 1)) if ds.nights else None,
                 "r2_gap": _finite(round(fit_.r2 - fit_.r2_loo, 3))}
    return {
        "available": True,
        "coefficients": coefficients,
        "spearman_total": spearman(tot, est),
        "spearman_direct": spearman(direct_vals, est),
        "pooled_spearman": spearman(true_c, engine_c),
        "pooled_n": len(true_c),
        "pearson_totals": pearson(totals_true, totals_engine),
        "holdout": holdout,
        "spearman_before_answers": spearman(tot, [fit_before.coef[k] for k in planted_keys if truth.effect_table.get(k) is not None]) if fit_before else None,
        "spearman_after_answers": spearman(tot, est),
        "reality": reality,
        "hidden": hidden,
        "stressors": stressors,
        "noise_note": "noise_points = interactions + noise (the score is nonlinear, so one-at-a-time removals do not add up exactly)",
        "limitations": ["One person's data: correlation, not proof.",
                        "Hinge features (meetings beyond three, hours past 18:00) are a simplification of a day.",
                        "The DST change night is off by one hour in durations.",
                        "The simulator plants alcohol on most social nights, so the social effect the engine sees includes the wine."],
    }
