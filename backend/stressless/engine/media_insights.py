"""Exploratory associations between imported media and the existing daily dataset."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..models import Dataset
from .baselines import night_metric
from .features import day_features


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _corr(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    if len(left) < 3 or len(left) != len(right):
        return None
    left_mean, right_mean = statistics.mean(left), statistics.mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_sd = math.sqrt(sum((a - left_mean) ** 2 for a in left))
    right_sd = math.sqrt(sum((b - right_mean) ** 2 for b in right))
    if left_sd == 0 or right_sd == 0:
        return None
    return round(numerator / (left_sd * right_sd), 2)


def _event_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _confidence(sample: int) -> str:
    return "high" if sample >= 20 else "medium" if sample >= 8 else "low"


def _minutes(rows: Sequence[Dict[str, Any]], kind: Optional[str] = None) -> float:
    return sum(float(row.get("minutes") or 0) for row in rows if kind is None or (row.get("source") or {}).get("media_kind") == kind)


def _average(rows: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return round(statistics.mean(values), 1) if values else None


def analyze_media(ds: Dataset, media_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Return small, sample-aware associations for media days overlapping health/calendar history."""
    by_day: Dict[date, List[Dict[str, Any]]] = defaultdict(list)
    for row in media_rows:
        occurred = _event_datetime(row.get("occurred_at"))
        if occurred is not None:
            by_day[occurred.date()].append(row)

    days: List[Dict[str, Any]] = []
    for day, events in sorted(by_day.items()):
        if day < ds.start or day > ds.end:
            continue
        night = ds.night(day)
        if night is None or not night.worn or night.score is None:
            continue
        features = day_features(ds, day)
        late_events = [row for row in events if (_event_datetime(row.get("occurred_at")) or datetime.min).hour >= 21]
        music = _minutes(events, "music")
        podcasts = _minutes(events, "podcast")
        days.append({
            "date": day, "events": events, "music": music, "podcasts": podcasts,
            "total": music + podcasts, "late": _minutes(late_events),
            "score": float(night.score), "hrv": night_metric(night, "hrv_ms"),
            "resting_hr": night_metric(night, "resting_hr"), "duration": night_metric(night, "duration_min"),
            "bedtime": night_metric(night, "bedtime_min"), "late_meeting": features.late_meeting_hours > 0,
            "meetings": features.n_meetings,
            "workouts": sum(1 for event in ds.events_on(day) if event.type == "workout"),
            "social": sum(1 for event in ds.events_on(day) if event.type == "social"),
        })

    insights: List[Dict[str, Any]] = []

    def add(title: str, detail: str, sample: int, kind: str = "association") -> None:
        insights.append({"title": title, "detail": detail, "sample": sample, "confidence": _confidence(sample), "kind": kind})

    if len(days) >= 3:
        score_days = [day for day in days if day["score"] is not None]
        late_corr = _corr([day["late"] for day in score_days], [day["score"] for day in score_days])
        if late_corr is not None:
            direction = "higher" if late_corr > 0 else "lower"
            add("Late-night listening and sleep", "On %d overlapping nights, more media after 21:00 was associated with %s sleep scores (r = %+.2f)." % (len(score_days), direction, late_corr), len(score_days), "sleep")

        music_days = [day for day in days if day["music"] > 0]
        podcast_days = [day for day in days if day["podcasts"] > 0]
        if music_days and podcast_days:
            music_score, podcast_score = _average(music_days, "score"), _average(podcast_days, "score")
            if music_score is not None and podcast_score is not None:
                add("Music nights versus podcast nights", "Music appeared on %d nights averaging %.0f sleep points; podcasts appeared on %d nights averaging %.0f." % (len(music_days), music_score, len(podcast_days), podcast_score), len(music_days) + len(podcast_days), "compare")

        hrv_days = [day for day in days if day["hrv"] is not None]
        music_hrv = _corr([day["music"] for day in hrv_days], [day["hrv"] for day in hrv_days])
        if music_hrv is not None:
            add("Music and overnight HRV", "Music minutes had a %s association with next-night HRV across %d nights (r = %+.2f)." % ("positive" if music_hrv > 0 else "negative", len(hrv_days), music_hrv), len(hrv_days), "recovery")

        meeting_days = [day for day in days if day["late_meeting"]]
        calm_days = [day for day in days if not day["late_meeting"]]
        if meeting_days and calm_days:
            meeting_late, calm_late = _average(meeting_days, "late"), _average(calm_days, "late")
            if meeting_late is not None and calm_late is not None:
                add("The meeting-night soundtrack", "After late-meeting days, you listened after 21:00 for %.0f minutes on average versus %.0f on calmer calendar days." % (meeting_late, calm_late), len(meeting_days) + len(calm_days), "calendar")

        bedtime_days = [day for day in days if day["bedtime"] is not None]
        bedtime_corr = _corr([day["late"] for day in bedtime_days], [day["bedtime"] for day in bedtime_days])
        if bedtime_corr is not None:
            add("Soundtrack versus bedtime", "Later listening tended to travel with a %s bedtime shift (r = %+.2f across %d nights)." % ("later" if bedtime_corr > 0 else "earlier", bedtime_corr, len(bedtime_days)), len(bedtime_days), "sleep")

    creator_days: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for day in days:
        creators = {str(row.get("creator")) for row in day["events"] if row.get("creator")}
        for creator in creators:
            creator_days[creator].append(day)
    creator_candidates = sorted(creator_days.items(), key=lambda item: len(item[1]), reverse=True)
    for creator, creator_day_rows in creator_candidates[:3]:
        if len(creator_day_rows) < 3:
            continue
        creator_score = _average(creator_day_rows, "score")
        if creator_score is not None:
            add("A recurring artist or show", "%s appeared on %d overlapping days averaging %.0f sleep points. This is a fun signature, not a verdict." % (creator, len(creator_day_rows), creator_score), len(creator_day_rows), "signature")

    headline = None
    if days:
        standout = max(days, key=lambda day: day["total"])
        creator_minutes: Dict[str, float] = defaultdict(float)
        for event in standout["events"]:
            if event.get("creator"):
                creator_minutes[str(event["creator"])] += float(event.get("minutes") or 0)
        creator = max(creator_minutes, key=creator_minutes.get) if creator_minutes else None
        calendar_bits = []
        if standout["workouts"]:
            calendar_bits.append("%d workout%s" % (standout["workouts"], "" if standout["workouts"] == 1 else "s"))
        if standout["meetings"]:
            calendar_bits.append("%d meeting%s" % (standout["meetings"], "" if standout["meetings"] == 1 else "s"))
        if standout["social"]:
            calendar_bits.append("a social evening")
        context = " and ".join(calendar_bits) if calendar_bits else "a fairly open calendar"
        subject = (creator + " more than anything else") if creator else "your media"
        headline = {
            "title": "Your most curious recent day",
            "detail": "%s you spent %.0f minutes with %s, alongside %s. Did that soundtrack fit the day?" % (standout["date"].strftime("%A"), standout["total"], subject, context),
            "date": standout["date"], "sample": len(days),
        }

    chart = [{"date": day["date"], "media_minutes": round(day["total"], 1), "music_minutes": round(day["music"], 1),
              "podcast_minutes": round(day["podcasts"], 1), "sleep_score": day["score"], "meetings": day["meetings"],
              "workouts": day["workouts"]} for day in days[-30:]]
    return {
        "available": bool(days), "overlap_days": len(days), "media_days": len(by_day),
        "health_calendar_days": max(0, (ds.end - ds.start).days + 1), "insights": insights, "headline": headline, "chart": chart,
        "note": "Associations use media dates that overlap the current health/calendar history. They are exploratory patterns, not causes; imported media is not fed into the sleep model.",
    }
