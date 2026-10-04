"""Dataset orchestration for the digital twin (SPEC §5.5, §5.6).

Order: calendar -> showcase overrides -> coverage fix-up -> location -> physiology day by day ->
realised truth tables. Deterministic for (persona, seed, anchor).
"""
from __future__ import annotations

import logging
import random
import statistics
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..engine.features import day_features
from ..models import (CalendarEvent, Dataset, DayFeatures, HeartRateDay, Persona, SimTruth, SimTruthEvent,
                      SimTruthNight, new_id)
from ..timeutil import at, day_hour, today_local, tz
from .calendar_gen import generate_events
from .location_gen import generate_visits
from .personas import PERSONAS, get_persona, ratios_for
from .physiology import CALENDAR_KEYS, draw_noise, simulate_day

log = logging.getLogger("stressless.sim")

MIN_ACTIVE = 8


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
class Book:
    """Mutable event/truth bookkeeping shared by the showcase and coverage passes."""

    def __init__(self, persona: Persona, events: List[CalendarEvent], truth: List[SimTruthEvent], today: date) -> None:
        self.p = persona
        self.events = events
        self.truth = truth
        self.today = today

    def on(self, d: date) -> List[CalendarEvent]:
        return sorted([e for e in self.events if e.start.date() == d], key=lambda e: e.start)

    def attended_on(self, d: date) -> List[CalendarEvent]:
        att = {t.event_id: t.attended for t in self.truth}
        return [e for e in self.on(d) if att.get(e.id, True)]

    def remove(self, ev: CalendarEvent) -> None:
        self.events.remove(ev)
        self.truth[:] = [t for t in self.truth if t.event_id != ev.id]

    def remove_where(self, d: date, pred) -> None:
        for ev in list(self.on(d)):
            if pred(ev):
                self.remove(ev)

    def next_seq(self, d: date) -> int:
        prefix = new_id("ev", self.p.key, d, "")
        seqs = [int(e.id[len(prefix):]) for e in self.events if e.id.startswith(prefix) and e.id[len(prefix):].isdigit()]
        return (max(seqs) + 1) if seqs else 0

    def add(self, d: date, title: str, s: float, e: float, type_: str, hint: Optional[str] = None, attendees: int = 0,
            notes: Optional[str] = None, attended: bool = True, reason: Optional[str] = None, recurring_key: Optional[str] = None) -> CalendarEvent:
        ev = CalendarEvent(id=new_id("ev", self.p.key, d, self.next_seq(d)), title=title, start=at(d, s, tzname=self.p.tz),
                           end=at(d, e, tzname=self.p.tz), type=type_, location_hint=hint, attendees=attendees,
                           recurring_key=recurring_key, source="demo", attended=None, notes=notes)
        self.events.append(ev)
        if d < self.today:
            self.truth.append(SimTruthEvent(event_id=ev.id, attended=attended, reason=reason))
        return ev

    def free(self, d: date, s: float, e: float) -> bool:
        for ev in self.on(d):
            a, b = day_hour(ev.start, d), day_hour(ev.end, d)
            if s < b and e > a:
                return False
        return True


def _shell(persona: Persona, start: date, end: date, today: date) -> Dataset:
    return Dataset(persona=persona, seed=0, source="demo", start=start, end=end, today=today)


