"""The social page: groups of friends who compare a few chosen metrics, week by week and over a season.

    GET /api/social    {"week": {...}, "weeks": [...], "metrics": {...}, "members": {...}, "groups": [...],
                        "challenges": [...]}

The signed-in person's own numbers are computed from their data (the same nights, screen time and unlocks the other
pages read). Friends, groups and challenges are not in the database yet: the friends are fixed example profiles with
week-to-week variation, the same on every request, so the page shows how the social side works.

Every board compares people on something comparable between them: scores, minutes, counts, or a change against the
person's own usual (HRV and sleep improvement). Raw HRV, resting heart rate, alcohol and coffee are never ranked.
"""
from __future__ import annotations

import random
import statistics
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..engine import baselines as bl
from ..models import Dataset, to_jsonable
from . import session
from .auth import Principal, current_principal
from .reports import current_periods

router = APIRouter()
SEASON_WEEKS = 4                               # the longer-term view: the last four full weeks
USUAL_DAYS = 28                                # a person's usual: the four weeks before the season
FOCUS_FROM, FOCUS_TO = 8, 22                   # waking hours the longest phone-free stretch is looked for in
QUIET_EVENING_MIN = 15                         # an evening counts as phone-free under this many minutes after 22:00
POINTS = (3, 2, 1)                             # season points for first, second and third on a weekly board


