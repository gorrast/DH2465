"""Causal physiology model of the digital twin (SPEC §5.4).

Given a day's attended events, location visits, hidden factors and pre-drawn noise, produce the
minute heart rate, activity, the night's sleep and the ground-truth contribution of every factor
(computed by re-running the night without that factor on the same noise draws).
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..models import (CalendarEvent, DailyActivity, DayFeatures, HeartRateDay, LocationVisit,
                      Persona, SimTruthNight, SleepNight, SleepStage, WatchWorkout, new_id)
from ..timeutil import at, day_hour
from .sleep_score import compute_score

NOISE_SITES = ("bed", "onset", "wake", "awake", "hrv_ln", "rhr", "resp", "temp", "spo2", "life", "jitter")
INTENSE_WORDS = ("board", "review", "interview", "pitch", "customer", "investor", "escalation", "planning")
CALENDAR_KEYS = ("meetings_over_3", "b2b_over_2", "late_meeting_hours", "evening_social", "workout_morning",
                 "workout_late", "travel", "early_start", "protected_evening")


def draw_noise(rng: random.Random) -> Dict[str, float]:
    noise = {k: rng.gauss(0.0, 1.0) for k in NOISE_SITES}
    noise["interrupt_u"] = rng.random()
    noise["gap_u"] = rng.random()
    noise["gap_pos"] = rng.random()
    noise["walks"] = [(rng.uniform(10.0, 19.0), rng.randint(10, 20), rng.uniform(20, 30)) for _ in range(rng.randint(2, 4))]
    noise["ar_seed"] = rng.random()
    return noise


def poisson_invcdf(lam: float, u: float) -> int:
    """Inverse-CDF Poisson draw so a smaller lambda never gives a larger count for the same u."""
    if lam <= 0:
        return 0
    k = 0
    p = math.exp(-lam)
    cdf = p
    while u > cdf and k < 60:
        k += 1
        p *= lam / k
        cdf += p
    return k


def to_night_min(hour: float) -> float:
    """Clock hour -> minutes after 12:00 of the night date (23:05 -> 665, 00:15 -> 735)."""
    h = hour + 24.0 if hour < 12.0 else hour
    return h * 60.0 - 720.0


def night_min_to_dt(night_date: date, m: float, tzname: str):
    return at(night_date, 12.0, tzname=tzname) + timedelta(minutes=m)


# --------------------------------------------------------------------------- #
# Sleep mechanics
# --------------------------------------------------------------------------- #
def compute_sleep(persona: Persona, ratios: Dict[str, float], reg: Dict[str, float], hidden: Dict[str, Any],
                  noise: Dict[str, float], debt: float, last_event_end_min: Optional[float],
                  recent_bedtimes: Sequence[float], weekend: bool) -> Dict[str, Any]:
    r = ratios
    late_h = reg.get("late_meeting_hours", 0.0) * r["late_meeting_hours"]
    m3 = reg.get("meetings_over_3", 0.0) * r["meetings_over_3"]
    b2b = reg.get("b2b_over_2", 0.0) * r["b2b_over_2"]
    soc = reg.get("evening_social", 0.0) * r["evening_social"]
    wl = reg.get("workout_late", 0.0) * r["workout_late"]
    wm = reg.get("workout_morning", 0.0) * r["workout_morning"]
    trv = reg.get("travel", 0.0) * r["travel"]
    es = reg.get("early_start", 0.0) * r["early_start"]
    prot = reg.get("protected_evening", 0.0) * r["protected_evening"]
    alc = float(hidden.get("alcohol_units", 0) or 0)
    caff = 1.0 if hidden.get("caffeine_late") else 0.0
    screens = 1.0 if hidden.get("screens_late") else 0.0
    ill = 1.0 if hidden.get("illness") else 0.0
    wl_flag = 1.0 if reg.get("workout_late", 0.0) > 0 else 0.0

    shift = persona.weekend_shift_min if weekend else 0.0
    usual_bed = to_night_min(persona.usual_bedtime) + 0.6 * shift + 12.0 * noise["jitter"]
    bed_delay = (20 * late_h + 45 * soc + 20 * wl + 20 * trv - 10 * prot + 20 * screens - 0.05 * debt + 14 * noise["bed"])
    bedtime = usual_bed + bed_delay
    if last_event_end_min is not None:
        bedtime = max(bedtime, last_event_end_min + 30.0)
    onset = max(3.0, 12 + 6 * late_h + 10 * wl + 3 * m3 + 4 * b2b + 5 * caff - 3 * wm - 6 * prot - 0.02 * debt + 4 * noise["onset"])
    lam = max(0.2, 1.0 + 0.3 * alc + 0.3 * m3 + 0.5 * trv + 0.8 * ill - 0.3 * wm - 0.4 * prot)
    interrupt = poisson_invcdf(lam, noise["interrupt_u"])
    awake = max(0.0, 8 + 10 * interrupt - 4 * wm - 4 * prot - 0.03 * debt + 4 * noise["awake"])
    wake = to_night_min(persona.usual_wake) - 45 * es + 8 * noise["wake"] + 8 * noise["life"]
    if weekend:
        wake += shift + min(120.0, 0.5 * max(0.0, bed_delay))
    wake = max(wake, bedtime + onset + awake + 180.0)
    duration = wake - (bedtime + onset) - awake

    hrv = persona.hrv_ms * (1 - 0.03 * m3 - 0.05 * late_h - min(0.30, 0.06 * alc) - 0.07 * wl + 0.05 * wm - 0.10 * trv - 0.20 * ill)
    hrv = max(8.0, hrv) * math.exp(0.18 * noise["hrv_ln"])
    rhr = persona.resting_hr + 1.2 * m3 + 1.8 * late_h + min(1.2 * alc, 5.0) + 2.5 * wl - 1.5 * wm + 3 * trv + 7 * ill + 1.5 * noise["rhr"]
    resp = persona.resp_rate + 0.7 * (1 if alc > 0 else 0) + 1.5 * ill + 0.3 * noise["resp"]
    temp = 0.25 * (1 if alc > 0 else 0) + 0.5 * ill + 0.15 * trv + 0.12 * noise["temp"]
    spo2 = max(92.0, min(100.0, 97.5 - 0.4 * (1 if alc > 0 else 0) - 0.3 * ill + 0.4 * noise["spo2"]))
    deep_share = 0.20 * (1 - 0.05 * (1 if alc > 0 else 0) - 0.15 * wl_flag)
    rem_share = 0.22 * (1 - min(0.35, 0.10 * alc))

    score, parts = compute_score({"duration_min": duration, "bedtime_min": bedtime, "interruptions": interrupt,
                                  "awake_min": awake, "sleep_need_min": persona.sleep_need_min}, list(recent_bedtimes))
    return {"bedtime": bedtime, "onset": onset, "interrupt": interrupt, "awake": awake, "wake": wake,
            "duration": duration, "hrv": hrv, "rhr": rhr, "resp": resp, "temp": temp, "spo2": spo2,
            "deep_share": deep_share, "rem_share": rem_share, "score": score, "parts": parts, "bed_delay": bed_delay}


def build_stages(night_date: date, tzname: str, sp: Dict[str, Any]) -> List[SleepStage]:
    """4–5 cycles of ~90 min; deep front-loaded, REM back-loaded; interruptions at cycle boundaries."""
    duration = sp["duration"]
    n = 4 if duration < 420 else 5
    deep_w = [0.35, 0.25, 0.12, 0.05, 0.0][:n]
    rem_w = [0.05, 0.15, 0.25, 0.35, 0.40][:n]
    cycle = duration / n
    deep_total = sp["deep_share"] * duration
    rem_total = sp["rem_share"] * duration
    sd, sr = sum(deep_w) or 1.0, sum(rem_w) or 1.0
    n_awake = int(sp["interrupt"])
    awake_each = (sp["awake"] / n_awake) if n_awake else 0.0
    stages: List[SleepStage] = []
    t = sp["bedtime"] + sp["onset"]
    base = at(night_date, 12.0, tzname=tzname)

    def push(kind: str, minutes: float) -> None:
        nonlocal t
        if minutes <= 0.5:
            return
        stages.append(SleepStage(kind=kind, start=base + timedelta(minutes=t), end=base + timedelta(minutes=t + minutes)))
        t += minutes

    for i in range(n):
        deep = deep_total * deep_w[i] / sd
        rem = rem_total * rem_w[i] / sr
        core = max(0.0, cycle - deep - rem)
        push("core", core * 0.55)
        push("deep", deep)
        push("core", core * 0.45)
        push("rem", rem)
        if i < n_awake and i < n - 1:
            push("awake", awake_each)
    if n_awake > n - 1:
        push("awake", awake_each * (n_awake - (n - 1)))
    return stages


# --------------------------------------------------------------------------- #
# Heart rate
# --------------------------------------------------------------------------- #
def _sleep_hr(rhr: float, frac: float) -> float:
    """U-shaped sleeping HR: nadir mid-night; ``frac`` in [0,1] through the night."""
    return rhr - 6.0 + 3.0 * math.cos(2 * math.pi * (frac - 0.5)) * -1.0


def workout_profile(kind: str) -> Tuple[float, float]:
    return {"run": (140.0, 168.0), "cycling": (130.0, 155.0), "strength": (115.0, 145.0), "yoga": (95.0, 110.0)}.get(kind, (118.0, 142.0))


def event_kind(ev: CalendarEvent) -> str:
    notes = ev.notes or ""
    if "kind=" in notes:
        return notes.split("kind=")[1].split(";")[0].strip()
    t = (ev.title or "").lower()
    if "run" in t:
        return "run"
    if "yoga" in t:
        return "yoga"
    return "strength"


def build_hr(persona: Persona, d: date, attended: Sequence[CalendarEvent], visits: Sequence[LocationVisit],
             features: DayFeatures, hidden: Dict[str, Any], sp: Dict[str, Any], state: Dict[str, Any],
             noise: Dict[str, Any], rng: random.Random, unworn_tonight: bool, force_no_gap: bool,
             partial_until: Optional[int] = None) -> Tuple[List[Optional[int]], List[WatchWorkout], Dict[str, Any]]:
    tz = persona.tz
    base_awake = persona.resting_hr + 12.0
    arr = [base_awake] * 1440
    ill = 7.0 if hidden.get("illness") else 0.0

    # --- morning: tail of the previous night
    prev_wake = int(state.get("wake_min_today", 7 * 60))
    prev_rhr = float(state.get("prev_rhr", persona.resting_hr))
    prev_len = float(state.get("prev_sleep_len", 450.0))
    prev_bed_before_midnight = float(state.get("prev_min_before_midnight", 60.0))
    for m in range(0, min(1440, max(0, prev_wake))):
        frac = (prev_bed_before_midnight + m) / max(1.0, prev_len)
        arr[m] = _sleep_hr(prev_rhr, min(1.0, frac))
    for m, span in state.get("awake_spans_today", []):
        for k in range(max(0, m), min(1440, m + span)):
            arr[k] += 10.0
    for k in range(30):
        m = prev_wake + k
        if 0 <= m < 1440:
            arr[m] = _sleep_hr(prev_rhr, 1.0) + (base_awake - _sleep_hr(prev_rhr, 1.0)) * (k / 30.0)

    add = [0.0] * 1440

    def bump(start_min: int, end_min: int, amount: float) -> None:
        for k in range(max(0, start_min), min(1440, end_min)):
            add[k] += amount

    # --- walking: commute/transit segments and random walks
    for v in visits:
        if v.start.date() != d or v.place_type != "transit":
            continue
        s = int(day_hour(v.start, d) * 60)
        e = int(day_hour(v.end, d) * 60)
        walk = min(e - s, 12)
        bump(s, s + walk, 22.0)
        bump(e - min(8, e - s), e, 18.0)
    for (h, minutes, amount) in noise.get("walks", []):
        s = int(h * 60)
        bump(s, s + minutes, amount)

    # --- meetings: arousal during + decay after; chains accumulate (cap +18)
    meeting_add = [0.0] * 1440
    for ev in attended:
        if ev.type != "meeting":
            continue
        s = int(day_hour(ev.start, d) * 60)
        e = int(day_hour(ev.end, d) * 60)
        title = (ev.title or "").lower()
        intensity = 4.0 + (5.0 if any(w in title for w in INTENSE_WORDS) else 0.0) + min(5.0, ev.attendees / 2.0)
        for k in range(max(0, s), min(1440, e)):
            meeting_add[k] += intensity
        for k in range(max(0, e), min(1440, e + 120)):
            meeting_add[k] += intensity * math.exp(-(k - e) / 40.0)
    for k in range(1440):
        add[k] += min(18.0, meeting_add[k])

    # --- late meeting: evening arousal persists
    if features.late_meeting_hours > 0 and features.last_meeting_end_hour is not None:
        e = int(features.last_meeting_end_hour * 60)
        plateau = 5.0 + 5.0 * rng.random()
        hold = 60 + int(60 * rng.random())
        bump(e, e + hold, plateau)
        for k in range(e + hold, min(1440, e + hold + 120)):
            add[k] += plateau * math.exp(-(k - e - hold) / 40.0)

    # --- social
    for ev in attended:
        if ev.type == "social":
            s = int(day_hour(ev.start, d) * 60)
            e = int(day_hour(ev.end, d) * 60)
            bump(s, e, 8.0 + 4.0 * rng.random())

    # --- workouts: attended events and unbooked gym visits
    workouts: List[Tuple[int, int, str]] = []
    for ev in attended:
        if ev.type == "workout":
            workouts.append((int(day_hour(ev.start, d) * 60), int(day_hour(ev.end, d) * 60), event_kind(ev)))
    for v in visits:
        if v.start.date() == d and v.place_type == "gym":
            s = int(day_hour(v.start, d) * 60)
            e = int(day_hour(v.end, d) * 60)
            if not any(ws <= s + 5 <= we or ws <= e - 5 <= we for ws, we, _ in workouts):
                workouts.append((s + 5, e - 5, "strength"))
    for s, e, kind in workouts:
        lo, hi = workout_profile(kind)
        peak = lo + (hi - lo) * rng.random()
        for k in range(max(0, s), min(1440, e)):
            frac = (k - s) / max(1.0, (e - s))
            level = peak * (0.6 + 0.4 * min(1.0, frac * 6)) + 6.0 * math.sin(k / 3.0)
            arr[k] = level
            add[k] = 0.0
        for k in range(max(0, e), min(1440, e + 45)):
            arr[k] = base_awake + (peak - base_awake) * math.exp(-(k - e) / 20.0)

    # --- tonight: sleep portion within this day
    bed_min_of_day = int(sp["bedtime"] + 720)          # minutes after midnight of d (may be >= 1440)
    alc = float(hidden.get("alcohol_units", 0) or 0)
    night_len = max(1.0, sp["wake"] - sp["bedtime"])
    for m in range(max(0, bed_min_of_day), 1440):
        frac = (m - bed_min_of_day) / night_len
        arr[m] = _sleep_hr(sp["rhr"], frac) + (min(1.2 * alc, 5.0) if frac < 0.5 else 0.0)
        add[m] = 0.0
    onset_end = bed_min_of_day + int(sp["onset"])
    for m in range(max(0, bed_min_of_day), min(1440, onset_end)):
        arr[m] = sp["rhr"] + 2.0 - (sp["rhr"] + 2.0 - _sleep_hr(sp["rhr"], 0.0)) * ((m - bed_min_of_day) / max(1.0, sp["onset"]))

    # --- compose, illness, AR(1) noise
    out: List[Optional[int]] = [None] * 1440
    ar = 0.0
    r2 = random.Random(noise.get("ar_seed", 0.5))
    for m in range(1440):
        ar = 0.7 * ar + r2.gauss(0.0, 2.5) * math.sqrt(1 - 0.49)
        v = arr[m] + add[m] + ill + ar
        out[m] = int(max(38, min(195, round(v))))

    # --- watch not worn: charging gap, unworn night, morning of an unworn night
    gap_start = None
    if not force_no_gap and noise.get("gap_u", 1.0) < 0.6:
        pos = noise.get("gap_pos", 0.5)
        gap_start = 7 * 60 + int(pos * 30) if pos < 0.5 else 17 * 60 + 30 + int((pos - 0.5) * 60)
    elif force_no_gap and noise.get("gap_u", 1.0) < 0.6:
        gap_start = 12 * 60 + int(noise.get("gap_pos", 0.5) * 45)
    if gap_start is not None:
        for m in range(gap_start, min(1440, gap_start + 35 + int(25 * noise.get("gap_pos", 0.5)))):
            out[m] = None
    unworn_until = int(state.get("unworn_until_today", 0))
    for m in range(0, min(1440, unworn_until)):
        out[m] = None
    if unworn_tonight:
        for m in range(22 * 60, 1440):
            out[m] = None
    if partial_until is not None:
        for m in range(max(0, partial_until), 1440):
            out[m] = None

    detected = detect_workouts(out, d, persona.tz, workouts)
    next_state = {
        "wake_min_today": int(sp["wake"] + 720 - 1440),
        "prev_rhr": sp["rhr"],
        "prev_sleep_len": night_len,
        "prev_min_before_midnight": max(0.0, 1440 - bed_min_of_day) if bed_min_of_day < 1440 else 0.0,
        "unworn_until_today": 8 * 60 if unworn_tonight else 0,
        "awake_spans_today": [],
    }
    return out, detected, next_state


def detect_workouts(bpm: Sequence[Optional[int]], d: date, tzname: str, planned: Sequence[Tuple[int, int, str]]) -> List[WatchWorkout]:
    """The watch's own detection: 5-min rolling mean > 120 for >= 20 consecutive minutes."""
    out: List[WatchWorkout] = []
    roll: List[Optional[float]] = [None] * 1440
    for m in range(1440):
        window = [b for b in bpm[max(0, m - 4):m + 1] if b is not None]
        roll[m] = (sum(window) / len(window)) if window else None
    m = 0
    seq = 0
    while m < 1440:
        if roll[m] is not None and roll[m] > 120:
            s = m
            while m < 1440 and roll[m] is not None and roll[m] > 120:
                m += 1
            if m - s >= 20:
                vals = [b for b in bpm[s:m] if b is not None]
                kind = "strength"
                for ws, we, k in planned:
                    if ws <= s + 5 <= we or ws <= m - 5 <= we:
                        kind = k
                if kind == "strength" and vals and sum(vals) / len(vals) > 145:
                    kind = "run"
                avg = int(round(sum(vals) / len(vals))) if vals else 0
                out.append(WatchWorkout(id=new_id("wk", d, seq), kind=kind, start=at(d, s / 60.0, tzname=tzname),
                                        end=at(d, m / 60.0, tzname=tzname), avg_hr=avg, max_hr=max(vals) if vals else 0,
                                        calories=int((m - s) * (9 if kind == "run" else 6))))
                seq += 1
        else:
            m += 1
    return out