# --------------------------------------------------------------------------- #
# showcase (SPEC §5.6)
# --------------------------------------------------------------------------- #
def apply_showcase(book: Book, day_kind: Dict[date, str], start: date, end: date, today: date, rng: random.Random) -> Dict[str, Any]:
    key = book.p.key
    tomorrow = today + timedelta(days=1)
    # (b) signature bad day on `end`: wipe and script
    for ev in list(book.on(end)):
        book.remove(ev)
    day_kind[end] = "office"
    if key == "alex":
        book.add(end, "Roadmap review", 9.5, 10.5, "meeting", "Room Björk", 7)
        book.add(end, "1:1 with Maria", 11.0, 11.5, "meeting", "Google Meet", 2)
        book.add(end, "Design crit", 13.0, 14.0, "meeting", "Room Ek", 6)
        book.add(end, "Pricing workshop", 14.0, 15.0, "meeting", "Room Ek", 8)
        book.add(end, "Hiring sync", 15.0, 16.0, "meeting", "Google Meet", 4)
        book.add(end, "Product review", 16.0, 17.0, "meeting", "Room Björk", 9)
        book.add(end, "Customer call: Pacific team", 19.25, 20.25, "meeting", "Zoom", 5)
        book.add(end, "Early call: APAC partner", 7.0, 7.75, "meeting", "Zoom", 4)
    elif key == "sam":
        day_kind[end] = "travel_back"
        book.add(end, "Early client workshop", 7.0, 8.5, "meeting", "Client site", 6)
        book.add(end, "Steering group", 9.0, 10.0, "meeting", "Client site", 6)
        book.add(end, "Workstream review", 10.0, 11.0, "meeting", "Client site", 5)
        book.add(end, "Data room walkthrough", 11.0, 12.0, "meeting", "Client site", 4)
        book.add(end, "Findings readout", 13.0, 14.0, "meeting", "Client site", 9)
        book.add(end, "Next-phase planning", 14.0, 15.0, "meeting", "Client site", 6)
        book.add(end, "Flight CPH->ARN 17:50", 17.25, 20.0, "travel", "Copenhagen airport")
        book.add(end, "Dinner with the steering group", 20.25, 22.5, "social", "Marchal", 5)
    else:
        book.add(end, "Early call: US investor", 7.0, 7.75, "meeting", "Zoom", 2)
        book.add(end, "Product sync", 9.5, 10.5, "meeting", "Office", 4)
        book.add(end, "Customer call: Northwind", 11.0, 12.0, "meeting", "Zoom", 3)
        book.add(end, "Hiring sync", 13.0, 14.0, "meeting", "Office", 3)
        book.add(end, "Board prep", 14.0, 15.0, "meeting", "Office", 2)
        book.add(end, "Partner sync", 15.5, 16.5, "meeting", "Zoom", 4)
        book.add(end, "Investor update", 19.0, 20.0, "meeting", "Zoom", 4)
        book.add(end, "Gym", 20.75, 21.75, "workout", "Friskis Södermalm", notes="kind=strength")
    # (c) today: a late meeting, no protected; tomorrow: an early start
    book.remove_where(today, lambda e: e.type == "protected" or (e.type == "meeting" and day_hour(e.end, today) >= 18.0))
    late = {"alex": ("Customer call: Pacific team", 18.5, 19.75), "sam": ("Board call", 19.0, 20.0), "robin": ("Investor update", 19.0, 20.0)}[key]
    book.add(today, late[0], late[1], late[2], "meeting", "Zoom", 5)
    if not any(e.type in ("meeting", "travel", "personal") and day_hour(e.start, tomorrow) <= 7.5 for e in book.on(tomorrow)):
        book.remove_where(tomorrow, lambda e: e.type == "meeting" and day_hour(e.start, tomorrow) < 8.5)
        if key == "sam":
            book.add(tomorrow, "Early client workshop", 7.0, 8.5, "meeting", "Client site", 6)
        else:
            book.add(tomorrow, "Early call: APAC partner", 7.0, 8.0, "meeting", "Zoom", 4)
    # (d) one skipped gym and one unbooked gym (robin also an unbooked bar) within end-6..end-1
    window = [end - timedelta(days=k) for k in range(6, 0, -1)]
    weekdays = [d for d in window if d.weekday() <= 4 and day_kind.get(d) in ("office", "wfh", "home")]
    rng.shuffle(weekdays)
    skipped_day = None
    unbooked_gym_day = None
    unbooked_bar_day = None
    def clear_evening(d: date) -> None:
        book.remove_where(d, lambda e: e.type in ("social", "personal", "protected") and day_hour(e.start, d) >= 17.0)

    for d in weekdays:
        if skipped_day is None and not any(e.type == "workout" for e in book.on(d)):
            clear_evening(d)
            if book.free(d, 18.0, 19.0):
                book.add(d, "Gym", 18.0, 19.0, "workout", "SATS Odenplan", notes="kind=strength", attended=False, reason="skipped")
                skipped_day = d
                continue
        if unbooked_gym_day is None and not any(e.type == "workout" and day_hour(e.end, d) > 17.0 for e in book.on(d)):
            clear_evening(d)
            unbooked_gym_day = d
            continue
        if key == "robin" and unbooked_bar_day is None and not any(e.type == "social" for e in book.on(d)):
            clear_evening(d)
            if book.free(d, 18.5, 21.0):
                unbooked_bar_day = d
    if today.weekday() >= 5 and not any(day_hour(e.start, today) <= 9.0 for e in book.on(today)):
        book.add(today, "Brunch with Sara" if key != "sam" else "Airport run for Alex", 8.5, 10.0, "personal", "Café Saturnus")
    # (e) illness pinned, unworn night pinned on a social night
    illness_days = [end - timedelta(days=12), end - timedelta(days=11), end - timedelta(days=10)]
    unworn_night = end - timedelta(days=10)
    if not any(e.type == "social" and day_hour(e.end, unworn_night) >= 20.5 for e in book.on(unworn_night)):
        book.remove_where(unworn_night, lambda e: e.type in ("social", "protected", "workout") and day_hour(e.start, unworn_night) >= 17.0)
        book.add(unworn_night, "Dinner with Sara", 19.0, 22.5, "social", "Restaurang Pelikan", 2)
    protected_window: Set[date] = set(window) | {end, today, tomorrow} | set(illness_days) | {unworn_night}
    return {"skipped_gym_day": skipped_day, "unbooked_gym_day": unbooked_gym_day, "unbooked_bar_day": unbooked_bar_day,
            "illness_days": illness_days, "unworn_night": unworn_night, "protected_window": protected_window}