# --------------------------------------------------------------------------- #
# Metrics: value for a run of days, from the person's own data
# --------------------------------------------------------------------------- #
def _mean(vals: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return round(statistics.fmean(vals), 1) if vals else None


def _scores(ds: Dataset, days: List[date]) -> List[Optional[float]]:
    return [bl.night_metric(ds.night(d), "score") for d in days]


def _longest_phone_free(ds: Dataset, d: date) -> Optional[float]:
    """The longest stretch between FOCUS_FROM and FOCUS_TO without a phone unlock, in minutes."""
    if ds.metric_on(d, "screen.pickups") is None:
        return None
    marks = [FOCUS_FROM * 60] + sorted(t.hour * 60 + t.minute for t in ds.unlocks_on(d)
                                       if FOCUS_FROM <= t.hour < FOCUS_TO) + [FOCUS_TO * 60]
    return float(max(b - a for a, b in zip(marks, marks[1:])))


def _onset_spread(ds: Dataset, days: List[date]) -> Optional[float]:
    onsets = [v for v in (bl.night_metric(ds.night(d), "onset_min") for d in days) if v is not None]
    return round(statistics.pstdev(onsets), 1) if len(onsets) >= 3 else None


def _hrv_vs_usual(ds: Dataset, days: List[date], usual: List[date]) -> Optional[float]:
    now = _mean([bl.night_metric(ds.night(d), "hrv_ms") for d in days])
    before = _mean([bl.night_metric(ds.night(d), "hrv_ms") for d in usual])
    return round(100.0 * (now / before - 1.0), 1) if now and before else None


def _sleep_vs_usual(ds: Dataset, days: List[date], usual: List[date]) -> Optional[float]:
    now, before = _mean(_scores(ds, days)), _mean(_scores(ds, usual))
    return round(now - before, 1) if now is not None and before is not None else None


METRICS: Dict[str, Dict[str, Any]] = {
    "sleep_improved": {"label": "Most improved sleep", "unit": "points vs usual", "better": "up", "relative": True,
                       "get": _sleep_vs_usual},
    "sleep_score": {"label": "Best sleep score", "unit": "points", "better": "up",
                    "get": lambda ds, days, usual: _mean(_scores(ds, days))},
    "bedtime": {"label": "Steadiest bedtime", "unit": "min spread", "better": "down",
                "get": lambda ds, days, usual: _onset_spread(ds, days)},
    "focus": {"label": "Longest phone-free stretch", "unit": "min a day", "better": "up",
              "get": lambda ds, days, usual: _mean([_longest_phone_free(ds, d) for d in days])},
    "screen": {"label": "Least screen time", "unit": "min a day", "better": "down",
               "get": lambda ds, days, usual: _mean([ds.metric_on(d, "screen.minutes") for d in days])},
    "evenings": {"label": "Phone-free evenings", "unit": "a week", "better": "up",
                 "get": lambda ds, days, usual: round(7.0 * sum(1 for d in days if (ds.metric_on(d, "screen.late_minutes") or 99) < QUIET_EVENING_MIN)
                                                      / max(1, sum(1 for d in days if ds.metric_on(d, "screen.late_minutes") is not None)), 1)},
    "steps": {"label": "Most steps", "unit": "a day", "better": "up",
              "get": lambda ds, days, usual: _mean([float(a.steps) if (a := ds.activity_on(d)) else None for d in days])},
    "recovery": {"label": "Best recovery", "unit": "% HRV vs usual", "better": "up", "relative": True,
                 "get": _hrv_vs_usual},
}


# --------------------------------------------------------------------------- #
# Friends: example profiles (their usual value per metric, and how much a week varies around it)
# --------------------------------------------------------------------------- #
ME = "Hugo Wigh"
FRIENDS: Dict[str, Dict[str, float]] = {
    "Nima Tehranchi":  {"sleep_score": 76, "bedtime": 47, "focus": 52, "screen": 228, "evenings": 2.0, "steps": 8100, "hrv": 51},
    "Knut Ovesjö":     {"sleep_score": 73, "bedtime": 58, "focus": 44, "screen": 251, "evenings": 1.5, "steps": 7300, "hrv": 58},
    "Marcus Pramborg": {"sleep_score": 79, "bedtime": 38, "focus": 61, "screen": 196, "evenings": 3.0, "steps": 6600, "hrv": 46},
    "Gustaf Salenius": {"sleep_score": 74, "bedtime": 52, "focus": 49, "screen": 238, "evenings": 1.5, "steps": 9200, "hrv": 63},
    "Hugo Ankarcrona": {"sleep_score": 78, "bedtime": 44, "focus": 57, "screen": 207, "evenings": 2.5, "steps": 6900, "hrv": 54},
}
SPREAD = {"sleep_score": 2.5, "bedtime": 6, "focus": 8, "screen": 20, "evenings": 1.0, "steps": 900, "hrv": 0.035}

GROUPS: List[Dict[str, Any]] = [
    {"id": "team", "name": "DH2465 team", "about": "The whole project group, on sleep.",
     "members": [ME, "Nima Tehranchi", "Knut Ovesjö", "Marcus Pramborg", "Gustaf Salenius", "Hugo Ankarcrona"],
     "metrics": ["sleep_improved", "sleep_score", "bedtime"],
     "goal": {"metric": "sleep_score", "label": "Average sleep score of 80 together", "target": 80, "combine": "mean"}},
    {"id": "focus", "name": "Focus crew", "about": "Less phone, more deep work.",
     "members": [ME, "Nima Tehranchi", "Marcus Pramborg", "Knut Ovesjö"],
     "metrics": ["focus", "screen", "evenings"],
     "goal": {"metric": "evenings", "label": "12 phone-free evenings between us", "target": 12, "combine": "sum"}},
    {"id": "padel", "name": "Padel league", "about": "Moving, and recovering from it.",
     "members": [ME, "Gustaf Salenius", "Hugo Ankarcrona", "Knut Ovesjö"],
     "metrics": ["steps", "recovery", "sleep_improved"],
     "goal": {"metric": "steps", "label": "250 000 steps together", "target": 250000, "combine": "sum_week"}},
]

CHALLENGES: List[Dict[str, Any]] = [
    {"id": "phone-down", "title": "Phone down by 22:00", "text": "Under 15 minutes on the phone after 22:00, 5 of 7 nights.",
     "target": 5, "joined": [ME, "Nima Tehranchi", "Marcus Pramborg", "Hugo Ankarcrona"]},
    {"id": "two-hours", "title": "Two phone-free hours", "text": "A two-hour stretch without picking up the phone, 5 of 7 days.",
     "target": 5, "joined": ["Marcus Pramborg", "Knut Ovesjö"]},
    {"id": "lights-out", "title": "Lights out by 23:30", "text": "Asleep before 23:30 on 5 of 7 nights.",
     "target": 5, "joined": ["Gustaf Salenius", "Nima Tehranchi", "Knut Ovesjö"]},
]


def _friend_week(name: str, week: date) -> Dict[str, float]:
    """A friend's values for the week starting ``week``: their usual plus this week's variation (fixed per week)."""
    base, rng = FRIENDS[name], random.Random("%s-%s" % (name, week.isoformat()))
    v = {k: base[k] + rng.gauss(0, SPREAD[k]) for k in ("sleep_score", "bedtime", "focus", "screen", "steps")}
    v["evenings"] = min(7.0, max(0.0, round(base["evenings"] + rng.gauss(0, SPREAD["evenings"]))))
    v["sleep_improved"] = v["sleep_score"] - base["sleep_score"]
    v["recovery"] = 100.0 * rng.gauss(0, SPREAD["hrv"])
    v["bedtime"] = max(8.0, v["bedtime"])
    return {k: round(x, 1) for k, x in v.items()}


def _friend_usual(name: str) -> Dict[str, Optional[float]]:
    base = FRIENDS[name]
    return {k: (None if METRICS[k].get("relative") else float(base[k])) for k in METRICS}


def _friend_challenge(name: str, cid: str, week: date) -> int:
    rng = random.Random("%s-%s-%s" % (name, cid, week.isoformat()))
    return rng.choice([3, 4, 4, 5, 5, 6, 7])


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def _days(start: date, n: int) -> List[date]:
    return [start + timedelta(days=k) for k in range(n)]


def build(ds: Dataset, today: date) -> Dict[str, Any]:
    week = current_periods(today)["weekly"]
    weeks = [week - timedelta(days=7 * k) for k in range(SEASON_WEEKS - 1, -1, -1)]   # oldest first
    usual_days = _days(weeks[0] - timedelta(days=USUAL_DAYS), USUAL_DAYS)

    def mine(days: List[date]) -> Dict[str, Optional[float]]:
        return {k: m["get"](ds, days, usual_days) for k, m in METRICS.items()}
    values: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {ME: {w.isoformat(): mine(_days(w, 7)) for w in weeks}}
    values[ME]["season"] = mine(_days(weeks[0], 7 * SEASON_WEEKS))
    usual = {ME: {k: (None if m.get("relative") else m["get"](ds, usual_days, usual_days)) for k, m in METRICS.items()}}
    for name in FRIENDS:
        per_week = {w.isoformat(): _friend_week(name, w) for w in weeks}
        values[name] = dict(per_week, season={k: round(statistics.fmean(v[k] for v in per_week.values()), 1)
                                              for k in METRICS})
        usual[name] = _friend_usual(name)

    def ranked(members: List[str], metric: str, key: str) -> List[Dict[str, Any]]:
        rows = [{"name": n, "value": values[n][key].get(metric), "usual": usual[n].get(metric)} for n in members]
        rows = [r for r in rows if r["value"] is not None]
        rows.sort(key=lambda r: r["value"], reverse=METRICS[metric]["better"] == "up")
        for i, r in enumerate(rows):
            r["rank"] = i + 1
        return rows

    groups = []
    for g in GROUPS:
        boards = {key: [{"metric": m, "rows": ranked(g["members"], m, key)} for m in g["metrics"]]
                  for key in [w.isoformat() for w in weeks] + ["season"]}
        points = {n: 0 for n in g["members"]}
        for w in weeks:                                           # season standings: points from each weekly board
            for board in boards[w.isoformat()]:
                for r in board["rows"][:len(POINTS)]:
                    points[r["name"]] += POINTS[r["rank"] - 1]
        goal = g["goal"]
        this = [values[n][week.isoformat()].get(goal["metric"]) for n in g["members"]]
        this = [v for v in this if v is not None]
        progress = (statistics.fmean(this) if goal["combine"] == "mean" else
                    sum(v * 7 for v in this) if goal["combine"] == "sum_week" else sum(this))
        groups.append(dict({k: g[k] for k in ("id", "name", "about", "members", "metrics")},
                           week=boards[week.isoformat()], season=boards["season"],
                           standings=sorted(({"name": n, "points": p} for n, p in points.items()), key=lambda r: -r["points"]),
                           goal=dict(goal, progress=round(progress, 1))))

    week_days = _days(week, 7)
    mine_challenge = {
        "phone-down": sum(1 for d in week_days if (ds.metric_on(d, "screen.late_minutes") or 99) < QUIET_EVENING_MIN),
        "two-hours": sum(1 for d in week_days if (_longest_phone_free(ds, d) or 0) >= 120),
        "lights-out": sum(1 for d in week_days if (bl.night_metric(ds.night(d), "onset_min") or 9e9) < 23.5 * 60),
    }
    challenges = []
    for c in CHALLENGES:
        progress = [{"name": n, "days": mine_challenge[c["id"]] if n == ME else _friend_challenge(n, c["id"], week)}
                    for n in c["joined"]]
        challenges.append(dict(c, joined=ME in c["joined"], people=len(c["joined"]),
                               progress=sorted(progress, key=lambda r: -r["days"])))
    return {"me": ME, "week": {"start": week, "end": week + timedelta(days=6)}, "weeks": weeks,
            "season": {"start": weeks[0], "end": week + timedelta(days=6)},
            "metrics": {k: {f: m[f] for f in ("label", "unit", "better")} for k, m in METRICS.items()},
            "groups": groups, "challenges": challenges}


@router.get("/api/social")
def get_social(p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        payload = build(e.ds, e.ds.today)
    return JSONResponse(to_jsonable(payload), headers={"Cache-Control": "no-store"})
