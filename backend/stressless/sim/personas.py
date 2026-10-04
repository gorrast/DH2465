"""The three demo personas and their design sensitivities (SPEC §5.1).

``Persona.sensitivities`` are *nominal* points-per-unit effects used only to scale the causal
mechanisms in ``physiology.py`` (``ratio = sensitivities[k] / REF_TABLE[k]``). The realised effects
that actually generated the data are computed after generation (``generate.py``).
"""
from __future__ import annotations

from typing import Dict, List

from ..models import Persona

#: Reference (Alex) effect table: every regressor key non-zero so ratios are defined.
REF_TABLE: Dict[str, float] = {
    "meetings_over_3": -2.2,
    "b2b_over_2": -1.5,
    "late_meeting_hours": -4.0,
    "evening_social": -8.0,
    "workout_morning": 5.0,
    "workout_late": -3.0,
    "travel": -9.0,
    "early_start": -3.0,
    "protected_evening": 4.0,
}

HIDDEN_KEYS = ("alcohol", "caffeine_late", "screens_late", "illness", "sleep_debt")

PERSONA_ORDER: List[str] = ["alex", "sam", "robin"]


def _sens(**kw: float) -> Dict[str, float]:
    base = {k: 0.0 for k in REF_TABLE}
    base.update({"alcohol": -4.0, "caffeine_late": -3.0, "screens_late": -2.0, "illness": -12.0, "sleep_debt": 0.0})
    base.update(kw)
    return base