# --------------------------------------------------------------------------- #
# coverage fix-up (SPEC §5.6 f)
# --------------------------------------------------------------------------- #
def _active_counts(book: Book, shell: Dataset, start: date, end: date) -> Dict[str, int]:
    counts = {k: 0 for k in CALENDAR_KEYS}
    d = start
    while d <= end:
        reg = day_features(shell, d, events=book.attended_on(d)).regressors()
        for k in CALENDAR_KEYS:
            if reg.get(k, 0.0) != 0.0:
                counts[k] += 1
        d += timedelta(days=1)
    return counts


def ensure_coverage(book: Book, shell: Dataset, start: date, end: date, rng: random.Random, exclude: Set[date]) -> None:
    b = book.p.behaviour
    travel = b.get("travel") or {}
    code, city = travel.get("code", "BER"), travel.get("city", "Berlin")
    late_gym_hour = float(b.get("late_gym_hour", 20.0))
    for _ in range(12):
        counts = _active_counts(book, shell, start, end)
        missing = [k for k in CALENDAR_KEYS if counts[k] < MIN_ACTIVE]
        if not missing:
            return
        cands = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        cands = [d for d in cands if d not in exclude and d.weekday() <= 4]
        rng.shuffle(cands)
        for k in missing:
            for d in cands:
                evs = book.on(d)
                reg = day_features(shell, d, events=book.attended_on(d)).regressors()
                if reg.get(k, 0.0) != 0.0:
                    continue
                if k == "travel" and not any(e.type == "travel" for e in evs) and book.free(d, 5.9, 9.0) and book.free(d, 19.0, 22.25):
                    book.add(d, "Flight ARN->%s 07:10" % code, 5.9, 9.0, "travel", "Arlanda")
                    book.add(d, "Flight %s->ARN 19:40" % code, 19.0, 22.25, "travel", "%s airport" % city)
                elif k == "workout_late" and not any(e.type == "workout" for e in evs) and book.free(d, late_gym_hour, late_gym_hour + 1.0):
                    book.add(d, "Gym", late_gym_hour, late_gym_hour + 1.0, "workout", "SATS Odenplan", notes="kind=strength")
                elif k == "workout_morning" and not any(e.type == "workout" for e in evs) and book.free(d, 7.0, 7.75):
                    book.add(d, "Morning run", 7.0, 7.75, "workout", "Djurgården loop", notes="kind=run")
                elif k == "protected_evening":
                    if book.free(d, 21.0, 22.0):
                        book.add(d, "Wind down", 21.0, 22.0, "protected", None)
                    elif book.free(d, 22.0, 23.0):
                        book.add(d, "Wind down", 22.0, 23.0, "protected", None)
                    else:
                        continue
                elif k == "early_start" and book.free(d, 7.0, 7.75):
                    book.add(d, "Early call: APAC partner", 7.0, 7.75, "meeting", "Zoom", 4)
                elif k == "evening_social" and not any(e.type == "social" for e in evs) and book.free(d, 19.0, 22.5):
                    book.add(d, "Dinner with friends", 19.0, 22.5, "social", "Restaurang Pelikan", 3)
                elif k == "late_meeting_hours" and book.free(d, 19.0, 20.0):
                    book.add(d, "Investor update" if book.p.key == "robin" else "Customer call: Pacific team", 19.0, 20.0, "meeting", "Zoom", 4)
                elif k == "b2b_over_2":
                    s = 13.0
                    added = 0
                    while added < 4 and s < 17.0:
                        if book.free(d, s, s + 1.0):
                            book.add(d, "Sprint planning" if added % 2 else "Roadmap review", s, s + 1.0, "meeting", "Room Ek", 5)
                            added += 1
                        s += 1.0
                    if added < 3:
                        continue
                elif k == "meetings_over_3":
                    s = 9.0
                    added = 0
                    while added < 3 and s < 17.0:
                        if book.free(d, s, s + 0.75):
                            book.add(d, "Partner sync", s, s + 0.75, "meeting", "Google Meet", 3)
                            added += 1
                        s += 1.5
                else:
                    continue
                break
    log.warning("coverage fix-up did not reach %d active nights for all factors: %s", MIN_ACTIVE, _active_counts(book, shell, start, end))


