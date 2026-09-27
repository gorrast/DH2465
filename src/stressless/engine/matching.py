"""Match calendar events to the body's response: heart rate windows against a personal norm (SPEC §7.3)."""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..models import CalendarEvent, Dataset, LocationVisit, SleepNight
from ..timeutil import at, day_range, overlap_minutes
from .features import day_features


def _mean(vals: Sequence[Optional[float]]) -> Optional[float]:
    xs = [float(v) for v in vals if v is not None]
    if not xs:
        return None
    m = sum(xs) / len(xs)
    return m if math.isfinite(m) else None


def hr_slice(ds: Dataset, start: datetime, end: datetime) -> List[Optional[int]]:
    """Minute samples from ``start`` (inclusive) to ``end`` (exclusive), across day boundaries."""
    out: List[Optional[int]] = []
    tzname = str(start.tzinfo)
    cur = start.replace(second=0, microsecond=0)
    while cur < end:
        hr = ds.hr(cur.date())
        idx = cur.hour * 60 + cur.minute
        if hr is not None and 0 <= idx < len(hr.bpm):
            out.append(hr.bpm[idx])
        else:
            out.append(None)
        cur += timedelta(minutes=1)
    return out


def rolling_mean(values: Sequence[Optional[float]], window: int) -> List[Optional[float]]:
    """Centred None-aware moving average."""
    n = len(values)
    half = window // 2
    out: List[Optional[float]] = [None] * n
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        out[i] = _mean(values[lo:hi])
    return out


def _workout_mask(ds: Dataset, d: date) -> List[bool]:
    mask = [False] * 1440
    act = ds.activity_on(d)
    if act is None:
        return mask
    for w in act.workouts:
        s = max(0, w.start.hour * 60 + w.start.minute - 10)
        e = min(1440, w.end.hour * 60 + w.end.minute + 10)
        if w.end.date() != d:
            e = 1440
        for m in range(s, e):
            mask[m] = True
    return mask


def hr_norm_curve(ds: Dataset, upto: date, window_days: int = 21, cache: Optional[dict] = None) -> List[Optional[float]]:
    """Per clock minute, the median of the smoothed heart rate over prior calm days."""
    key = ("norm", upto, window_days)
    if cache is not None and key in cache:
        return cache[key]
    days = [d for d in day_range(upto - timedelta(days=window_days), upto - timedelta(days=1)) if ds.hr(d) is not None]
    calm = [d for d in days if day_features(ds, d).late_meeting_hours == 0 and day_features(ds, d).evening_social == 0]
    use = calm if len(calm) >= 10 else days
    smoothed: List[List[Optional[float]]] = []
    for d in use:
        hr = ds.hr(d)
        mask = _workout_mask(ds, d)
        vals = [None if (mask[m] or hr.bpm[m] is None) else float(hr.bpm[m]) for m in range(min(1440, len(hr.bpm)))]
        smoothed.append(rolling_mean(vals, 21))
    norm: List[Optional[float]] = [None] * 1440
    for m in range(1440):
        col = [s[m] for s in smoothed if m < len(s) and s[m] is not None]
        norm[m] = statistics.median(col) if len(col) >= 3 else None
    if cache is not None:
        cache[key] = norm
    return norm


def _norm_slice(norm: Sequence[Optional[float]], start: datetime, end: datetime) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    cur = start.replace(second=0, microsecond=0)
    while cur < end:
        out.append(norm[(cur.hour * 60 + cur.minute) % 1440] if norm else None)
        cur += timedelta(minutes=1)
    return out