PERSONAS: Dict[str, Persona] = {
    "alex": Persona(
        key="alex", name="Alex",
        tagline="Product lead who lives by the calendar",
        description=("Alex runs product at a Stockholm scale-up. Office Monday to Thursday, home on "
                     "Fridays, a run before work twice a week, after-work on Thursdays and the odd "
                     "customer call that runs late into the evening."),
        resting_hr=56, hrv_ms=48.0, resp_rate=14.6, sleep_need_min=480,
        usual_bedtime=23.083, usual_wake=6.75, weekend_shift_min=60,
        behaviour={
            "office_days": [0, 1, 2, 3],
            "meetings_per_day": [3, 7],
            "late_meetings_per_week": 1.5,
            "b2b_prob": 0.35,
            "workouts": [
                {"dow": 1, "hour": 7.0, "minutes": 45, "kind": "run", "place": "Djurgården loop", "title": "Morning run"},
                {"dow": 3, "hour": 7.0, "minutes": 45, "kind": "run", "place": "Djurgården loop", "title": "Morning run"},
                {"dow": 5, "hour": 10.0, "minutes": 60, "kind": "strength", "place": "SATS Odenplan", "title": "Gym"},
            ],
            "late_gym_prob": 0.14,
            "late_gym_hour": 20.0,
            "social": [[3, 0.5], [5, 0.6]],
            "weekday_social_prob": 0.05,
            "travel_every_days": 21,
            "travel": {"kind": "daytrip", "city": "Berlin", "code": "BER", "tz_shift": 0},
            "wfh_every_days": 14,
            "early_start_prob": 0.06,
            "focus_prob": 0.5,
            "skip_prob": {"workout": 0.12, "social": 0.08, "meeting": 0.03},
        },
        sensitivities=_sens(meetings_over_3=-2.2, b2b_over_2=0.0, late_meeting_hours=-4.0, evening_social=-8.0,
                            workout_morning=5.0, workout_late=-3.0, travel=-9.0, early_start=-3.0,
                            protected_evening=4.0),
    ),
    "sam": Persona(
        key="sam", name="Sam",
        tagline="Consultant: eight meetings and a flight",
        description=("Sam is a management consultant on a client engagement in Copenhagen. Flies out "
                     "Monday morning and back Thursday evening every other week, eight meetings a day, "
                     "client dinners, and an early gym habit."),
        resting_hr=60, hrv_ms=38.0, resp_rate=15.2, sleep_need_min=450,
        usual_bedtime=23.25, usual_wake=6.25, weekend_shift_min=75,
        behaviour={
            "office_days": [0, 1, 2, 3],
            "meetings_per_day": [5, 9],
            "late_meetings_per_week": 2.0,
            "b2b_prob": 0.6,
            "workouts": [
                {"dow": 0, "hour": 6.5, "minutes": 50, "kind": "strength", "place": "Nordic Wellness Vasastan", "title": "Gym"},
                {"dow": 2, "hour": 6.5, "minutes": 50, "kind": "strength", "place": "Nordic Wellness Vasastan", "title": "Gym"},
                {"dow": 4, "hour": 6.5, "minutes": 50, "kind": "strength", "place": "Nordic Wellness Vasastan", "title": "Gym"},
            ],
            "late_gym_prob": 0.04,
            "late_gym_hour": 20.0,
            "social": [[4, 0.55], [5, 0.4]],
            "weekday_social_prob": 0.15,
            "client_dinner_prob": 0.35,
            "travel_every_days": 14,
            "travel": {"kind": "week", "city": "Copenhagen", "code": "CPH", "tz_shift": 0},
            "extra_trip": {"city": "London", "code": "LHR", "tz_shift": -1},
            "wfh_every_days": 21,
            "early_start_prob": 0.15,
            "focus_prob": 0.25,
            "skip_prob": {"workout": 0.15, "social": 0.06, "meeting": 0.03},
        },
        sensitivities=_sens(meetings_over_3=-1.2, b2b_over_2=-1.5, late_meeting_hours=-3.0, evening_social=-5.0,
                            workout_morning=3.0, workout_late=-2.0, travel=-12.0, early_start=-5.0,
                            protected_evening=3.0),
    ),
    "robin": Persona(
        key="robin", name="Robin",
        tagline="Founder: late nights and late workouts",
        description=("Robin founded a small climate-tech company. Few meetings but many investor "
                     "calls in the evening, gym sessions at quarter to nine at night, and a social "
                     "calendar that fills every weekend."),
        resting_hr=52, hrv_ms=62.0, resp_rate=14.0, sleep_need_min=480,
        usual_bedtime=0.25, usual_wake=7.75, weekend_shift_min=60,
        behaviour={
            "office_days": [0, 1, 2, 3, 4],
            "meetings_per_day": [1, 5],
            "late_meetings_per_week": 2.0,
            "b2b_prob": 0.15,
            "workouts": [
                {"dow": 0, "hour": 20.75, "minutes": 60, "kind": "strength", "place": "Friskis Södermalm", "title": "Gym"},
                {"dow": 2, "hour": 20.75, "minutes": 60, "kind": "strength", "place": "Friskis Södermalm", "title": "Gym"},
                {"dow": 4, "hour": 20.75, "minutes": 60, "kind": "strength", "place": "Friskis Södermalm", "title": "Gym"},
                {"dow": 6, "hour": 10.0, "minutes": 50, "kind": "run", "place": "Årstaviken", "title": "Sunday run"},
            ],
            "late_gym_prob": 0.0,
            "late_gym_hour": 20.75,
            "social": [[4, 0.7], [5, 0.7]],
            "weekday_social_prob": 0.15,
            "travel_every_days": 24,
            "travel": {"kind": "daytrip", "city": "Göteborg", "code": "GOT", "tz_shift": 0},
            "extra_trip": {"city": "Helsinki", "code": "HEL", "tz_shift": 1},
            "wfh_every_days": 10,
            "early_start_prob": 0.03,
            "focus_prob": 0.6,
            "skip_prob": {"workout": 0.12, "social": 0.08, "meeting": 0.03},
        },
        sensitivities=_sens(meetings_over_3=-1.2, b2b_over_2=0.0, late_meeting_hours=-3.0, evening_social=-8.0,
                            workout_morning=2.0, workout_late=-6.0, travel=-6.0, early_start=-2.0,
                            protected_evening=6.0),
    ),
}


def get_persona(key: str) -> Persona:
    if key not in PERSONAS:
        raise KeyError("unknown persona %r (choose from %s)" % (key, ", ".join(PERSONA_ORDER)))
    return PERSONAS[key]


def ratios_for(persona: Persona) -> Dict[str, float]:
    """Mechanism scaling factors relative to the reference table (0 = mechanism absent)."""
    return {k: float(persona.sensitivities.get(k, 0.0)) / REF_TABLE[k] for k in REF_TABLE}
