"""Calendar generator for the digital twin (SPEC §5.2).

Produces ten weeks of realistic events for a persona plus attendance ground truth. Titles and
venues are fictional. ``CalendarEvent.attended`` is always left ``None``; the truth lives in
``SimTruthEvent``.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from ..models import CalendarEvent, Persona, SimTruthEvent, new_id
from ..timeutil import at

MEETING_TITLES = [
    "Roadmap review", "Design crit", "Sprint planning", "Customer call: Northwind", "Board prep",
    "Hiring sync", "1:1 with Maria", "1:1 with Jonas", "Analytics deep-dive", "Pricing workshop",
    "Interview: senior engineer", "Partner sync", "Weekly team sync", "Product review",
    "Quarterly planning", "Support escalations", "Launch checklist", "Growth review",
    "Legal check-in", "Vendor demo: Lumen", "Pitch rehearsal", "Marketing sync", "Ops standup",
]
LATE_TITLES = ["Customer call: Pacific team", "Investor update", "Board call", "Customer call: Northwind US",
               "Escalation bridge", "Late sync with the SF team"]
FOCUS_TITLES = ["Focus: roadmap doc", "Focus: spec writing", "Deep work", "Focus: budget model", "Writing time"]
SOCIAL = [
    ("After-work with the team", "Bar Central", "bar"),
    ("Dinner at Tranan", "Tranan", "restaurant"),
    ("Dinner with Sara", "Restaurang Pelikan", "restaurant"),
    ("Drinks with old colleagues", "Häktet", "bar"),
    ("Concert at Debaser", "Debaser", "bar"),
    ("Birthday dinner", "Woodstockholm", "restaurant"),
    ("Team dinner", "Meatballs for the People", "restaurant"),
    ("Pub quiz", "The Bishops Arms", "bar"),
]
CLIENT_DINNERS = [("Client dinner", "Restaurant Kokkeriet", "restaurant"), ("Dinner with the steering group", "Marchal", "restaurant")]
PERSONAL = [("Dentist", "personal", 16.0, 1.0), ("School pickup", "personal", 15.5, 0.5),
            ("Physio", "personal", 17.0, 0.75), ("Car service drop-off", "personal", 8.0, 0.5)]
MEETING_PLACES_OFFICE = ["Room Björk", "Room Ek", "Office", "Office", "Room Tall"]
MEETING_PLACES_REMOTE = ["Google Meet", "Zoom", "Google Meet"]


class DayPlan:
    """Mutable per-day bookkeeping while generating."""

    def __init__(self, d: date) -> None:
        self.date = d
        self.busy: List[Tuple[float, float]] = []   # (start_hour, end_hour) reserved slots

    def free(self, start: float, end: float) -> bool:
        for s, e in self.busy:
            if start < e and end > s:
                return False
        return True

    def reserve(self, start: float, end: float) -> None:
        self.busy.append((start, end))


class CalendarBuilder:
    def __init__(self, persona: Persona, start: date, end_cal: date, today: date, rng: random.Random) -> None:
        self.p = persona
        self.b = persona.behaviour
        self.start = start
        self.end_cal = end_cal
        self.today = today
        self.rng = rng
        self.events: List[CalendarEvent] = []
        self.truth: List[SimTruthEvent] = []
        self.seq: Dict[date, int] = {}
        self.day_kind: Dict[date, str] = {}   # office | wfh | away | home | travel_out | travel_back
        self.tz = persona.tz

    # ------------------------------------------------------------ helpers --
    def _id(self, d: date) -> str:
        n = self.seq.get(d, 0)
        self.seq[d] = n + 1
        return new_id("ev", self.p.key, d, n)

    def add(self, d: date, title: str, start_h: float, end_h: float, type_: str, hint: Optional[str] = None,
            attendees: int = 0, recurring_key: Optional[str] = None, notes: Optional[str] = None,
            plan: Optional[DayPlan] = None, attended: Optional[bool] = None, reason: Optional[str] = None) -> CalendarEvent:
        ev = CalendarEvent(id=self._id(d), title=title, start=at(d, start_h, tzname=self.tz), end=at(d, end_h, tzname=self.tz),
                           type=type_, location_hint=hint, attendees=attendees, recurring_key=recurring_key,
                           source="demo", attended=None, notes=notes)
        self.events.append(ev)
        if plan is not None:
            plan.reserve(start_h, end_h)
        if ev.start.date() < self.today:
            if attended is None:
                attended, reason = self._attendance(type_, self.day_kind.get(d, "office"), hint)
            self.truth.append(SimTruthEvent(event_id=ev.id, attended=attended, reason=reason))
        return ev

    def _attendance(self, type_: str, kind: str, hint: Optional[str]) -> Tuple[bool, Optional[str]]:
        skip = self.b.get("skip_prob", {})
        if type_ == "travel" or type_ == "protected" or type_ == "focus":
            return True, None
        if type_ == "meeting":
            if self.rng.random() < skip.get("meeting", 0.03):
                return False, "cancelled"
            if kind == "wfh" and hint in MEETING_PLACES_OFFICE:
                return True, "wfh"
            return True, None
        if type_ == "workout":
            return (False, "skipped") if self.rng.random() < skip.get("workout", 0.12) else (True, None)
        if type_ == "social":
            return (False, "skipped") if self.rng.random() < skip.get("social", 0.08) else (True, None)
        if type_ == "personal":
            return (False, "skipped") if self.rng.random() < 0.05 else (True, None)
        return True, None

    def _slot(self, plan: DayPlan, lo: float, hi: float, minutes: int, step: float = 0.5, tries: int = 30) -> Optional[float]:
        dur = minutes / 60.0
        n_steps = int((hi - lo - dur) / step)
        if n_steps < 0:
            return None
        for _ in range(tries):
            s = lo + step * self.rng.randint(0, n_steps)
            if plan.free(s, s + dur):
                return s
        return None

    # ------------------------------------------------------------ passes ---
    def classify_days(self) -> None:
        days = (self.end_cal - self.start).days + 1
        office_days = set(self.b.get("office_days", [0, 1, 2, 3, 4]))
        wfh_every = int(self.b.get("wfh_every_days", 14))
        travel_every = int(self.b.get("travel_every_days", 21))
        travel = self.b.get("travel", {})
        for i in range(days):
            d = self.start + timedelta(days=i)
            kind = "home"
            if d.weekday() in office_days:
                kind = "office"
                if wfh_every and (i % wfh_every) == wfh_every // 2:
                    kind = "wfh"
            self.day_kind[d] = kind
        # travel schedule (history + planner window)
        if travel.get("kind") == "week":
            # every 2nd week: Monday out, Thursday back, away Tue/Wed
            for i in range(days):
                d = self.start + timedelta(days=i)
                if d.weekday() == 0 and ((i // 7) % 2 == 0):
                    self.day_kind[d] = "travel_out"
                    for k in (1, 2):
                        dd = d + timedelta(days=k)
                        if dd <= self.end_cal:
                            self.day_kind[dd] = "away"
                    back = d + timedelta(days=3)
                    if back <= self.end_cal:
                        self.day_kind[back] = "travel_back"
        else:
            for i in range(travel_every // 2, days, travel_every):
                d = self.start + timedelta(days=i)
                if d.weekday() <= 4:
                    self.day_kind[d] = "travel_out"   # day trip
        extra = self.b.get("extra_trip")
        if extra:
            # one two-day trip about a third into the history
            i = days // 3
            d = self.start + timedelta(days=i)
            while d.weekday() > 3:
                d += timedelta(days=1)
            self.day_kind[d] = "travel_extra_out"
            self.day_kind[d + timedelta(days=1)] = "travel_extra_back"

    def build(self) -> Tuple[List[CalendarEvent], List[SimTruthEvent], Dict[date, str]]:
        self.classify_days()
        days = (self.end_cal - self.start).days + 1
        protected_dates = self._protected_dates()
        for i in range(days):
            d = self.start + timedelta(days=i)
            self._build_day(d, i, protected_dates)
        self.events.sort(key=lambda e: e.start)
        return self.events, self.truth, self.day_kind

    def _protected_dates(self) -> set:
        hist_days = (self.today - self.start).days
        n = self.rng.randint(6, 8)
        picks = set()
        for k in range(n):
            base = int((k + 0.5) * hist_days / n)
            d = self.start + timedelta(days=max(0, min(hist_days - 1, base + self.rng.randint(-3, 3))))
            picks.add(d)
        return picks

    def _build_day(self, d: date, i: int, protected_dates: set) -> None:
        plan = DayPlan(d)
        kind = self.day_kind[d]
        dow = d.weekday()
        weekday = dow <= 4
        remote = kind in ("wfh", "home")
        places = MEETING_PLACES_REMOTE if remote else MEETING_PLACES_OFFICE
        travel = self.b.get("travel", {})
        extra = self.b.get("extra_trip") or {}

        # --- travel events
        if kind == "travel_out":
            if travel.get("kind") == "week":
                self.add(d, "Flight ARN->%s 07:05" % travel.get("code", "CPH"), 5.75, 8.5, "travel", "Arlanda", plan=plan,
                         notes=("tz_shift=%+d" % travel.get("tz_shift", 0)) if travel.get("tz_shift") else None)
            else:
                self.add(d, "Flight ARN->%s 07:10" % travel.get("code", "BER"), 5.9, 9.0, "travel", "Arlanda", plan=plan)
                self.add(d, "Flight %s->ARN 19:40" % travel.get("code", "BER"), 19.0, 22.25, "travel", "%s airport" % travel.get("city", "Berlin"), plan=plan)
        elif kind == "travel_back":
            self.add(d, "Flight %s->ARN 17:50" % travel.get("code", "CPH"), 17.25, 20.0, "travel", "%s airport" % travel.get("city", "Copenhagen"), plan=plan)
        elif kind == "travel_extra_out":
            self.add(d, "Flight ARN->%s 08:20" % extra.get("code", "LHR"), 6.75, 10.5, "travel", "Arlanda", plan=plan,
                     notes="tz_shift=%+d" % int(extra.get("tz_shift", 0)))
        elif kind == "travel_extra_back":
            self.add(d, "Flight %s->ARN 18:10" % extra.get("code", "LHR"), 17.0, 21.0, "travel", "%s airport" % extra.get("city", "London"), plan=plan,
                     notes="tz_shift=%+d" % int(extra.get("tz_shift", 0)))

        # --- recurring meetings
        if weekday and kind not in ("home",):
            if dow == 0 and kind not in ("travel_out",):
                self.add(d, "Weekly standup", 9.0, 9.5, "meeting", places[0] if not remote else "Google Meet", attendees=6, recurring_key="mon-standup", plan=plan)
            if dow == 1:
                self.add(d, "1:1 with Maria", 14.0, 14.5, "meeting", "Google Meet", attendees=2, recurring_key="tue-1on1", plan=plan)
            if dow == 3 and kind not in ("travel_back",):
                self.add(d, "Weekly team sync", 10.0, 11.0, "meeting", places[1] if not remote else "Zoom", attendees=8, recurring_key="thu-sync", plan=plan)

        # --- early start (client workshop / early call)
        if weekday and self.rng.random() < float(self.b.get("early_start_prob", 0.05)) and plan.free(7.0, 8.0):
            self.add(d, "Early client workshop" if self.p.key == "sam" else "Early call: APAC partner", 7.0, 8.0, "meeting",
                     "Client site" if kind == "away" else "Zoom", attendees=5, plan=plan)

        # --- meetings
        if weekday:
            lo, hi = self.b.get("meetings_per_day", [3, 7])
            if kind == "home":
                lo, hi = max(0, lo - 2), max(1, hi - 3)
            n_target = self.rng.randint(int(lo), int(hi))
            n_existing = sum(1 for e in self.events if e.start.date() == d and e.type == "meeting")
            b2b = self.rng.random() < float(self.b.get("b2b_prob", 0.3))
            if b2b:
                chain = self.rng.randint(4, 6)
                s = 13.0
                for k in range(chain):
                    dur = self.rng.choice([0.5, 0.75, 1.0])
                    if s + dur > 17.5:
                        break
                    if plan.free(s, s + dur):
                        title = self.rng.choice(MEETING_TITLES)
                        self.add(d, title, s, s + dur, "meeting", self.rng.choice(places), attendees=self.rng.randint(2, 9), plan=plan)
                        n_existing += 1
                    s += dur + (0.0 if self.rng.random() < 0.7 else 0.1667)
            while n_existing < n_target:
                dur_min = self.rng.choice([30, 30, 45, 60])
                s = self._slot(plan, 9.0, 17.0, dur_min)
                if s is None:
                    break
                title = self.rng.choice(MEETING_TITLES)
                self.add(d, title, s, s + dur_min / 60.0, "meeting", "Client site" if kind == "away" else self.rng.choice(places),
                         attendees=self.rng.randint(2, 12), plan=plan)
                n_existing += 1
            # late meeting
            p_late = float(self.b.get("late_meetings_per_week", 1.0)) / 5.0
            if self.rng.random() < p_late:
                s = self.rng.choice([18.0, 18.5, 19.0, 19.0, 19.5])
                dur = self.rng.choice([0.75, 1.0, 1.25, 1.5])
                end = min(20.75, s + dur)
                if plan.free(s, end):
                    self.add(d, self.rng.choice(LATE_TITLES), s, end, "meeting", "Zoom", attendees=self.rng.randint(3, 8), plan=plan)
            # focus blocks
            if self.rng.random() < float(self.b.get("focus_prob", 0.4)):
                s = self._slot(plan, 8.5, 12.0, 90)
                if s is not None:
                    self.add(d, self.rng.choice(FOCUS_TITLES), s, s + 1.5, "focus", None, plan=plan)

        # --- workouts
        for w in self.b.get("workouts", []):
            if w["dow"] == dow and kind not in ("travel_out", "travel_back", "away", "travel_extra_out", "travel_extra_back"):
                jitter = self.rng.choice([-0.25, 0.0, 0.0, 0.25])
                s = float(w["hour"]) + jitter
                e = s + int(w["minutes"]) / 60.0
                if plan.free(s, e):
                    self.add(d, w.get("title", "Workout"), s, e, "workout", w.get("place"), recurring_key="wk-%d-%s" % (dow, w.get("kind")), plan=plan,
                             notes="kind=%s" % w.get("kind", "strength"))
        if weekday and kind in ("office", "wfh") and self.rng.random() < float(self.b.get("late_gym_prob", 0.0)):
            h = float(self.b.get("late_gym_hour", 20.0))
            if plan.free(h, h + 1.0):
                self.add(d, "Gym", h, h + 1.0, "workout", "SATS Odenplan", plan=plan, notes="kind=strength")

        # --- social
        social_prob = 0.0
        for pair in self.b.get("social", []):
            if int(pair[0]) == dow:
                social_prob = float(pair[1])
        if social_prob == 0.0 and weekday:
            social_prob = float(self.b.get("weekday_social_prob", 0.05))
        if kind == "away" and self.rng.random() < float(self.b.get("client_dinner_prob", 0.0)):
            title, venue, _ = self.rng.choice(CLIENT_DINNERS)
            self.add(d, title, 19.0, 22.5, "social", venue, attendees=4, plan=plan)
        elif self.rng.random() < social_prob and kind not in ("travel_out",):
            title, venue, _ = self.rng.choice(SOCIAL)
            s = self.rng.choice([17.5, 18.0, 18.5, 19.0, 19.5, 20.0])
            dur = self.rng.choice([2.5, 3.0, 3.5, 4.0, 4.5])
            end = min(24.5, s + dur)
            if plan.free(s, end):
                self.add(d, title, s, end, "social", venue, attendees=self.rng.randint(2, 6), plan=plan)
        if dow == 6 and self.rng.random() < 0.6:
            self.add(d, "Family dinner", 17.0, 19.5, "social", "Home", attendees=4, recurring_key="sun-family-dinner", plan=plan)

        # --- personal
        if weekday and self.rng.random() < 0.08:
            title, t, h, dur = self.rng.choice(PERSONAL)
            if plan.free(h, h + dur):
                self.add(d, title, h, h + dur, t, None, plan=plan)

        # --- protected evenings
        if d in protected_dates and plan.free(21.0, 22.0):
            self.add(d, "Wind down", 21.0, 22.0, "protected", None, plan=plan)


def generate_events(persona: Persona, start: date, end_cal: date, today: date, rng: random.Random
                    ) -> Tuple[List[CalendarEvent], List[SimTruthEvent], Dict[date, str]]:
    """Generate events for ``start..end_cal`` and attendance truth for past events."""
    return CalendarBuilder(persona, start, end_cal, today, rng).build()