def _series(values: Sequence[Optional[float]], step: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(0, len(values), step):
        m = _mean(values[i:i + step])
        out.append(None if m is None else round(m, 1))
    return out


def event_response(ds: Dataset, ev: CalendarEvent, norm: Sequence[Optional[float]]) -> Dict[str, Any]:
    during = hr_slice(ds, ev.start, ev.end)
    norm_during = _norm_slice(norm, ev.start, ev.end)
    post = hr_slice(ds, ev.end, ev.end + timedelta(minutes=60))
    post_norm = _norm_slice(norm, ev.end, ev.end + timedelta(minutes=60))
    during_mean, norm_mean = _mean(during), _mean(norm_during)
    post_mean, post_norm_mean = _mean(post), _mean(post_norm)
    vals = [v for v in during if v is not None]
    # elevated_until: first minute after the end where the 15-min rolling mean stays <= norm + 3 for 15 minutes
    elevated_until: Optional[datetime] = None
    horizon = hr_slice(ds, ev.end, ev.end + timedelta(hours=3))
    horizon_norm = _norm_slice(norm, ev.end, ev.end + timedelta(hours=3))
    roll = rolling_mean(horizon, 15)
    run = 0
    for i, (r, nv) in enumerate(zip(roll, horizon_norm)):
        if r is None or nv is None:
            run = 0
            continue
        if r <= nv + 3.0:
            run += 1
            if run >= 15:
                elevated_until = ev.end + timedelta(minutes=i - 14)
                break
        else:
            run = 0
    series_start = ev.start - timedelta(minutes=30)
    series_end = ev.end + timedelta(minutes=180)
    return {
        "event_id": ev.id,
        "during_mean": None if during_mean is None else round(during_mean, 1),
        "during_max": max(vals) if vals else None,
        "norm_during": None if norm_mean is None else round(norm_mean, 1),
        "delta_during": None if (during_mean is None or norm_mean is None) else round(during_mean - norm_mean, 1),
        "post60_mean": None if post_mean is None else round(post_mean, 1),
        "post60_norm": None if post_norm_mean is None else round(post_norm_mean, 1),
        "delta_post60": None if (post_mean is None or post_norm_mean is None) else round(post_mean - post_norm_mean, 1),
        "elevated_until": elevated_until,
        "series": _series(hr_slice(ds, series_start, series_end), 5),
        "series_norm": _series(_norm_slice(norm, series_start, series_end), 5),
        "series_start": series_start,
        "series_step_min": 5,
    }


def evening_summary(ds: Dataset, d: date, norm: Sequence[Optional[float]]) -> Dict[str, Any]:
    tzname = ds.persona.tz
    start, end = at(d, 20.0, tzname=tzname), at(d, 23.0, tzname=tzname)
    hr = hr_slice(ds, start, end)
    nv = _norm_slice(norm, start, end)
    m, nm = _mean(hr), _mean(nv)
    roll = rolling_mean(hr, 15)
    elevated_until: Optional[datetime] = None
    for i in range(len(roll) - 1, -1, -1):
        if roll[i] is not None and nv[i] is not None and roll[i] > nv[i] + 3.0:
            elevated_until = start + timedelta(minutes=i + 1)
            break
    return {"mean": None if m is None else round(m, 1), "norm": None if nm is None else round(nm, 1),
            "delta": None if (m is None or nm is None) else round(m - nm, 1), "elevated_until": elevated_until,
            "series": _series(hr, 5), "series_norm": _series(nv, 5), "series_start": start, "series_step_min": 5}


def workout_signature(ds: Dataset, start: datetime, end: datetime) -> Dict[str, Any]:
    hr = hr_slice(ds, start, end)
    vals = [v for v in hr if v is not None]
    return {"minutes_over_120": sum(1 for v in vals if v > 120), "mean": (round(sum(vals) / len(vals), 1) if vals else None),
            "max": (max(vals) if vals else None), "min": (min(vals) if vals else None), "n_samples": len(vals)}


def visits_during(ds: Dataset, start: datetime, end: datetime) -> List[Tuple[LocationVisit, int]]:
    out = []
    seen = set()
    for d in day_range(start.date(), end.date()):
        for v in ds.visits_on(d):
            if v.id in seen:
                continue
            seen.add(v.id)
            ov = overlap_minutes(v.start, v.end, start, end)
            if ov > 0:
                out.append((v, ov))
    out.sort(key=lambda t: -t[1])
    return out


def night_hr_series(ds: Dataset, night: Optional[SleepNight]) -> List[Optional[float]]:
    if night is None or not night.worn or night.in_bed_start is None or night.wake_time is None:
        return []
    return _series(hr_slice(ds, night.in_bed_start, night.wake_time), 10)