# --------------------------------------------------------------------------- #
# hidden factors and missingness
# --------------------------------------------------------------------------- #
def draw_hidden(rng: random.Random, f: DayFeatures, d: date, illness_days: Sequence[date], bar_day: bool) -> Dict[str, Any]:
    units = 0
    if f.evening_social:
        if rng.random() < 0.7:
            units = rng.choice([2, 3, 4])
    elif bar_day:
        if rng.random() < 0.6:
            units = rng.choice([2, 3])
    elif rng.random() < 0.05:
        units = rng.choice([1, 2])
    return {
        "alcohol_units": units,
        "caffeine_late": bool(f.n_meetings >= 5 and rng.random() < 0.25),
        "screens_late": bool(rng.random() < 0.20),
        "illness": d in set(illness_days),
    }


def partial_today_hr(persona: Persona, today: date, state: Dict[str, Any], rng: random.Random) -> HeartRateDay:
    """Heart rate for the current day: last night's tail and the morning, then None (it is 'now')."""
    from .physiology import _sleep_hr
    wake = int(state.get("wake_min_today", 7 * 60))
    prev_rhr = float(state.get("prev_rhr", persona.resting_hr))
    prev_len = float(state.get("prev_sleep_len", 450.0))
    before = float(state.get("prev_min_before_midnight", 60.0))
    unworn_until = int(state.get("unworn_until_today", 0))
    base_awake = persona.resting_hr + 12.0
    until = max(wake + 45, 9 * 60)
    bpm: List[Optional[int]] = [None] * 1440
    r2 = random.Random(rng.random())
    for m in range(0, min(1440, until)):
        if m < wake:
            v = _sleep_hr(prev_rhr, min(1.0, (before + m) / max(1.0, prev_len)))
        elif m < wake + 30:
            v = _sleep_hr(prev_rhr, 1.0) + (base_awake - _sleep_hr(prev_rhr, 1.0)) * ((m - wake) / 30.0)
        else:
            v = base_awake + (12.0 if (m - wake) % 37 < 6 else 0.0)
        bpm[m] = int(max(38, min(195, round(v + r2.gauss(0, 2.0)))))
    for m in range(0, min(1440, unworn_until)):
        bpm[m] = None
    return HeartRateDay(date=today, bpm=bpm)


