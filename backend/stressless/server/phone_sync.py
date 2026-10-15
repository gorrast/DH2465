"""Phone upload (correlate-app): POST /api/sync, the ingest flow of docs/SCHEMA.md.

    1. check profiles.consented_at (403 until the user has agreed)
    2. upsert the install's provider_connections (one per source: health_connect, screen_time)
    3. upsert the raw source_records, deduplicated on (user, source, source_record_id)
    4. recompute sleep_nights, daily_activity and daily_metrics for the nights and days in the upload
    5. upsert connection_streams (permitted, data_from, data_until, last_synced_at) and the connections' last_synced_at

Signed-in users can only read these tables, so this module writes with the service-role key and scopes every query to
the caller's user id itself, like server/calendar.py.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from ..connectors import device_sync as ds
from ..engine.pipeline import EngineError
from ..store import SupabaseError
from .auth import Principal, current_principal, supabase_url

log = logging.getLogger("stressless.server.phone_sync")
router = APIRouter()

BATCH = 500
_client: Optional[httpx.Client] = None


class NotConfigured(EngineError):
    status = 503


class ConsentRequired(EngineError):
    status = 403


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=20.0)
    return _client


def _db(method: str, table: str, *, params: Optional[Dict[str, str]] = None, json: Any = None, prefer: Optional[str] = None) -> Any:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise NotConfigured("Phone sync is not configured on this server: SUPABASE_SERVICE_ROLE_KEY is not set")
    headers = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_"):  # legacy service_role JWT; the newer sb_secret_ keys go in apikey only
        headers["Authorization"] = "Bearer " + key
    if prefer:
        headers["Prefer"] = prefer
    try:
        r = _http().request(method, supabase_url() + "/rest/v1/" + table, params=params, json=json, headers=headers)
    except httpx.HTTPError as exc:
        raise SupabaseError("Supabase unreachable: %s" % exc) from exc
    if r.status_code >= 400:
        raise SupabaseError("Supabase %s %s -> %d %s" % (method, table, r.status_code, r.text[:300]))
    return r.json() if r.content else None


def _upsert(table: str, rows: List[Dict[str, Any]], on_conflict: str) -> None:
    for i in range(0, len(rows), BATCH):
        _db("POST", table, params={"on_conflict": on_conflict}, json=rows[i:i + BATCH], prefer="resolution=merge-duplicates,return=minimal")


def _require_consent(user_id: str) -> None:
    rows = _db("GET", "profiles", params={"user_id": "eq." + user_id, "select": "consented_at"}) or []
    if not rows or not rows[0].get("consented_at"):
        raise ConsentRequired("consent_required: agree to storing your health and screen-time data before syncing")


def _zone(name: Optional[str]) -> Optional[str]:
    try:
        return name if name and ZoneInfo(name) else None
    except (ValueError, KeyError, OSError):
        return None


def _connection(user_id: str, source: str, device: Dict[str, Any], now: str) -> str:
    """The install's connection for one source (created on its first sync); returns its id."""
    row = {"user_id": user_id, "provider": source, "provider_account_id": device["install_id"], "status": "connected",
           "platform": device["platform"], "device_label": device["label"], "time_zone": _zone(device["time_zone"]), "last_error": None}
    out = _db("POST", "provider_connections", params={"on_conflict": "user_id,provider,provider_account_id"}, json=row,
              prefer="resolution=merge-duplicates,return=representation")
    conn = out[0]
    if not conn.get("connected_at"):
        _db("PATCH", "provider_connections", params={"id": "eq." + conn["id"], "user_id": "eq." + user_id}, json={"connected_at": now})
    return conn["id"]


def _earlier_bedtimes(user_id: str, batch: Dict[str, Any]) -> List[float]:
    """Bedtimes of the stored nights in the two weeks before the upload's first night, for the consistency score."""
    if not batch["sleep"]:
        return []
    first: date = min(ds.night_of(s["start"], s["offset"])[0] for s in batch["sleep"])
    rows = _db("GET", "sleep_nights", params={
        "user_id": "eq." + user_id, "select": "night_date,in_bed_at,utc_offset_min", "order": "night_date.asc",
        "and": "(night_date.gte.%s,night_date.lt.%s)" % ((first - timedelta(days=14)).isoformat(), first.isoformat())}) or []
    return [ds.bedtime_min(r["in_bed_at"], r["utc_offset_min"]) for r in rows if r.get("in_bed_at")]


@router.post("/api/sync")
def post_sync(body: Optional[Dict[str, Any]] = Body(None), p: Principal = Depends(current_principal)):
    batch = ds.parse(body)
    _require_consent(p.user_id)
    now = ds.iso(datetime.now(timezone.utc))
    uid = {"user_id": p.user_id}

    streams = ds.streams(batch)
    conns = {source: _connection(p.user_id, source, batch["device"], now) for source in sorted({s for s, _ in streams})}

    records = [dict(r, connection_id=conns[r["source"]], **uid) for r in ds.source_records(batch)]
    _upsert("source_records", records, "user_id,source,source_record_id")

    nights = ds.sleep_night_rows(batch, _earlier_bedtimes(p.user_id, batch))
    metrics = ds.metric_rows(batch)
    _upsert("sleep_nights", [dict(r, computed_at=now, **uid) for r in nights], "user_id,night_date")
    _upsert("daily_activity", [dict(r, computed_at=now, **uid) for r in ds.activity_rows(batch)], "user_id,day")
    _upsert("daily_metrics", [dict(r, computed_at=now, **uid) for r in metrics], "user_id,day,metric_key")

    _upsert("connection_streams", [dict(s, connection_id=conns[source], data_type=data_type, last_synced_at=now, updated_at=now, **uid)
                                   for (source, data_type), s in sorted(streams.items())], "connection_id,data_type")
    for cid in conns.values():
        _db("PATCH", "provider_connections", params={"id": "eq." + cid, "user_id": "eq." + p.user_id}, json={"last_synced_at": now})
    log.info("phone sync for %s: %d records, %d nights, %d metric rows", p.user_id, len(records), len(nights), len(metrics))
    return JSONResponse(dict(ds.summary(batch, nights, metrics, len(records)), ok=True), headers={"Cache-Control": "no-store"})
