"""Apple data (tools/apple-data): POST /api/apple/derive, the Apple counterpart of POST /api/sync's step 4.

The Apple importer runs on a Mac and only appends raw ``source_records`` (through the apple-import Edge Function).
Afterwards it calls this endpoint, which reads those raw rows back and adds missing rows to the derived tables:

    1. check profiles.consented_at (403 until the user has agreed)
    2. read the user's raw apple_health / apple_screen_time records for the nights and days asked for
    3. recompute sleep_nights (with HRV, resting HR, breathing rate, SpO2, wrist temperature), heart_rate_days,
       daily_activity (steps, hourly steps, exercise minutes, workouts) and daily_metrics (screen.* and the Apple-only
       health.* values: active energy, exercise, stand hours, VO2 max, walking HR, daytime HRV, mindful minutes)
    4. upsert a provider_connection per Apple source, its connection_streams and last_synced_at

Body (all optional): {"since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "timeZone": "Europe/Stockholm"}; the nights and
days ``since``..``until`` inclusive are recomputed, by default the last 70 days (what the engine looks at).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from ..connectors import apple_derive as ad
from ..connectors import device_sync as ds
from ..connectors.real_data import DAYS
from ..timeutil import parse_date
from .auth import Principal, current_principal
from .phone_sync import BATCH, _connection, _db, _earlier_bedtimes, _require_consent, _upsert

log = logging.getLogger("stressless.server.apple_sync")
router = APIRouter()

PAGE = 1000
MAX_SPAN_DAYS = 400
RAW_COLUMNS = "data_type,data_origin,start_at,end_at,start_offset_min,value,unit"
EXPORT_ID = "apple-export"
# (source, data_type of connection_streams, raw data_types it is read from)
STREAMS = [(ad.HEALTH, "sleep_session", ("ah_sleep_analysis",)),
           (ad.HEALTH, "heart_rate", ("heart_rate", "ah_heart_rate")),
           (ad.HEALTH, "steps", ("steps", "ah_step_count")),
           (ad.HEALTH, ad.ACTIVITY_SUMMARY_DATA_TYPE, (ad.ACTIVITY_SUMMARY_DATA_TYPE,)),
           (ad.SCREEN, "app_usage", (ad.SCREEN_DATA_TYPE,))]
LABELS = {ad.HEALTH: "Apple Health export", ad.SCREEN: "Mac Screen Time"}


def _all(table: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
    """Every matching row, a page at a time (PostgREST caps a response at its max-rows)."""
    out: List[Dict[str, Any]] = []
    while True:
        page = _db("GET", table, params=dict(params, limit=str(PAGE), offset=str(len(out)))) or []
        out += page
        if not page:
            return out


def _raw(user_id: str, source: str, types: tuple, lo: datetime, hi: datetime, select: str) -> List[Dict[str, Any]]:
    return _all("source_records", {"user_id": "eq." + user_id, "source": "eq." + source,
                                   "data_type": "in.(%s)" % ",".join(types), "select": select, "order": "start_at.asc,id.asc",
                                   "and": "(start_at.gte.%s,start_at.lt.%s)" % (ds.iso(lo), ds.iso(hi))})


def _insert_missing(table: str, rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    """Let the existing unique key protect summaries, even during a concurrent sync."""
    inserted = []
    for i in range(0, len(rows), BATCH):
        inserted += _db("POST", table, params={"on_conflict": "user_id," + key, "select": "source," + key},
                        json=rows[i:i + BATCH], prefer="resolution=ignore-duplicates,return=representation")
    return inserted


def _edge(user_id: str, source: str, types: tuple, column: str, desc: bool) -> Optional[str]:
    rows = _db("GET", "source_records", params={"user_id": "eq." + user_id, "source": "eq." + source,
                                                "data_type": "in.(%s)" % ",".join(types), "select": column,
                                                "order": column + (".desc.nullslast" if desc else ".asc"), "limit": "1"}) or []
    return rows[0].get(column) if rows else None


def _range(body: Dict[str, Any]) -> tuple:
    today = datetime.now(timezone.utc).date()
    try:
        last = parse_date(str(body["until"])) if body.get("until") else today
        first = parse_date(str(body["since"])) if body.get("since") else last - timedelta(days=DAYS)
    except ValueError:
        raise ValueError("since/until must be dates (YYYY-MM-DD)")
    if first > last:
        raise ValueError("since must not be after until")
    if (last - first).days > MAX_SPAN_DAYS:
        raise ValueError("at most %d days per request" % MAX_SPAN_DAYS)
    return first, last


@router.post("/api/apple/derive")
def post_apple_derive(body: Optional[Dict[str, Any]] = Body(None), p: Principal = Depends(current_principal)):
    body = body or {}
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    first, last = _range(body)
    _require_consent(p.user_id)
    uid = {"user_id": p.user_id}
    now = ds.iso(datetime.now(timezone.utc))

    # A night starts the evening of its date and ends the next morning; a day's offset is at most 14 h from UTC.
    lo = datetime.combine(first - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    hi = datetime.combine(last + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)
    rows = _raw(p.user_id, ad.HEALTH, ad.HEALTH_DATA_TYPES, lo, hi,
                RAW_COLUMNS + ",kind:payload->>apple_type,stage:payload->attributes->>value")
    for kind, data_type in ((ad.WORKOUT, ad.WORKOUT_DATA_TYPE), (ad.ACTIVITY_SUMMARY, ad.ACTIVITY_SUMMARY_DATA_TYPE)):
        rows.extend(dict(r, kind=kind) for r in _raw(p.user_id, ad.HEALTH, (data_type,), lo, hi, RAW_COLUMNS + ",payload"))
    screen = _raw(p.user_id, ad.SCREEN, (ad.SCREEN_DATA_TYPE,), lo, hi, RAW_COLUMNS)
    raw = ad.parse(rows)

    sessions = ad.sleep_sessions(raw.get(ad.SLEEP, []))
    nights = ad.sleep_night_rows(raw, _earlier_bedtimes(p.user_id, {"sleep": sessions}), first, last)
    hr_days = ad.heart_rate_day_rows(raw, first, last)
    activity = ad.activity_rows(raw, first, last)
    metrics = ad.screen_metric_rows(screen, first, last) + ad.health_metric_rows(raw, first, last)
    nights = _insert_missing("sleep_nights", [dict(r, computed_at=now, **uid) for r in nights], "night_date")
    hr_days = _insert_missing("heart_rate_days", [dict(r, computed_at=now, **uid) for r in hr_days], "day")
    activity = _insert_missing("daily_activity", [dict(r, computed_at=now, **uid) for r in activity], "day")
    metrics = _insert_missing("daily_metrics", [dict(r, computed_at=now, **uid) for r in metrics], "day,metric_key")

    # Sync bookkeeping, so the app lists the Apple sources with how far their data goes.
    device = {"install_id": EXPORT_ID, "platform": "ios", "time_zone": body.get("timeZone")}
    conns: Dict[str, str] = {}
    streams = []
    for source, data_type, types in STREAMS:
        until = _edge(p.user_id, source, types, "start_at", True)
        if until is None:
            continue
        if source not in conns:
            conns[source] = _connection(p.user_id, source, dict(device, label=LABELS[source]), now)
        end = _edge(p.user_id, source, types, "end_at", True)
        streams.append({"connection_id": conns[source], "data_type": data_type, "permitted": True,
                        "data_from": _edge(p.user_id, source, types, "start_at", False),
                        "data_until": max(until, end or until), "last_synced_at": now, "updated_at": now, **uid})
    _upsert("connection_streams", streams, "connection_id,data_type")
    for cid in conns.values():
        _db("PATCH", "provider_connections", params={"id": "eq." + cid, "user_id": "eq." + p.user_id}, json={"last_synced_at": now})

    log.info("apple derive for %s %s..%s: %d raw, %d nights, %d hr days, %d activity days, %d metric rows",
             p.user_id, first, last, len(rows) + len(screen), len(nights), len(hr_days), len(activity), len(metrics))
    return JSONResponse({"ok": True, "since": first.isoformat(), "until": last.isoformat(),
                         "read": {"health_records": len(rows), "screen_records": len(screen)},
                         "stored": {"nights": len(nights), "heart_rate_days": len(hr_days), "activity_days": len(activity),
                                    "screen_days": len({m["day"] for m in metrics if m["source"] == ad.SCREEN}),
                                    "health_metric_rows": sum(1 for m in metrics if m["source"] == ad.HEALTH)}},
                         headers={"Cache-Control": "no-store"})
