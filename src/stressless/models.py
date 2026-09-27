"""Shared data model for StressLess.

Rules
-----
* Every datetime is timezone-aware in the persona's zone (see timeutil).
* ``to_jsonable`` turns any dataclass tree into JSON-safe dicts (datetimes ->
  ISO strings); ``from_dict`` reverses it using the dataclass type hints.
* Simulator ground truth lives in ``SimTruth``. ``stressless.engine`` must never
  import or read it; only the Lab/validation code compares the two.
"""
from __future__ import annotations

import dataclasses
import json
import typing
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from .timeutil import DEFAULT_TZ, parse_date, parse_dt

EVENT_TYPES = ("meeting", "focus", "workout", "social", "travel", "personal", "protected")
PLACE_TYPES = ("home", "office", "gym", "restaurant", "bar", "transit", "airport",
               "hotel", "away", "outdoors", "other")
WORKOUT_SLOTS = ("none", "morning", "midday", "evening", "late")
STAGE_KINDS = ("awake", "core", "deep", "rem")
CONFIDENCE_LEVELS = ("high", "medium", "low")


# --------------------------------------------------------------------------- #
# Persona
# --------------------------------------------------------------------------- #
@dataclass
class Persona:
    key: str                       # "alex" | "sam" | "robin"
    name: str
    tagline: str                   # one line, shown in the UI
    description: str
    tz: str = DEFAULT_TZ
    home_city: str = "Stockholm"
    # physiology baselines
    resting_hr: int = 56
    hrv_ms: float = 48.0
    resp_rate: float = 14.6
    sleep_need_min: int = 450
    usual_bedtime: float = 22.75   # hours on weekdays (22.75 = 22:45)
    usual_wake: float = 6.75
    weekend_shift_min: int = 60
    # opaque knobs consumed only by the simulator
    behaviour: Dict[str, Any] = field(default_factory=dict)
    sensitivities: Dict[str, float] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Raw sources: calendar, location, watch
