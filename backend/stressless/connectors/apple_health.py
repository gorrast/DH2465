"""Streaming Apple Health export.xml importer (SPEC §6.1). Never loads the file into memory."""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from ..models import DailyActivity, HeartRateDay, SleepNight, SleepStage, WatchWorkout, new_id
from ..timeutil import night_date
from .base import parse_ts

log = logging.getLogger("stressless.connectors.apple_health")

HR = "HKQuantityTypeIdentifierHeartRate"
HRV = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
RHR = "HKQuantityTypeIdentifierRestingHeartRate"
RESP = "HKQuantityTypeIdentifierRespiratoryRate"
SPO2 = "HKQuantityTypeIdentifierOxygenSaturation"
TEMP = "HKQuantityTypeIdentifierAppleSleepingWristTemperature"
STEPS = "HKQuantityTypeIdentifierStepCount"
SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"
SLEEP_KINDS = {"HKCategoryValueSleepAnalysisAsleepCore": "core", "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
               "HKCategoryValueSleepAnalysisAsleepREM": "rem", "HKCategoryValueSleepAnalysisAsleepUnspecified": "core",
               "HKCategoryValueSleepAnalysisAsleep": "core", "HKCategoryValueSleepAnalysisAwake": "awake",
               "HKCategoryValueSleepAnalysisInBed": "inbed"}


