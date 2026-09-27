"""Google-Maps-like location history for the digital twin (SPEC §5.3)."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..models import CalendarEvent, LocationVisit, Persona, SimTruthEvent, new_id
from ..timeutil import at, day_hour

HOME = ("home", "Home", 59.3421, 18.0498)
OFFICE = ("office", "Office, Vasagatan", 59.3315, 18.0592)
UNBOOKED_GYM = ("gym", "SATS Odenplan", 59.3428, 18.0498)
UNBOOKED_FOOD = [("restaurant", "Restaurang Prinsen", 59.3355, 18.0740), ("bar", "Omnipollos hatt", 59.3175, 18.0714)]


def _place_for_event(ev: CalendarEvent) -> Tuple[str, str]:
    hint = (ev.location_hint or "").lower()
    if ev.type == "workout":
        if any(k in hint for k in ("loop", "viken", "park", "run")):
            return "outdoors", ev.location_hint or "Outdoors"
        return "gym", ev.location_hint or "Gym"
    if ev.type == "social":
        if "home" in hint:
            return "home", "Home"
        if any(k in hint for k in ("bar", "häktet", "debaser", "arms", "hatt")):
            return "bar", ev.location_hint or "Bar"
        return "restaurant", ev.location_hint or "Restaurant"
    if ev.type == "travel":
        return "airport", ev.location_hint or "Airport"
    return "other", ev.location_hint or "Other"


class Segment:
    __slots__ = ("start", "end", "ptype", "name")

    def __init__(self, start: float, end: float, ptype: str, name: str) -> None:
        self.start, self.end, self.ptype, self.name = start, end, ptype, name


def _insert(segments: List[Segment], new: Segment) -> None:
    """Insert ``new`` (day-relative hours), trimming/splitting what it overlaps."""
    out: List[Segment] = []
    for s in segments:
        if s.end <= new.start or s.start >= new.end:
            out.append(s)
            continue
        if s.start < new.start:
            out.append(Segment(s.start, new.start, s.ptype, s.name))
        if s.end > new.end:
            out.append(Segment(new.end, s.end, s.ptype, s.name))
    out.append(new)
    out.sort(key=lambda x: x.start)
    segments[:] = out


def generate_visits(persona: Persona, events: Sequence[CalendarEvent], truth_events: Sequence[SimTruthEvent],
                    day_kind: Dict[date, str], start: date, end: date, rng: random.Random,
                    forced_unbooked_gym: Optional[Sequence[date]] = None,
                    forced_unbooked_bar: Optional[Sequence[date]] = None,
                    protected_days: Optional[Set[date]] = None) -> Tuple[List[LocationVisit], List[str]]:
    """Build visits for ``start..end``. Returns (visits, ids of unbooked activity visits)."""
    tz = persona.tz
    attended = {t.event_id: t.attended for t in truth_events}
    by_day: Dict[date, List[CalendarEvent]] = {}
    for ev in events:
        by_day.setdefault(ev.start.date(), []).append(ev)
    protected_days = protected_days or set()
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    # choose unbooked activity days and phone-off days
    candidates_gym = [d for d in days if d.weekday() <= 3 and not any(e.type == "workout" for e in by_day.get(d, []))
                      and day_kind.get(d) in ("office", "wfh") and d not in protected_days]
    rng.shuffle(candidates_gym)
    unbooked_gym: Set[date] = set(list(forced_unbooked_gym or []))
    for d in candidates_gym:
        if len(unbooked_gym) >= rng.randint(3, 5):
            break
        unbooked_gym.add(d)
    candidates_food = [d for d in days if not any(e.type == "social" for e in by_day.get(d, [])) and d.weekday() in (1, 2, 4)
                       and day_kind.get(d) in ("office", "wfh", "home") and d not in unbooked_gym and d not in protected_days]
    rng.shuffle(candidates_food)
    unbooked_food: Set[date] = set(list(forced_unbooked_bar or []))
    for d in candidates_food:
        if len(unbooked_food) >= rng.randint(2, 3):
            break
        unbooked_food.add(d)
    gap_candidates = [d for d in days if d not in protected_days and d not in unbooked_gym and d not in unbooked_food
                      and (end - d).days > 8]
    rng.shuffle(gap_candidates)
    phone_off: Set[date] = set(gap_candidates[: rng.randint(2, 3)])

    visits: List[LocationVisit] = []
    unbooked_ids: List[str] = []
    away_city = (persona.behaviour.get("travel") or {}).get("city", "Copenhagen")

    for d in days:
        if d in phone_off:
            continue
        kind = day_kind.get(d, "home")
        segs: List[Segment] = [Segment(0.0, 24.0, HOME[0], HOME[1])]
        if kind == "office":
            j = rng.uniform(-0.33, 0.33)
            _insert(segs, Segment(7.9 + j, 8.5 + j, "transit", "Commute"))
            _insert(segs, Segment(8.5 + j, 17.5 + j, OFFICE[0], OFFICE[1]))
            _insert(segs, Segment(17.5 + j, 18.1 + j, "transit", "Commute"))
        elif kind == "away":
            _insert(segs, Segment(0.0, 8.0, "hotel", "Hotel %s" % away_city))
            _insert(segs, Segment(8.0, 8.5, "transit", "Taxi"))
            _insert(segs, Segment(8.5, 18.0, "away", "Client site, %s" % away_city))
            _insert(segs, Segment(18.0, 18.5, "transit", "Taxi"))
            _insert(segs, Segment(18.5, 24.0, "hotel", "Hotel %s" % away_city))
        # attended physical events
        for ev in sorted(by_day.get(d, []), key=lambda e: e.start):
            if ev.type not in ("workout", "social", "travel"):
                continue
            if attended.get(ev.id) is False:
                continue
            s_h = day_hour(ev.start, d)
            e_h = min(24.0, day_hour(ev.end, d))
            if ev.type == "travel":
                title = ev.title.lower()
                outbound = "arn->" in title
                if outbound:
                    _insert(segs, Segment(max(0.0, s_h - 0.75), s_h, "transit", "Taxi to Arlanda"))
                    _insert(segs, Segment(s_h, s_h + 1.0, "airport", "Arlanda"))
                    _insert(segs, Segment(s_h + 1.0, e_h, "transit", "In the air"))
                    if kind in ("travel_out", "travel_extra_out") and (persona.behaviour.get("travel") or {}).get("kind") == "week" or kind == "travel_extra_out":
                        city = away_city if kind == "travel_out" else (persona.behaviour.get("extra_trip") or {}).get("city", "London")
                        _insert(segs, Segment(e_h, 18.5, "away", "Client site, %s" % city))
                        _insert(segs, Segment(18.5, 24.0, "hotel", "Hotel %s" % city))
                    else:
                        _insert(segs, Segment(e_h, min(24.0, e_h + 9.0), "away", "%s" % away_city))
                else:
                    city = away_city if kind == "travel_back" else (persona.behaviour.get("extra_trip") or {}).get("city", away_city)
                    _insert(segs, Segment(0.0, s_h - 0.5, "away", "%s" % city))
                    _insert(segs, Segment(s_h - 0.5, s_h + 0.75, "airport", "%s airport" % city))
                    _insert(segs, Segment(s_h + 0.75, e_h, "transit", "In the air"))
                    _insert(segs, Segment(e_h, min(24.0, e_h + 0.75), "transit", "Taxi home"))
                continue
            ptype, name = _place_for_event(ev)
            if ptype == "home":
                continue
            _insert(segs, Segment(max(0.0, s_h - 0.2), s_h, "transit", "On the way"))
            _insert(segs, Segment(s_h, e_h, ptype, name))
            if e_h < 23.8:
                _insert(segs, Segment(e_h, min(24.0, e_h + 0.25), "transit", "On the way home"))
        if d in unbooked_gym:
            s_h = rng.choice([18.0, 18.083, 18.25])
            _insert(segs, Segment(s_h - 0.2, s_h, "transit", "On the way"))
            _insert(segs, Segment(s_h, s_h + rng.choice([1.0, 1.083, 1.17]), UNBOOKED_GYM[0], UNBOOKED_GYM[1]))
        if d in unbooked_food:
            ptype, name, _, _ = rng.choice(UNBOOKED_FOOD)
            s_h = rng.choice([18.5, 19.0, 19.5])
            _insert(segs, Segment(s_h, s_h + rng.choice([1.5, 2.0, 2.5]), ptype, name))

        seq = 0
        for s in segs:
            if s.end - s.start < 0.05:
                continue
            vid = new_id("vis", persona.key, d, seq)
            seq += 1
            lat, lon = HOME[2], HOME[3]
            if s.ptype == "office":
                lat, lon = OFFICE[2], OFFICE[3]
            elif s.ptype == "gym":
                lat, lon = UNBOOKED_GYM[2], UNBOOKED_GYM[3]
            visits.append(LocationVisit(id=vid, place_type=s.ptype, place_name=s.name,
                                        start=at(d, s.start, tzname=tz), end=at(d, s.end, tzname=tz), lat=lat, lon=lon))
            if (d in unbooked_gym and s.ptype == "gym" and s.name == UNBOOKED_GYM[1]) or \
               (d in unbooked_food and s.ptype in ("restaurant", "bar") and s.name in [f[1] for f in UNBOOKED_FOOD]):
                unbooked_ids.append(vid)
    return visits, unbooked_ids
