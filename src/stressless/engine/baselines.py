"""Personal baselines: robust medians over the person's own recent nights (SPEC §7.2)."""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from ..models import Dataset, RecoveryMetric, SleepNight
from ..timeutil import at

METRIC_KEYS = ("score", "hrv_ms", "resting_hr", "resp_rate", "wrist_temp_dev", "spo2", "duration_min",
               "interruptions", "awake_min", "bedtime_min", "onset_min", "wake_min")

RECOVERY_DEFS = (
    ("hrv_ms", "Overnight HRV", "ms", "up"),
    ("resting_hr", "Resting heart rate", "bpm", "down"),
    ("wrist_temp_dev", "Wrist temperature", "°C", "zero"),
    ("resp_rate", "Respiratory rate", "br/min", "zero"),
    ("spo2", "Blood oxygen", "%", "up"),
)


def _finite(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return xf if math.isfinite(xf) else None


def robust_baseline(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    """(median, 1.4826 * MAD) with a tiny floor; (None, None) below 3 values."""
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if len(vals) < 3:
        return None, None
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    return med, max(1.4826 * mad, 1e-6)


def _night_min(night: SleepNight, dt) -> Optional[float]:
    if dt is None:
        return None
    return (dt - at(night.date, 12.0, tzname=str(dt.tzinfo))).total_seconds() / 60.0


def night_metric(night: Optional[SleepNight], key: str) -> Optional[float]:
    if night is None or not night.worn:
        return None
    if key == "bedtime_min":
        return _finite(_night_min(night, night.in_bed_start))
    if key == "onset_min":
        return _finite(_night_min(night, night.sleep_onset))
    if key == "wake_min":
        return _finite(_night_min(night, night.wake_time))
    if key in ("interruptions", "awake_min", "duration_min", "score"):
        v = getattr(night, key, None)
        return None if v is None else float(v)
    return _finite(getattr(night, key, None))


def worn_nights(ds: Dataset, upto: date, history_days: Optional[int] = None) -> List[SleepNight]:
    """Worn nights with a score strictly before ``upto`` (last ``history_days`` calendar nights)."""
    lo = (upto - timedelta(days=int(history_days))) if history_days else None
    out = []
    for d in ds.night_dates():
        if d >= upto:
            break
        if lo is not None and d < lo:
            continue
        n = ds.night(d)
        if n is not None and n.worn and n.score is not None:
            out.append(n)
    return out


def history(ds: Dataset, upto: date, key: str, history_days: Optional[int] = None) -> List[float]:
    vals = []
    for n in worn_nights(ds, upto, history_days):
        v = night_metric(n, key)
        if v is not None:
            vals.append(v)
    return vals


def baseline_for(ds: Dataset, upto: date, key: str, window: int = 28, history_days: Optional[int] = None) -> Dict[str, Optional[float]]:
    vals = history(ds, upto, key, history_days)[-window:]
    med, scale = robust_baseline(vals)
    return {"median": med, "scale": scale, "n": len(vals)}


def z(value: Optional[float], baseline: Dict[str, Optional[float]]) -> Optional[float]:
    if value is None or baseline.get("median") is None or not baseline.get("scale"):
        return None
    return _finite((float(value) - baseline["median"]) / baseline["scale"])


def _status(zv: Optional[float], good_direction: str) -> str:
    if zv is None:
        return "unknown"
    if good_direction == "up":
        if zv >= 0.8:
            return "good"
        if zv <= -1.0:
            return "watch"
    elif good_direction == "down":
        if zv <= -0.8:
            return "good"
        if zv >= 1.0:
            return "watch"
    else:
        if abs(zv) >= 1.5:
            return "watch"
    return "typical"


def recovery_metrics(ds: Dataset, night_date: date, window: int = 28) -> List[RecoveryMetric]:
    night = ds.night(night_date)
    out: List[RecoveryMetric] = []
    for key, label, unit, good in RECOVERY_DEFS:
        value = night_metric(night, key)
        base = baseline_for(ds, night_date, key, window)
        zv = z(value, base)
        med = base["median"]
        delta = _finite(value - med) if (value is not None and med is not None) else None
        delta_pct = _finite(delta / med * 100.0) if (delta is not None and med not in (None, 0)) else None
        if key == "wrist_temp_dev":
            delta_pct = None
        series: List[Optional[float]] = []
        for k in range(13, -1, -1):
            d = night_date - timedelta(days=k)
            series.append(night_metric(ds.night(d), key))
        out.append(RecoveryMetric(key=key, label=label, value=_finite(value), baseline=_finite(med), delta=delta,
                                  delta_pct=delta_pct, z=zv, unit=unit, good_direction=good,
                                  status=_status(zv, good), series=series))
    return out
