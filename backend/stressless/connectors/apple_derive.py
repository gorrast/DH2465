"""Apple Health / Screen Time: turn the raw rows the Apple importer (tools/apple-data) uploaded into derived rows.

The importer only appends raw ``source_records``; POST /api/apple/derive (server/apple_sync.py) reads them back and
calls these pure functions to fill the same derived tables the Android sync fills: ``sleep_nights`` (scored with the
same ``compute_score`` via device_sync), ``heart_rate_days``, ``daily_activity`` and ``daily_metrics`` (screen.*).

Raw rows arrive as PostgREST JSON with ``kind`` (the payload's apple_type) and ``stage`` (the sleep category value)
selected out of the payload, so the large payloads are never downloaded. Every timestamp carries its own
``start_offset_min``: local days and nights are cut with the offset the phone had when it was recorded.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import device_sync as ds

HEALTH = "apple_health"
SCREEN = "apple_screen_time"

HR = "HKQuantityTypeIdentifierHeartRate"
RHR = "HKQuantityTypeIdentifierRestingHeartRate"
HRV = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
RESP = "HKQuantityTypeIdentifierRespiratoryRate"
SPO2 = "HKQuantityTypeIdentifierOxygenSaturation"
TEMP = "HKQuantityTypeIdentifierAppleSleepingWristTemperature"
STEPS = "HKQuantityTypeIdentifierStepCount"
SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"
WORKOUT = "Workout"
ENERGY = "HKQuantityTypeIdentifierActiveEnergyBurned"
EXERCISE = "HKQuantityTypeIdentifierAppleExerciseTime"
STAND = "HKCategoryTypeIdentifierAppleStandHour"
VO2MAX = "HKQuantityTypeIdentifierVO2Max"
WALKING_HR = "HKQuantityTypeIdentifierWalkingHeartRateAverage"
MINDFUL = "HKCategoryTypeIdentifierMindfulSession"

# data_type keys the importer stores these under (health_to_supabase.py): the canonical key when the unit matched,
# otherwise its ah_* name. Both are read; the payload's apple_type decides what a row is.
HEALTH_DATA_TYPES = ("heart_rate", "ah_heart_rate", "resting_heart_rate", "ah_resting_heart_rate", "hrv_sdnn",
                     "ah_heart_rate_variability_sdnn", "steps", "ah_step_count", "ah_sleep_analysis",
                     "ah_respiratory_rate", "ah_oxygen_saturation", "ah_apple_sleeping_wrist_temperature",
                     # Apple-only daily values (health_metric_rows), nothing like them comes from Android
                     "ah_active_energy_burned", "ah_apple_exercise_time", "ah_apple_stand_hour", "ah_vo2_max",
                     "ah_walking_heart_rate_average", "ah_mindful_session")
WORKOUT_DATA_TYPE = "ah_workout"
SCREEN_DATA_TYPE = "app_usage"

SESSION_GAP = timedelta(minutes=90)   # sleep segments further apart than this are separate sessions (a nap, the night)
TEMP_BASELINE_MIN_NIGHTS = 3


# ------------------------------------------------------------------ parsing --
def _sample(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A raw row as {kind, start, end, offset, origin, value, stage}; None when unusable."""
    try:
        start = ds._ts(r.get("start_at"), "start_at")
        end = ds._ts(r["end_at"], "end_at") if r.get("end_at") else start
    except ValueError:
        return None
    try:
        value = float(r["value"]) if r.get("value") is not None else None
    except (TypeError, ValueError):
        value = None
    return {"kind": r.get("kind") or "", "start": start, "end": max(start, end), "offset": int(r.get("start_offset_min") or 0),
            "origin": r.get("data_origin"), "value": value, "stage": r.get("stage"), "payload": r.get("payload")}