# --------------------------------------------------------------------------- #
@dataclass
class CalendarEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    type: str                                  # EVENT_TYPES
    location_hint: Optional[str] = None        # "Office", "Google Meet", "SATS Odenplan", "Arlanda"
    attendees: int = 0
    recurring_key: Optional[str] = None        # e.g. "mon-standup"; None for one-offs
    source: str = "demo"                       # demo | ics | user | suggestion
    attended: Optional[bool] = None            # None = unknown; set by reality-check answers/imports
    notes: Optional[str] = None

    @property
    def duration_min(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class LocationVisit:
    id: str
    place_type: str                            # PLACE_TYPES
    place_name: str
    start: datetime
    end: datetime
    lat: float = 59.3293
    lon: float = 18.0686
    source: str = "demo"

    @property
    def duration_min(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class WatchWorkout:
    """A workout the watch detected on its own (independent of the calendar)."""
    id: str
    kind: str                                  # run | strength | cycling | yoga | other
    start: datetime
    end: datetime
    avg_hr: int
    max_hr: int
    calories: int = 0


@dataclass
class DailyActivity:
    date: date
    steps: int
    active_minutes: int
    workouts: List[WatchWorkout] = field(default_factory=list)
    hourly_steps: List[int] = field(default_factory=list)   # 24 entries


@dataclass
class HeartRateDay:
    """One calendar day of minute-level heart rate. ``bpm[i]`` is minute i of the
    local day (0..1439); ``None`` means the watch was not worn (charging, off)."""
    date: date
    bpm: List[Optional[int]]

    def worn_fraction(self) -> float:
        if not self.bpm:
            return 0.0
        return sum(1 for b in self.bpm if b is not None) / float(len(self.bpm))


@dataclass
class SleepStage:
    kind: str                                  # STAGE_KINDS
    start: datetime
    end: datetime


@dataclass
class SleepNight:
    """The night that starts on the evening of ``date`` (see timeutil.night_date)."""
    date: date
    worn: bool
    in_bed_start: Optional[datetime] = None
    sleep_onset: Optional[datetime] = None
    wake_time: Optional[datetime] = None
    out_of_bed: Optional[datetime] = None
    stages: List[SleepStage] = field(default_factory=list)
    interruptions: int = 0
    awake_min: int = 0
    duration_min: int = 0                      # minutes asleep (core+deep+rem)
    deep_min: int = 0
    rem_min: int = 0
    core_min: int = 0
    hrv_ms: Optional[float] = None             # overnight SDNN
    resting_hr: Optional[int] = None
    resp_rate: Optional[float] = None
    wrist_temp_dev: Optional[float] = None     # degC vs personal baseline
    spo2: Optional[float] = None               # percent
    score: Optional[int] = None                # 0..100, None when not worn
    score_parts: Dict[str, int] = field(default_factory=dict)   # duration/consistency/interruptions
    score_source: str = "stressless"           # "apple" | "stressless"


# --------------------------------------------------------------------------- #
# Simulator ground truth (engine must never read)
# --------------------------------------------------------------------------- #
@dataclass
class SimTruthNight:
    date: date
    contributions: Dict[str, float]            # factor key -> sleep-score points (signed)
    hidden: Dict[str, Any] = field(default_factory=dict)   # alcohol_units, caffeine_late, illness, screens_late
    noise_points: float = 0.0
    counterfactual_score: Optional[int] = None  # score with all calendar factors removed
    regressors: Dict[str, float] = field(default_factory=dict)   # attended-event regressors the sim used


@dataclass
class SimTruthEvent:
    event_id: str
    attended: bool
    reason: Optional[str] = None               # "skipped" | "wfh" | "cancelled" | None


@dataclass
class SimTruth:
    nights: List[SimTruthNight] = field(default_factory=list)
    events: List[SimTruthEvent] = field(default_factory=list)
    unbooked: List[str] = field(default_factory=list)      # visit ids that had no calendar event
    effect_table: Dict[str, float] = field(default_factory=dict)   # realised TOTAL effect incl. correlated hidden factors
    effect_table_direct: Dict[str, float] = field(default_factory=dict)   # realised direct effect (hidden factors removed)
    effect_table_design: Dict[str, float] = field(default_factory=dict)   # nominal points-per-unit from Persona.sensitivities
    hidden_summary: Dict[str, Any] = field(default_factory=dict)          # counts of hidden-factor nights etc.


# --------------------------------------------------------------------------- #
# Engine: features and model
# --------------------------------------------------------------------------- #
REGRESSOR_KEYS = (
    "meetings_over_3", "b2b_over_2", "late_meeting_hours", "evening_social",
    "workout_morning", "workout_late", "travel", "early_start",
    "protected_evening", "is_weekend",
)

FACTOR_LABELS = {
    "meetings_over_3": "Meeting load",
    "b2b_over_2": "Back-to-back meetings",
    "late_meeting_hours": "Late meetings",
    "evening_social": "Evening social",
    "workout_morning": "Morning workout",
    "workout_late": "Late workout",
    "travel": "Travel day",
    "early_start": "Early start",
    "protected_evening": "Protected evening",
    "is_weekend": "Weekend",
}


@dataclass
class DayFeatures:
    date: date
    n_events: int = 0
    n_meetings: int = 0
    meeting_minutes: int = 0
    max_b2b_run: int = 0                       # longest chain of meetings with <=10 min gaps
    first_start_hour: Optional[float] = None
    last_meeting_end_hour: Optional[float] = None
    late_meeting_hours: float = 0.0            # max(0, last_meeting_end_hour - 18)
    evening_social: int = 0                    # social event ending >= 20:30
    social_end_hour: Optional[float] = None
    workout_slot: str = "none"                 # WORKOUT_SLOTS
    workout_minutes: int = 0
    travel: int = 0
    tz_shift_hours: float = 0.0
    protected_evening: int = 0
    early_start: int = 0                       # first event < 07:30
    is_weekend: int = 0
    dow: int = 0                               # Monday = 0
    event_ids: List[str] = field(default_factory=list)

    def regressors(self) -> Dict[str, float]:
        return {
            "meetings_over_3": float(max(0, self.n_meetings - 3)),
            "b2b_over_2": float(max(0, self.max_b2b_run - 2)),
            "late_meeting_hours": float(self.late_meeting_hours),
            "evening_social": float(self.evening_social),
            "workout_morning": 1.0 if self.workout_slot == "morning" else 0.0,
            "workout_late": 1.0 if self.workout_slot == "late" else 0.0,
            "travel": float(self.travel),
            "early_start": float(self.early_start),
            "protected_evening": float(self.protected_evening),
            "is_weekend": float(self.is_weekend),
        }


@dataclass
class Coefficient:
    key: str
    label: str
    value: float                               # points per unit
    ci_low: float
    ci_high: float
    n_active: int                              # nights where regressor != 0


@dataclass
class ModelSummary:
    n_nights: int
    r2: float
    rmse: float
    intercept: float
    coefficients: List[Coefficient]
    history_days: Optional[int] = None
    target: str = "score"
    ridge_lambda: float = 1.0
    r2_loo: Optional[float] = None             # leave-one-out R^2 (honest, shown in footer)
    rmse_loo: Optional[float] = None
    insufficient: bool = False                 # n < 10 worn nights: no causes, proximal facts only
    calm_day_pred: Optional[float] = None      # prediction for a calm day (all regressors 0)
    n_total_nights: Optional[int] = None       # nights in the history window (worn or not)
    n_unworn: int = 0


# --------------------------------------------------------------------------- #
# Engine: explanations
# --------------------------------------------------------------------------- #
@dataclass
class Evidence:
    kind: str                                  # "hr" | "hrv" | "rhr" | "bedtime" | "duration" | "interruptions" | "location" | "calendar" | "temp" | "resp" | "spo2"
    text: str                                  # "Heart rate 12 bpm above your evening norm until 22:00"
    value: Optional[float] = None
    baseline: Optional[float] = None
    unit: Optional[str] = None
    series: Optional[List[Optional[float]]] = None   # sparkline data
    series_baseline: Optional[List[Optional[float]]] = None
    series_start: Optional[datetime] = None
    series_step_min: int = 5


@dataclass
class Cause:
    rank: int
    factor: str                                # REGRESSOR key
    title: str                                 # "Meeting until 20:30"
    detail: str                                # one sentence of evidence
    points: float                              # signed effect on sleep score
    direction: str                             # "hurt" | "helped"
    confidence: str                            # CONFIDENCE_LEVELS
    evidence: List[Evidence] = field(default_factory=list)
    event_ids: List[str] = field(default_factory=list)
    n_similar: int = 0                         # nights with this factor active in history
    points_low: Optional[float] = None         # 95 % bootstrap interval of the contribution
    points_high: Optional[float] = None


@dataclass
class Suggestion:
    id: str
    kind: str                                  # "protect_evening" | "move_meeting" | "buffer" | "move_workout" | "later_start" | "recovery_day"
    title: str                                 # "Protect 21:00 to 22:00 tonight"
    body: str
    predicted_gain: float                      # sleep-score points
    for_date: date
    proposed_event: Optional[CalendarEvent] = None
    accepted: bool = False
    related_factor: Optional[str] = None
    gain_low: Optional[float] = None
    gain_high: Optional[float] = None


@dataclass
class RecoveryMetric:
    key: str                                   # hrv_ms | resting_hr | resp_rate | wrist_temp_dev | spo2
    label: str
    value: Optional[float]
    baseline: Optional[float]
    delta: Optional[float]
    delta_pct: Optional[float]
    z: Optional[float]
    unit: str
    good_direction: str                        # "up" | "down" | "zero"
    status: str                                # "good" | "typical" | "watch" | "unknown"
    series: List[Optional[float]] = field(default_factory=list)   # last 14 nights


@dataclass
class MorningReport:
    date: date                                 # the morning
    night_date: date                           # = date - 1
    night: Optional[SleepNight]
    score: Optional[int]
    baseline_score: Optional[float]
    delta_vs_baseline: Optional[float]
    causes: List[Cause]
    helpers: List[Cause]
    proximal: List[Evidence]
    recovery: List[RecoveryMetric]
    narrative: str
    reasoning_mode: str                        # "rules" | "claude"
    suggestions: List[Suggestion]
    predicted_score: Optional[float]
    residual: Optional[float]                  # actual - predicted
    unexplained_note: Optional[str]            # set when |residual| large or hidden signals
    model: Optional[ModelSummary]
    missing_data: Optional[str] = None         # e.g. "No watch data for this night (charging?)"
    confidence_note: str = ""
    calm_day_pred: Optional[float] = None      # "a calm day would predict ..."
    rating: Optional[str] = None               # Apple-style band label for the score
    sources: Dict[str, Any] = field(default_factory=dict)   # {"calendar_events": 6, "maps_places": 4, "watch_minutes": 1392}


@dataclass
class RealityCheck:
    id: str
    date: date
    kind: str                                  # "booked_not_seen" | "seen_not_booked" | "location_mismatch"
    question: str                              # "Did you actually go to the gym on Tue 18:00?"
    status: str                                # "open" | "yes" | "no"
    event_id: Optional[str] = None
    visit_id: Optional[str] = None
    evidence: List[Evidence] = field(default_factory=list)
    suggested_event: Optional[CalendarEvent] = None
    answered_at: Optional[datetime] = None
    consequence: Optional[str] = None          # what changes when answered


@dataclass
class HabitBucket:
    label: str
    n: int
    mean_score: Optional[float]
    lo: Optional[float] = None
    hi: Optional[float] = None


@dataclass
class Habit:
    key: str                                   # e.g. "late_meeting", "morning_workout"
    title: str
    description: str
    group: str                                 # "calendar" | "workout" | "social" | "travel" | "routine"
    n_with: int
    n_without: int
    mean_with: Optional[float]
    mean_without: Optional[float]
    effect: Optional[float]                    # mean_with - mean_without (points)
    ci_low: Optional[float]
    ci_high: Optional[float]
    adjusted_effect: Optional[float]           # model coefficient contribution
    direction: str                             # "good" | "bad" | "neutral"
    confidence: str                            # CONFIDENCE_LEVELS
    example_dates: List[date] = field(default_factory=list)
    metric_effects: Dict[str, Optional[float]] = field(default_factory=dict)  # hrv_ms pct, resting_hr bpm
    raw_effect: Optional[float] = None         # unstratified mean difference ("simple comparison")
    rank_score: Optional[float] = None         # conservative effect x confidence weight used for ordering


@dataclass
class WhatIfResult:
    date: date
    baseline_pred: float
    modified_pred: float
    delta: float
    rmse: float
    features_before: DayFeatures
    features_after: DayFeatures
    changed_factors: List[str]
    events_after: List[CalendarEvent]
    delta_low: Optional[float] = None          # 95 % interval from bootstrap coefficient draws
    delta_high: Optional[float] = None


# --------------------------------------------------------------------------- #
# Dataset container
# --------------------------------------------------------------------------- #
@dataclass
class Dataset:
    persona: Persona
    seed: int
    source: str                                # "demo" | "imported"
    start: date                                # first day with biometrics
    end: date                                  # last night date (normally yesterday)
    today: date                                # the "morning" the demo opens on
    events: List[CalendarEvent] = field(default_factory=list)
    visits: List[LocationVisit] = field(default_factory=list)
    hr_days: List[HeartRateDay] = field(default_factory=list)
    nights: List[SleepNight] = field(default_factory=list)
    activity: List[DailyActivity] = field(default_factory=list)
    truth: Optional[SimTruth] = None
    generated_at: Optional[datetime] = None
    showcase: bool = True

    def __post_init__(self) -> None:
        self.reindex()

    # -- indexes (plain attributes, not dataclass fields) --------------------
    def reindex(self) -> None:
        self._events_by_day: Dict[date, List[CalendarEvent]] = {}
        for ev in self.events:
            self._events_by_day.setdefault(ev.start.date(), []).append(ev)
        for lst in self._events_by_day.values():
            lst.sort(key=lambda e: e.start)
        self._events_by_id: Dict[str, CalendarEvent] = {e.id: e for e in self.events}
        self._visits_by_day: Dict[date, List[LocationVisit]] = {}
        for v in self.visits:
            d = v.start.date()
            self._visits_by_day.setdefault(d, []).append(v)
            if v.end.date() != d:
                self._visits_by_day.setdefault(v.end.date(), []).append(v)
        self._visits_by_id: Dict[str, LocationVisit] = {v.id: v for v in self.visits}
        self._hr: Dict[date, HeartRateDay] = {h.date: h for h in self.hr_days}
        self._nights: Dict[date, SleepNight] = {n.date: n for n in self.nights}
        self._activity: Dict[date, DailyActivity] = {a.date: a for a in self.activity}

    def events_on(self, d: date, include_unattended: bool = False) -> List[CalendarEvent]:
        evs = self._events_by_day.get(d, [])
        if include_unattended:
            return list(evs)
        return [e for e in evs if e.attended is not False]

    def event(self, event_id: str) -> Optional[CalendarEvent]:
        return self._events_by_id.get(event_id)

    def visits_on(self, d: date) -> List[LocationVisit]:
        return sorted(self._visits_by_day.get(d, []), key=lambda v: v.start)

    def visit(self, visit_id: str) -> Optional[LocationVisit]:
        return self._visits_by_id.get(visit_id)

    def hr(self, d: date) -> Optional[HeartRateDay]:
        return self._hr.get(d)

    def night(self, d: date) -> Optional[SleepNight]:
        return self._nights.get(d)

    def activity_on(self, d: date) -> Optional[DailyActivity]:
        return self._activity.get(d)

    def night_dates(self) -> List[date]:
        return sorted(self._nights.keys())

    def add_event(self, ev: CalendarEvent) -> None:
        self.events.append(ev)
        self.reindex()

    def set_attended(self, event_id: str, attended: Optional[bool]) -> None:
        ev = self._events_by_id.get(event_id)
        if ev is not None:
            ev.attended = attended


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #
def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses/datetimes into JSON-safe structures."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat(timespec="minutes")
    if isinstance(obj, date):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        out = {}
        for f in fields(obj):
            out[f.name] = to_jsonable(getattr(obj, f.name))
        return out
    if isinstance(obj, dict):
        return {str(to_jsonable(k)): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    return str(obj)


def dumps(obj: Any, **kw: Any) -> str:
    return json.dumps(to_jsonable(obj), ensure_ascii=False, **kw)


_NoneType = type(None)


def _decode(tp: Any, value: Any, tzname: Optional[str]) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is Union:
        non_none = [a for a in args if a is not _NoneType]
        if len(non_none) == 1:
            return _decode(non_none[0], value, tzname)
        return value
    if origin in (list, List):
        inner = args[0] if args else Any
        return [_decode(inner, v, tzname) for v in value]
    if origin in (tuple, Tuple):
        return tuple(_decode(args[i] if i < len(args) else Any, v, tzname) for i, v in enumerate(value))
    if origin in (dict, Dict):
        ktp = args[0] if args else Any
        vtp = args[1] if len(args) > 1 else Any
        return {_decode(ktp, k, tzname): _decode(vtp, v, tzname) for k, v in value.items()}
    if tp is datetime:
        return parse_dt(value, tzname)
    if tp is date:
        return parse_date(value)
    if tp is float and isinstance(value, (int, float)):
        return float(value)
    if isinstance(tp, type) and is_dataclass(tp) and isinstance(value, dict):
        return from_dict(tp, value, tzname)
    return value


def from_dict(cls: Any, data: Dict[str, Any], tzname: Optional[str] = None) -> Any:
    """Rebuild a dataclass from ``to_jsonable`` output. Unknown keys are ignored."""
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name in data:
            kwargs[f.name] = _decode(hints.get(f.name, Any), data[f.name], tzname)
    return cls(**kwargs)


def dataset_from_dict(data: Dict[str, Any]) -> Dataset:
    tzname = (data.get("persona") or {}).get("tz") or DEFAULT_TZ
    return from_dict(Dataset, data, tzname)


def new_id(prefix: str, *parts: Any) -> str:
    """Deterministic id: prefix + '-' + joined parts (safe for URLs)."""
    body = "-".join(str(p) for p in parts)
    body = "".join(ch if ch.isalnum() or ch in "-_:" else "_" for ch in body)
    return f"{prefix}-{body}"