def steps_for(attended: Sequence[CalendarEvent], visits: Sequence[LocationVisit], d: date, workouts: Sequence[WatchWorkout],
              noise: Dict[str, Any]) -> Tuple[int, int]:
    steps = 2500
    active = 0
    for v in visits:
        if v.start.date() == d and v.place_type == "transit":
            steps += 1100
            active += 12
    for (_, minutes, _) in noise.get("walks", []):
        steps += minutes * 90
        active += minutes
    for w in workouts:
        minutes = int((w.end - w.start).total_seconds() // 60)
        steps += 5500 if w.kind == "run" else 900
        active += minutes
    return steps, active


# --------------------------------------------------------------------------- #
# Day orchestration
# --------------------------------------------------------------------------- #
def last_event_end_min(attended: Sequence[CalendarEvent], d: date, exclude_factor: Optional[str] = None) -> Optional[float]:
    """Latest attended event end (minutes after 12:00), ignoring the events behind ``exclude_factor``."""
    best = None
    for ev in attended:
        end_h = day_hour(ev.end, d)
        if exclude_factor == "evening_social" and ev.type == "social":
            continue
        if exclude_factor == "late_meeting_hours" and ev.type == "meeting" and end_h > 18.0:
            continue
        if exclude_factor == "workout_late" and ev.type == "workout":
            continue
        if exclude_factor == "travel" and ev.type == "travel":
            continue
        if ev.type == "protected":
            continue
        m = end_h * 60.0 - 720.0
        if m > 300 and (best is None or m > best):   # only evening events matter (after 17:00)
            best = m
    return best


def simulate_day(persona: Persona, ratios: Dict[str, float], d: date, features: DayFeatures,
                 attended: Sequence[CalendarEvent], visits: Sequence[LocationVisit], hidden: Dict[str, Any],
                 noise: Dict[str, Any], state: Dict[str, Any], rng: random.Random, recent_bedtimes: Sequence[float],
                 unworn_tonight: bool, force_no_gap: bool, weekend_override: Optional[bool] = None
                 ) -> Tuple[HeartRateDay, DailyActivity, SleepNight, SimTruthNight, Dict[str, Any]]:
    reg = features.regressors()
    weekend = bool(features.is_weekend) if weekend_override is None else bool(weekend_override)
    debt = float(state.get("debt", 0.0))
    last_end = last_event_end_min(attended, d)

    sp = compute_sleep(persona, ratios, reg, hidden, noise, debt, last_end, recent_bedtimes, weekend)

    # --- ground truth by counterfactual re-runs on identical noise
    contributions: Dict[str, float] = {}
    for k in CALENDAR_KEYS:
        if reg.get(k, 0.0) == 0.0:
            continue
        reg_wo = dict(reg)
        reg_wo[k] = 0.0
        sp_wo = compute_sleep(persona, ratios, reg_wo, hidden, noise, debt, last_event_end_min(attended, d, k), recent_bedtimes, weekend)
        contributions[k] = float(sp["score"] - sp_wo["score"])
    for hkey, field in (("alcohol", "alcohol_units"), ("caffeine", "caffeine_late"), ("screens", "screens_late"), ("illness", "illness")):
        if hidden.get(field):
            h_wo = dict(hidden)
            h_wo[field] = 0
            sp_wo = compute_sleep(persona, ratios, reg, h_wo, noise, debt, last_end, recent_bedtimes, weekend)
            contributions["hidden:" + hkey] = float(sp["score"] - sp_wo["score"])
    if debt > 0:
        sp_wo = compute_sleep(persona, ratios, reg, hidden, noise, 0.0, last_end, recent_bedtimes, weekend)
        contributions["hidden:sleep_debt"] = float(sp["score"] - sp_wo["score"])
    reg_calm = {k: 0.0 for k in reg}
    reg_calm["is_weekend"] = reg.get("is_weekend", 0.0)
    sp_calm = compute_sleep(persona, ratios, reg_calm, hidden, noise, debt, None, recent_bedtimes, weekend)
    calendar_sum = sum(v for k, v in contributions.items() if not k.startswith("hidden:"))
    truth = SimTruthNight(date=d, contributions=contributions, hidden=dict(hidden),
                          noise_points=float(sp["score"] - sp_calm["score"] - calendar_sum),
                          counterfactual_score=int(sp_calm["score"]), regressors=dict(reg))

    # --- heart rate for the day (uses tonight's bedtime and last night's state)
    bpm, detected, next_state = build_hr(persona, d, attended, visits, features, hidden, sp, state, noise, rng,
                                         unworn_tonight, force_no_gap)
    steps, active = steps_for(attended, visits, d, detected, noise)
    activity = DailyActivity(date=d, steps=steps, active_minutes=active, workouts=detected)

    tz = persona.tz
    if unworn_tonight:
        night = SleepNight(date=d, worn=False)
    else:
        stages = build_stages(d, tz, sp)
        deep = sum(int((s.end - s.start).total_seconds() // 60) for s in stages if s.kind == "deep")
        rem = sum(int((s.end - s.start).total_seconds() // 60) for s in stages if s.kind == "rem")
        core = sum(int((s.end - s.start).total_seconds() // 60) for s in stages if s.kind == "core")
        night = SleepNight(
            date=d, worn=True,
            in_bed_start=night_min_to_dt(d, sp["bedtime"], tz),
            sleep_onset=night_min_to_dt(d, sp["bedtime"] + sp["onset"], tz),
            wake_time=night_min_to_dt(d, sp["wake"], tz),
            out_of_bed=night_min_to_dt(d, sp["wake"] + 8, tz),
            stages=stages, interruptions=int(sp["interrupt"]), awake_min=int(round(sp["awake"])),
            duration_min=int(round(sp["duration"])), deep_min=deep, rem_min=rem, core_min=core,
            hrv_ms=round(sp["hrv"], 1), resting_hr=int(round(sp["rhr"])), resp_rate=round(sp["resp"], 1),
            wrist_temp_dev=round(sp["temp"], 2), spo2=round(sp["spo2"], 1), score=int(sp["score"]),
            score_parts=dict(sp["parts"]), score_source="stressless")
    # awake spans (interruptions) that fall after midnight, for tomorrow's morning HR
    spans = []
    if not unworn_tonight:
        for s in night.stages:
            if s.kind == "awake" and s.start.date() == d + timedelta(days=1):
                spans.append((s.start.hour * 60 + s.start.minute, max(1, int((s.end - s.start).total_seconds() // 60))))
    next_state["awake_spans_today"] = spans
    next_state["debt"] = max(0.0, min(120.0, 0.5 * debt + max(0.0, persona.sleep_need_min - 30 - sp["duration"])))
    next_state["bedtime_min"] = sp["bedtime"]
    return HeartRateDay(date=d, bpm=bpm), activity, night, truth, next_state
