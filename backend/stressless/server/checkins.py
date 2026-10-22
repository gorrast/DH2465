"""Manual check-ins: cups of coffee and units of alcohol per day (migration 20261022000000_checkins.sql).

    GET  /api/checkins          the last DAYS days: {"today", "days": [{"day", "coffee_cups", "alcohol_units"}]}
    POST /api/checkins/{day}    {"coffee_cups": 2, "alcohol_units": 0}; a field set to null clears it, a missing
                                field is left as it is

Values live in daily_metrics (source 'manual'), which signed-in users can only read, so this writes with the
service-role key and scopes every query to the caller, like server/phone_sync.py. "day" is the local date the
coffee or drinks were had; the engine reads it as the evening before night "day".
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from ..connectors.real_data import valid_tz
from ..timeutil import parse_date, today_local
from . import session
from .auth import Principal, current_principal
from .phone_sync import _db, _require_consent, _upsert

router = APIRouter()

SOURCE = "manual"
DAYS = 14                                      # how far back a check-in can be added or changed
# body field -> (metric key, largest accepted value)
FIELDS = {"coffee_cups": ("intake.coffee_cups", 20), "alcohol_units": ("intake.alcohol_units", 30)}
KEYS = {key: name for name, (key, _) in FIELDS.items()}


def _today(p: Principal) -> date:
    return session.anchor_override() or today_local(valid_tz(p.store.time_zone()))


def _read(user_id: str, lo: date, hi: date) -> Dict[str, Dict[str, Any]]:
    rows = _db("GET", "daily_metrics", params={
        "user_id": "eq." + user_id, "source": "eq." + SOURCE, "metric_key": "in.(%s)" % ",".join(KEYS),
        "select": "day,metric_key,value", "and": "(day.gte.%s,day.lt.%s)" % (lo.isoformat(), (hi + timedelta(days=1)).isoformat())}) or []
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out.setdefault(r["day"], {})[KEYS[r["metric_key"]]] = float(r["value"])
    return out


def _payload(user_id: str, today: date) -> Dict[str, Any]:
    lo = today - timedelta(days=DAYS - 1)
    stored = _read(user_id, lo, today)
    days = []
    for k in range(DAYS):
        d = (today - timedelta(days=k)).isoformat()
        days.append(dict({name: None for name in FIELDS}, day=d, **stored.get(d, {})))
    return {"today": today.isoformat(), "days": days}


def _value(body: Dict[str, Any], name: str, top: int) -> Optional[float]:
    v = body[name]
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= top:
        raise ValueError("%s must be a number from 0 to %d" % (name, top))
    return round(float(v) * 2) / 2              # whole or half cups and units


@router.get("/api/checkins")
def get_checkins(p: Principal = Depends(current_principal)):
    return JSONResponse(_payload(p.user_id, _today(p)), headers={"Cache-Control": "no-store"})


@router.post("/api/checkins/{day}")
def post_checkin(day: str, body: Optional[Dict[str, Any]] = Body(None), p: Principal = Depends(current_principal)):
    try:
        d = parse_date(day)
    except (TypeError, ValueError):
        raise ValueError("Bad date %r (expected YYYY-MM-DD)" % day)
    today = _today(p)
    if not today - timedelta(days=DAYS - 1) <= d <= today:
        raise ValueError("Check-ins can only be added for the last %d days" % DAYS)
    body = body or {}
    given = {name: _value(body, name, top) for name, (_, top) in FIELDS.items() if name in body}
    if not given:
        raise ValueError("Send coffee_cups and/or alcohol_units")
    _require_consent(p.user_id)

    now = datetime.now(timezone.utc).isoformat()
    rows = [{"user_id": p.user_id, "day": d.isoformat(), "metric_key": FIELDS[name][0], "value": v, "source": SOURCE,
             "computed_at": now} for name, v in given.items() if v is not None]
    _upsert("daily_metrics", rows, "user_id,day,metric_key")
    cleared = [FIELDS[name][0] for name, v in given.items() if v is None]
    if cleared:
        _db("DELETE", "daily_metrics", params={"user_id": "eq." + p.user_id, "day": "eq." + d.isoformat(),
                                                "source": "eq." + SOURCE, "metric_key": "in.(%s)" % ",".join(cleared)})
    session.forget(p.user_id)                  # the next report should see it, not a cached engine
    return JSONResponse(dict(_payload(p.user_id, today), ok=True), headers={"Cache-Control": "no-store"})