def parse_export(path: str, tzname: str, start: date, end: date) -> Tuple[List[HeartRateDay], List[SleepNight], List[DailyActivity]]:
    lo_s = (start - timedelta(days=1)).isoformat()
    hi_s = (end + timedelta(days=1)).isoformat()
    hr_sum: Dict[date, List[List[float]]] = {}
    per_night: Dict[str, Dict[date, List[float]]] = defaultdict(lambda: defaultdict(list))
    steps: Dict[date, float] = defaultdict(float)
    sleep_segs: Dict[date, Dict[str, List[Tuple[datetime, datetime, str]]]] = defaultdict(lambda: defaultdict(list))
    workouts: Dict[date, List[WatchWorkout]] = defaultdict(list)
    root = None
    count = 0
    for event, el in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            if root is None:
                root = el
            continue
        if el.tag not in ("Record", "Workout"):
            continue
        count += 1
        sd = el.get("startDate", "")
        if sd[:10] < lo_s or sd[:10] > hi_s:
            el.clear()
            if count % 10000 == 0 and root is not None:
                root.clear()
            continue
        try:
            s_dt = parse_ts(sd, tzname)
            e_dt = parse_ts(el.get("endDate", sd), tzname)
        except ValueError:
            el.clear()
            continue
        if el.tag == "Workout":
            kind = (el.get("workoutActivityType", "") or "").replace("HKWorkoutActivityType", "").lower() or "other"
            kind = "run" if "running" in kind else ("cycling" if "cycling" in kind else ("yoga" if "yoga" in kind else ("strength" if ("strength" in kind or "functional" in kind) else "other")))
            d = s_dt.date()
            workouts[d].append(WatchWorkout(id=new_id("wk", d, len(workouts[d])), kind=kind, start=s_dt, end=e_dt, avg_hr=0, max_hr=0,
                                            calories=int(float(el.get("totalEnergyBurned", "0") or 0))))
        else:
            t = el.get("type")
            try:
                val = float(el.get("value", "nan"))
            except ValueError:
                val = float("nan")
            if t == HR and val == val:
                d = s_dt.date()
                slot = hr_sum.setdefault(d, [[0.0, 0.0] for _ in range(1440)])[s_dt.hour * 60 + s_dt.minute]
                slot[0] += val
                slot[1] += 1
            elif t in (HRV, RHR, RESP, SPO2, TEMP) and val == val:
                if t == SPO2 and val <= 1.0:
                    val *= 100.0
                nd = night_date(s_dt) if t in (HRV, RESP, SPO2, TEMP) else s_dt.date() - timedelta(days=1)
                per_night[t][nd].append(val)
            elif t == STEPS and val == val:
                steps[s_dt.date()] += val
            elif t == SLEEP:
                kind = SLEEP_KINDS.get(el.get("value", ""), None)
                if kind:
                    src = el.get("sourceName", "")
                    sleep_segs[night_date(s_dt)][src].append((s_dt, e_dt, kind))
        el.clear()
        if count % 10000 == 0 and root is not None:
            root.clear()

    hr_days = [HeartRateDay(date=d, bpm=[int(round(s / c)) if c else None for s, c in slots]) for d, slots in sorted(hr_sum.items())]
    temp_all = sorted(per_night[TEMP].items())
    temp_base = statistics.median([statistics.median(v) for _, v in temp_all[:14]]) if temp_all else None
    nights: List[SleepNight] = []
    from ..sim.sleep_score import compute_score
    recent_bed: List[float] = []
    for nd in sorted(set(list(sleep_segs.keys()) + list(per_night[HRV].keys()))):
        if nd < start or nd > end:
            continue
        srcs = sleep_segs.get(nd, {})
        chosen = None
        if srcs:
            watch = [s for s in srcs if "watch" in s.lower()]
            chosen = srcs[watch[0]] if watch else srcs[max(srcs, key=lambda k: len(srcs[k]))]
        if not chosen:
            nights.append(SleepNight(date=nd, worn=False))
            continue
        segs = sorted(chosen, key=lambda x: x[0])
        asleep = [x for x in segs if x[2] in ("core", "deep", "rem")]
        inbed = [x for x in segs if x[2] == "inbed"] or asleep
        stages = [SleepStage(kind=k, start=s, end=e) for s, e, k in segs if k != "inbed"]
        onset = min(x[0] for x in asleep) if asleep else inbed[0][0]
        wake = max(x[1] for x in asleep) if asleep else inbed[-1][1]
        bed = min(x[0] for x in inbed)
        mins = lambda k: int(sum((e - s).total_seconds() for s, e, kk in segs if kk == k) // 60)
        duration = mins("core") + mins("deep") + mins("rem")
        awake = mins("awake")
        interruptions = sum(1 for x in segs if x[2] == "awake")
        bed_min = (bed - datetime.combine(nd, datetime.min.time(), tzinfo=bed.tzinfo)).total_seconds() / 60.0 - 720.0
        score, parts = compute_score({"duration_min": duration, "bedtime_min": bed_min, "interruptions": interruptions, "awake_min": awake, "sleep_need_min": 450}, recent_bed)
        recent_bed = (recent_bed + [bed_min])[-14:]
        med = lambda t: (statistics.median(per_night[t][nd]) if per_night[t].get(nd) else None)
        temp_dev = (med(TEMP) - temp_base) if (med(TEMP) is not None and temp_base is not None) else None
        nights.append(SleepNight(date=nd, worn=True, in_bed_start=bed, sleep_onset=onset, wake_time=wake, out_of_bed=max(x[1] for x in inbed),
                                 stages=stages, interruptions=interruptions, awake_min=awake, duration_min=duration, deep_min=mins("deep"),
                                 rem_min=mins("rem"), core_min=mins("core"), hrv_ms=med(HRV), resting_hr=int(round(med(RHR))) if med(RHR) is not None else None,
                                 resp_rate=med(RESP), wrist_temp_dev=round(temp_dev, 2) if temp_dev is not None else None, spo2=med(SPO2),
                                 score=score, score_parts=parts, score_source="stressless"))
    activity = [DailyActivity(date=d, steps=int(steps.get(d, 0)), active_minutes=sum(int((w.end - w.start).total_seconds() // 60) for w in workouts.get(d, [])),
                              workouts=workouts.get(d, [])) for d in sorted(set(list(steps.keys()) + list(workouts.keys()))) if start <= d <= end]
    return hr_days, nights, activity