def parse(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group raw rows by apple_type."""
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        s = _sample(r)
        if s is not None:
            out[s["kind"]].append(s)
    for v in out.values():
        v.sort(key=lambda s: s["start"])
    return out


def _local_day(s: Dict[str, Any]) -> date:
    return ds.local(s["start"], s["offset"]).date()


def _median(vals: List[float]) -> Optional[float]:
    return float(statistics.median(vals)) if vals else None


# -------------------------------------------------------------------- sleep --
def _stage_kind(raw: Optional[str]) -> str:
    return ds.stage_name((raw or "").replace("HKCategoryValueSleepAnalysis", ""))


def sleep_sessions(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sleep segments -> device_sync-shaped sessions: per recording app, segments joined until a 90-minute gap."""
    by_origin: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        if _stage_kind(s["stage"]) != "unknown" and s["end"] > s["start"]:
            by_origin[s["origin"]].append(s)
    sessions: List[Dict[str, Any]] = []
    for origin, segs in by_origin.items():
        segs.sort(key=lambda s: s["start"])
        cur: List[Dict[str, Any]] = []
        for s in segs:
            if cur and s["start"] > max(x["end"] for x in cur) + SESSION_GAP:
                sessions.append(_session(origin, cur))
                cur = []
            cur.append(s)
        if cur:
            sessions.append(_session(origin, cur))
    # A phone's plain "in bed" next to a watch's staged night would otherwise count as all asleep and win the night.
    staged = {ds.night_of(s["start"], s["offset"])[0] for s in sessions if any(st["kind"] in ds.ASLEEP for st in s["stages"])}
    return sorted((s for s in sessions if ds.night_of(s["start"], s["offset"])[0] not in staged
                   or any(st["kind"] in ds.ASLEEP for st in s["stages"])), key=lambda s: s["start"])


def _session(origin: Optional[str], segs: List[Dict[str, Any]]) -> Dict[str, Any]:
    start, end = min(s["start"] for s in segs), max(s["end"] for s in segs)
    stages = [{"start": s["start"], "end": s["end"], "raw": s["stage"], "kind": _stage_kind(s["stage"])} for s in segs]
    return {"id": "apple:%s:%d" % (origin or "", int(start.timestamp())), "start": start, "end": end,
            "offset": segs[0]["offset"], "origin": origin, "modified": None, "stages": stages}


def sleep_night_rows(raw: Dict[str, List[Dict[str, Any]]], earlier_bedtimes: Optional[List[float]] = None,
                     first: Optional[date] = None, last: Optional[date] = None) -> List[Dict[str, Any]]:
    """Scored nights (device_sync's scoring) with the watch's overnight vitals added."""
    sessions = sleep_sessions(raw.get(SLEEP, []))
    rows = ds.sleep_night_rows({"sleep": sessions}, earlier_bedtimes)
    rows = [r for r in rows if (first is None or r["night_date"] >= first.isoformat())
            and (last is None or r["night_date"] <= last.isoformat())]
    rhr_by_night: Dict[str, List[float]] = defaultdict(list)
    for s in raw.get(RHR, []):   # Apple's resting HR for a day describes the night that ended that morning
        if s["value"] is not None:
            rhr_by_night[(_local_day(s) - timedelta(days=1)).isoformat()].append(s["value"])
    temps: Dict[str, Optional[float]] = {}
    for r in rows:
        lo, hi = ds._ts(r["in_bed_at"], ""), ds._ts(r["out_of_bed_at"], "")
        inside = lambda kind, pad=timedelta(0): [s["value"] for s in raw.get(kind, [])
                                                 if s["value"] is not None and lo - pad <= s["start"] <= hi + pad]
        spo2 = _median([v * 100.0 if v <= 1.0 else v for v in inside(SPO2)])
        rhr = _median(rhr_by_night.get(r["night_date"], []))
        temps[r["night_date"]] = _median(inside(TEMP, timedelta(hours=1)))
        r.update(source=HEALTH, hrv_sdnn_ms=_round(_median(inside(HRV)), 1), resp_rate=_round(_median(inside(RESP)), 1),
                 spo2=_round(spo2, 1), resting_hr=int(round(rhr)) if rhr is not None else None, skin_temp_dev=None)
    known = [t for t in temps.values() if t is not None]
    if len(known) >= TEMP_BASELINE_MIN_NIGHTS:   # Apple reports absolute wrist temperature; the app wants a deviation
        base = statistics.median(known)
        for r in rows:
            t = temps[r["night_date"]]
            r["skin_temp_dev"] = round(t - base, 2) if t is not None else None
    return rows


def _round(v: Optional[float], n: int) -> Optional[float]:
    return round(v, n) if v is not None else None


# --------------------------------------------------------------- heart rate --
def heart_rate_day_rows(raw: Dict[str, List[Dict[str, Any]]], first: date, last: date) -> List[Dict[str, Any]]:
    """Per local day: the mean bpm of every minute (1440 slots, null where nothing was measured)."""
    slots: Dict[date, List[List[float]]] = {}
    offsets: Dict[date, Counter] = defaultdict(Counter)
    origins: Dict[date, Counter] = defaultdict(Counter)
    for s in raw.get(HR, []):
        if s["value"] is None or not 20 <= s["value"] <= 250:
            continue
        loc = ds.local(s["start"], s["offset"])
        d = loc.date()
        if not first <= d <= last:
            continue
        slot = slots.setdefault(d, [[0.0, 0] for _ in range(1440)])[loc.hour * 60 + loc.minute]
        slot[0] += s["value"]
        slot[1] += 1
        offsets[d][s["offset"]] += 1
        origins[d][s["origin"]] += 1
    rows = []
    for d in sorted(slots):
        bpm = [int(round(t / n)) if n else None for t, n in slots[d]]
        rows.append({"day": d.isoformat(), "source": HEALTH, "data_origin": origins[d].most_common(1)[0][0],
                     "utc_offset_min": offsets[d].most_common(1)[0][0], "bpm": bpm,
                     "worn_minutes": sum(1 for b in bpm if b is not None)})
    return rows


# ----------------------------------------------------------------- activity --
def _workout_kind(payload: Any) -> str:
    attrs = (payload or {}).get("attributes") or {}
    k = (attrs.get("workoutActivityType") or "").replace("HKWorkoutActivityType", "").lower()
    if "running" in k:
        return "run"
    if "cycling" in k:
        return "cycling"
    if "yoga" in k:
        return "yoga"
    if "strength" in k or "functional" in k:
        return "strength"
    return "other"


def _workout_calories(payload: Any) -> int:
    payload = payload or {}
    attrs = payload.get("attributes") or {}
    try:
        if attrs.get("totalEnergyBurned"):
            return int(float(attrs["totalEnergyBurned"]))
        for child in payload.get("children") or []:   # newer exports: <WorkoutStatistics type=... sum=...>
            a = child.get("attributes") or {}
            if child.get("tag") == "WorkoutStatistics" and a.get("type") == ENERGY and a.get("sum"):
                return int(float(a["sum"]))
    except (TypeError, ValueError):
        pass
    return 0


def activity_rows(raw: Dict[str, List[Dict[str, Any]]], first: date, last: date) -> List[Dict[str, Any]]:
    """Per local day: steps from the app that counted the most (iPhone and Watch both count the same steps, so
    they are never added together), hourly steps, and the day's workouts with heart rate from the HR samples."""
    by_origin: Dict[date, Dict[Optional[str], List[int]]] = defaultdict(lambda: defaultdict(lambda: [0] * 24))
    offsets: Dict[date, Counter] = defaultdict(Counter)
    for s in raw.get(STEPS, []):
        if s["value"] is None or s["value"] < 0:
            continue
        loc = ds.local(s["start"], s["offset"])
        if first <= loc.date() <= last:
            by_origin[loc.date()][s["origin"]][loc.hour] += int(round(s["value"]))
            offsets[loc.date()][s["offset"]] += 1
    hr = [s for s in raw.get(HR, []) if s["value"] is not None]
    workouts: Dict[date, List[Dict[str, Any]]] = defaultdict(list)
    for w in raw.get(WORKOUT, []):
        d = _local_day(w)
        if not first <= d <= last or w["end"] <= w["start"]:
            continue
        beats = [s["value"] for s in hr if w["start"] <= s["start"] <= w["end"]]
        workouts[d].append({"kind": _workout_kind(w["payload"]), "start": ds.iso(w["start"]), "end": ds.iso(w["end"]),
                            "avg_hr": int(round(statistics.mean(beats))) if beats else 0,
                            "max_hr": int(max(beats)) if beats else 0, "calories": _workout_calories(w["payload"]),
                            "data_origin": w["origin"]})
        offsets[d][w["offset"]] += 1
    exercise = _per_day_best_origin(raw.get(EXERCISE, []), first, last)
    rows = []
    for d in sorted(set(by_origin) | set(workouts) | set(exercise)):
        hourly = max(by_origin[d].values(), key=sum) if by_origin.get(d) else []
        ws = workouts.get(d, [])
        # Apple's exercise minutes (the green ring) when there are any, otherwise the workouts' length
        active = exercise[d] if d in exercise else sum(ds._minutes(ds._ts(w["start"], ""), ds._ts(w["end"], "")) for w in ws)
        if not offsets[d]:
            offsets[d][next(s["offset"] for s in raw[EXERCISE] if _local_day(s) == d)] += 1
        rows.append({"day": d.isoformat(), "source": HEALTH, "utc_offset_min": offsets[d].most_common(1)[0][0],
                     "steps": sum(hourly) if hourly else None, "active_min": min(1440, int(active)),
                     "hourly_steps": hourly, "workouts": ws})
    return rows


def _per_day_best_origin(samples: List[Dict[str, Any]], first: date, last: date) -> Dict[date, float]:
    """Per local day, the total of the app that recorded the most (the iPhone and the Watch count the same things)."""
    sums: Dict[date, Dict[Optional[str], float]] = defaultdict(lambda: defaultdict(float))
    for s in samples:
        if s["value"] is not None and s["value"] >= 0 and first <= _local_day(s) <= last:
            sums[_local_day(s)][s["origin"]] += s["value"]
    return {d: max(by.values()) for d, by in sums.items()}


def _per_day(samples: List[Dict[str, Any]], first: date, last: date) -> Dict[date, List[Dict[str, Any]]]:
    out: Dict[date, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        if first <= _local_day(s) <= last:
            out[_local_day(s)].append(s)
    return out


# Apple-only per-day values: (metric_key, how a day's samples become one number)
HEALTH_METRICS = ("health.active_energy", "health.exercise_min", "health.stand_hours", "health.vo2max",
                  "health.walking_hr", "health.hrv_sdnn_day", "health.mindful_min")


def health_metric_rows(raw: Dict[str, List[Dict[str, Any]]], first: date, last: date) -> List[Dict[str, Any]]:
    """daily_metrics rows for what the Apple export has beyond the derived tables (see HEALTH_METRICS)."""
    vals: Dict[str, Dict[date, float]] = {
        "health.active_energy": _per_day_best_origin(raw.get(ENERGY, []), first, last),
        "health.exercise_min": _per_day_best_origin(raw.get(EXERCISE, []), first, last),
    }
    median_of = lambda kind: {d: statistics.median(v) for d, ss in _per_day(raw.get(kind, []), first, last).items()
                              if (v := [s["value"] for s in ss if s["value"] is not None])}
    vals["health.vo2max"] = median_of(VO2MAX)
    vals["health.walking_hr"] = median_of(WALKING_HR)
    vals["health.hrv_sdnn_day"] = median_of(HRV)        # all day, not only overnight like sleep_nights.hrv_sdnn_ms
    vals["health.stand_hours"] = {d: len({ds.local(s["start"], s["offset"]).hour for s in ss
                                          if (s["stage"] or "").endswith("Stood")})
                                  for d, ss in _per_day(raw.get(STAND, []), first, last).items()}
    vals["health.mindful_min"] = {d: sum(ds._minutes(s["start"], s["end"]) for s in ss)
                                  for d, ss in _per_day(raw.get(MINDFUL, []), first, last).items()}
    return [{"day": d.isoformat(), "metric_key": key, "value": round(v, 1), "source": HEALTH}
            for key in HEALTH_METRICS for d, v in sorted(vals[key].items())]


# ------------------------------------------------------------- screen time --
def screen_metric_rows(rows: Iterable[Dict[str, Any]], first: date, last: date) -> List[Dict[str, Any]]:
    """screen.minutes and screen.late_minutes per local day, from the app-usage sessions. Sessions on the Mac and
    the iPhone that overlap are counted once (the union of the intervals). Unlocks are not in the Apple data."""
    spans = sorted((s["start"], s["end"], s["offset"]) for s in (_sample(r) for r in rows) if s and s["end"] > s["start"])
    merged: List[List[Any]] = []
    for a, b, off in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b, off])
    if not merged:
        return []
    days: Dict[date, Dict[str, float]] = {}
    lo = max(first, ds.local(merged[0][0], merged[0][2]).date())
    hi = min(last, ds.local(merged[-1][1], merged[-1][2]).date())
    for i in range((hi - lo).days + 1):
        days[lo + timedelta(days=i)] = {"minutes": 0.0, "late_minutes": 0.0}
    for a, b, off in merged:
        la, lb = ds.local(a, off), ds.local(b, off)
        d = la.date() - timedelta(days=1)
        while d <= lb.date():
            if d in days:
                midnight = datetime.combine(d, time(0, 0))
                days[d]["minutes"] += ds._overlap(la, lb, midnight, midnight + timedelta(days=1))
                days[d]["late_minutes"] += ds._overlap(la, lb, midnight + timedelta(hours=ds.LATE_FROM_H),
                                                       midnight + timedelta(days=1, hours=ds.LATE_TO_H))
            d += timedelta(days=1)
    return [{"day": d.isoformat(), "metric_key": "screen." + k, "value": round(v, 1), "source": SCREEN}
            for d, vals in sorted(days.items()) for k, v in vals.items()]