# --------------------------------------------------------------------------- #
# truth tables
# --------------------------------------------------------------------------- #
def realised_truth(persona: Persona, nights: Sequence[SimTruthNight]) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, Any]]:
    direct: Dict[str, float] = {}
    total: Dict[str, float] = {}
    hidden_fields = {"alcohol": lambda h: (h.get("alcohol_units") or 0) > 0, "caffeine": lambda h: bool(h.get("caffeine_late")),
                     "screens": lambda h: bool(h.get("screens_late")), "illness": lambda h: bool(h.get("illness"))}
    mean_hidden = {}
    for hk in hidden_fields:
        vals = [n.contributions.get("hidden:" + hk) for n in nights if ("hidden:" + hk) in n.contributions]
        mean_hidden[hk] = (sum(vals) / len(vals)) if vals else 0.0
    for k in CALENDAR_KEYS:
        active = [n for n in nights if n.regressors.get(k, 0.0) != 0.0]
        inactive = [n for n in nights if n.regressors.get(k, 0.0) == 0.0]
        if not active:
            continue
        num = sum(n.contributions.get(k, 0.0) for n in active)
        den = sum(n.regressors.get(k, 0.0) for n in active)
        direct[k] = num / den if den else 0.0
        conf = 0.0
        for hk, pred in hidden_fields.items():
            p_act = sum(1 for n in active if pred(n.hidden)) / len(active)
            p_inact = (sum(1 for n in inactive if pred(n.hidden)) / len(inactive)) if inactive else p_act
            conf += (p_act - p_inact) * mean_hidden[hk]
        # per unit of the regressor
        unit = den / len(active) if den else 1.0
        total[k] = direct[k] + conf / (unit if unit else 1.0)
    hidden_nights = [n.date for n in nights if any(pred(n.hidden) for pred in hidden_fields.values())]
    summary = {
        "nights_with_hidden": len(hidden_nights),
        "alcohol_nights": sum(1 for n in nights if (n.hidden.get("alcohol_units") or 0) > 0),
        "caffeine_days": sum(1 for n in nights if n.hidden.get("caffeine_late")),
        "screens_nights": sum(1 for n in nights if n.hidden.get("screens_late")),
        "illness_nights": [n.date.isoformat() for n in nights if n.hidden.get("illness")],
        "mean_hidden_effect": {k: round(v, 2) for k, v in mean_hidden.items()},
        "debt_mean": round(statistics.mean([n.hidden.get("debt", 0.0) for n in nights]), 1) if nights else 0.0,
    }
    return direct, total, summary


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #
def generate_dataset(persona_key: str = "alex", seed: int = 7, days: int = 70, anchor: Optional[date] = None,
                     showcase: bool = True) -> Dataset:
    persona = get_persona(persona_key)
    rng = random.Random("%s-%d" % (persona_key, seed))
    today = anchor or today_local(persona.tz)
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    end_cal = today + timedelta(days=7)

    events, truth_events, day_kind = generate_events(persona, start, end_cal, today, rng)
    book = Book(persona, events, truth_events, today)
    shell = _shell(persona, start, end, today)
    forced: Dict[str, Any] = {"protected_window": set(), "illness_days": [], "unworn_night": None,
                              "unbooked_gym_day": None, "unbooked_bar_day": None, "skipped_gym_day": None}
    if showcase:
        forced = apply_showcase(book, day_kind, start, end, today, rng)
    else:
        i0 = rng.randint(10, days - 12)
        forced["illness_days"] = [start + timedelta(days=i0 + k) for k in range(3)]
    ensure_coverage(book, shell, start, end, rng, forced["protected_window"])
    events.sort(key=lambda e: e.start)

    visits, unbooked_ids = generate_visits(
        persona, events, truth_events, day_kind, start, end, rng,
        forced_unbooked_gym=[forced["unbooked_gym_day"]] if forced.get("unbooked_gym_day") else None,
        forced_unbooked_bar=[forced["unbooked_bar_day"]] if forced.get("unbooked_bar_day") else None,
        protected_days=forced["protected_window"])
    bar_days = {v.start.date() for v in visits if v.id in set(unbooked_ids) and v.place_type in ("bar", "restaurant")}

    ratios = ratios_for(persona)
    state: Dict[str, Any] = {"debt": 0.0, "wake_min_today": int(persona.usual_wake * 60), "prev_rhr": persona.resting_hr,
                             "prev_sleep_len": 450.0, "prev_min_before_midnight": 60.0, "unworn_until_today": 0, "awake_spans_today": []}
    recent_bedtimes: List[float] = []
    hr_days, activity, nights, truth_nights = [], [], [], []
    visits_by_day: Dict[date, List] = {}
    for v in visits:
        visits_by_day.setdefault(v.start.date(), []).append(v)
    d = start
    while d <= end:
        attended = book.attended_on(d)
        f = day_features(shell, d, events=attended)
        hidden = draw_hidden(rng, f, d, forced["illness_days"], d in bar_days)
        hidden["debt"] = round(float(state.get("debt", 0.0)), 1)
        noise = draw_noise(rng)
        in_last7 = (end - d).days < 7
        if showcase and d == end:
            # the hero night: fixed, modest noise so the story lands regardless of seed
            noise.update({"bed": 0.2, "onset": 0.3, "wake": 0.0, "awake": 0.0, "hrv_ln": -0.3, "rhr": 0.4, "resp": 0.0,
                          "temp": 0.0, "spo2": 0.0, "life": 0.3, "jitter": 0.0, "interrupt_u": 0.42, "gap_u": 1.0})
        if showcase and in_last7:
            unworn = False
        elif showcase and d == forced["unworn_night"]:
            unworn = True
        else:
            unworn = rng.random() < (0.15 if f.evening_social else 0.03)
        weekend_override = False if (showcase and d == end) else None   # the signature night reads like a work night
        hr, act, night, tn, state = simulate_day(persona, ratios, d, f, attended, visits_by_day.get(d, []), hidden, noise,
                                                 state, rng, recent_bedtimes, unworn, force_no_gap=(showcase and in_last7),
                                                 weekend_override=weekend_override)
        if night.worn:
            recent_bedtimes.append(state["bedtime_min"])
            recent_bedtimes = recent_bedtimes[-14:]
        hr_days.append(hr)
        activity.append(act)
        nights.append(night)
        truth_nights.append(tn)
        d += timedelta(days=1)
    hr_days.append(partial_today_hr(persona, today, state, rng))

    direct, total, summary = realised_truth(persona, truth_nights)
    summary["unworn_nights"] = [n.date.isoformat() for n in nights if not n.worn]
    summary["unworn_social_nights"] = sum(1 for n, tn in zip(nights, truth_nights) if not n.worn and tn.regressors.get("evening_social"))
    summary["skipped_gym_day"] = forced["skipped_gym_day"].isoformat() if forced.get("skipped_gym_day") else None
    summary["unbooked_gym_day"] = forced["unbooked_gym_day"].isoformat() if forced.get("unbooked_gym_day") else None
    truth = SimTruth(nights=truth_nights, events=truth_events, unbooked=unbooked_ids, effect_table=total,
                     effect_table_direct=direct, effect_table_design={k: float(persona.sensitivities.get(k, 0.0)) for k in CALENDAR_KEYS},
                     hidden_summary=summary)
    ds = Dataset(persona=persona, seed=seed, source="demo", start=start, end=end, today=today, events=events, visits=visits,
                 hr_days=hr_days, nights=nights, activity=activity, truth=truth, generated_at=datetime.now(tz(persona.tz)),
                 showcase=showcase)
    return ds
