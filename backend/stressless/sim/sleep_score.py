"""Sleep score from the same inputs a watch has (SPEC §5.4).

Shared by the simulator and the importers so a real Apple Health export is scored the same way
as the digital twin. Apple-style bands are used for the rating label only; this is *our* score.
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Tuple

BANDS = ((40, "Very low"), (60, "Low"), (80, "OK"), (95, "High"), (100, "Very high"))


def compute_score(params: Dict[str, float], recent_bedtimes: List[float]) -> Tuple[int, Dict[str, int]]:
    """Return ``(score, parts)``.

    ``params`` keys: ``duration_min`` (asleep minutes), ``bedtime_min`` (minutes after 12:00 of the
    night date: 23:15 -> 675, 00:20 -> 740), ``interruptions``, ``awake_min``, ``sleep_need_min``.
    ``recent_bedtimes`` uses the same unit for up to the previous 14 worn nights (may be empty).
    """
    duration = float(params["duration_min"])
    need = float(params.get("sleep_need_min") or 450)
    ratio = max(0.0, min(1.0, duration / need if need > 0 else 0.0))
    duration_pts = 50.0 * ratio ** 1.3
    if duration > need + 120:
        duration_pts -= 5.0
    duration_pts = max(0.0, duration_pts)

    if recent_bedtimes:
        med = statistics.median(recent_bedtimes)
        dev = float(params["bedtime_min"]) - med
        if dev >= 0:      # later than usual: the familiar consistency penalty
            consistency_pts = max(0.0, 30.0 - 0.25 * max(0.0, dev - 20.0))
        else:             # earlier than usual rarely hurts: wider dead-band, gentler slope
            consistency_pts = max(0.0, 30.0 - 0.10 * max(0.0, -dev - 30.0))
    else:
        consistency_pts = 30.0

    interruptions = float(params.get("interruptions") or 0)
    awake = float(params.get("awake_min") or 0)
    interruption_pts = max(0.0, 20.0 - 3.0 * interruptions - awake / 8.0)

    parts = {
        "duration": int(round(duration_pts)),
        "consistency": int(round(consistency_pts)),
        "interruptions": int(round(interruption_pts)),
    }
    score = int(round(duration_pts + consistency_pts + interruption_pts))
    score = max(0, min(100, score))
    return score, parts


def rating(score) -> str:
    """Apple-style band label (Very low / Low / OK / High / Very high)."""
    if score is None:
        return "No data"
    s = int(score)
    for upper, label in BANDS:
        if s <= upper:
            return label
    return "Very high"


def band_status(score) -> str:
    """Map a score to a status token name for the UI ring (critical/serious/warning/good)."""
    if score is None:
        return "unknown"
    s = int(score)
    if s <= 40:
        return "critical"
    if s <= 60:
        return "serious"
    if s <= 80:
        return "warning"
    return "good"
