"""Google Calendar connection: the OAuth round trip, sync and disconnect (ported from the google-calendar Edge Function).

    POST /api/calendar/google/authorize   -> {authorizationUrl}; the browser goes there
    GET  /api/calendar/google/callback    <- Google sends the browser back here with ?code&state
    GET  /api/calendar/google             -> {connections: [...]}
    POST /api/calendar/google/sync        -> {imported}
    POST /api/calendar/google/disconnect  -> {disconnected}

The connection tables are not writable by signed-in users, so this module talks to Supabase with the service-role key
and scopes every query to the caller's user id itself. The Google refresh token is stored AES-GCM encrypted with a key
only this server has (same format as the Edge Function, so its connections keep working).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..connectors import google_calendar as google
from ..engine.pipeline import EngineError
from ..store import SupabaseError
from .auth import Principal, current_principal, supabase_url

log = logging.getLogger("stressless.server.calendar")
router = APIRouter(prefix="/api/calendar/google")

CALLBACK_PATH = "/api/calendar/google/callback"
STATE_COOKIE = "sl_gcal_state"
STATE_TTL = timedelta(minutes=15)
BATCH = 500
PAGE = 1000
_client: Optional[httpx.Client] = None


class NotConfigured(EngineError):
    status = 503


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=20.0)
    return _client


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise NotConfigured("Google Calendar is not configured on this server: %s is not set" % name)
    return value


def _app_url() -> str:
    return _env("APP_URL").rstrip("/")


def _redirect_uri() -> str:
    return _app_url() + CALLBACK_PATH


def _json(payload: Any) -> JSONResponse:
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ crypto --
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _aes() -> AESGCM:
    try:
        encoded_key = _env("GOOGLE_TOKEN_ENCRYPTION_KEY")
        key = base64.b64decode(encoded_key + "=" * (-len(encoded_key) % 4), validate=True)
    except ValueError:
        key = b""
    if len(key) != 32:
        raise NotConfigured("GOOGLE_TOKEN_ENCRYPTION_KEY must be 32 bytes, base64-encoded")
    return AESGCM(key)


def encrypt(secret: str) -> str:
    iv = os.urandom(12)
    return _b64url(iv + _aes().encrypt(iv, secret.encode(), None))


def decrypt(value: str) -> str:
    data = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    try:
        return _aes().decrypt(data[:12], data[12:], None).decode()
    except InvalidTag:
        raise google.ReconnectNeeded("The stored calendar credential can no longer be read; reconnect your calendar")


def state_hash(state: str) -> str:
    return _b64url(hashlib.sha256(state.encode()).digest())


# ---------------------------------------------------------------- storage --
def _db(method: str, table: str, *, params: Optional[Dict[str, str]] = None, json: Any = None, prefer: Optional[str] = None) -> Any:
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
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


def _mine(user_id: str, **filters: str) -> Dict[str, str]:
    return dict({"user_id": "eq." + user_id, "provider": "eq." + google.PROVIDER}, **filters)


def _connected(user_id: str) -> Optional[Dict[str, Any]]:
    rows = _db("GET", "provider_connections", params=_mine(
        user_id, status="eq.connected", select="id,status,connected_at,last_synced_at,provider_account_id",
        order="connected_at.desc", limit="1"))
    return rows[0] if rows else None


def _refresh_token(connection_id: str) -> Optional[str]:
    rows = _db("GET", "provider_connection_credentials", params={
        "provider_connection_id": "eq." + connection_id, "select": "refresh_token_ciphertext"})
    return rows[0]["refresh_token_ciphertext"] if rows else None


def _forget(user_id: str, **filters: str) -> None:
    """Revoke and delete the user's Google connections matching ``filters`` (their credentials go with them)."""
    for row in _db("GET", "provider_connections", params=_mine(user_id, select="id", **filters)) or []:
        ciphertext = _refresh_token(row["id"])
        if ciphertext:
            try:
                google.revoke(_http(), decrypt(ciphertext))
            except EngineError as exc:
                log.warning("could not revoke Google token: %s", exc)
    _db("DELETE", "provider_connections", params=_mine(user_id, **filters))


# ------------------------------------------------------------------ routes --
@router.get("")
def get_status(p: Principal = Depends(current_principal)):
    c = _connected(p.user_id)
    return _json({"connections": [dict(c, email=c.get("provider_account_id"))] if c else []})


@router.get("/events")
def get_events(p: Principal = Depends(current_principal)):
    """Return all columns for every calendar event owned by the signed-in user."""
    rows: List[Dict[str, Any]] = []
    while True:
        page = _db("GET", "calendar_events", params={
            "user_id": "eq." + p.user_id,
            "select": "*",
            "order": "starts_at.asc,id.asc",
            "limit": str(PAGE),
            "offset": str(len(rows)),
        }) or []
        rows.extend(page)
        if len(page) < PAGE:
            return _json({"events": rows})


@router.post("/authorize")
def post_authorize(p: Principal = Depends(current_principal)):
    client_id, redirect_uri = _env("GOOGLE_CLIENT_ID"), _redirect_uri()
    _aes()  # fail now rather than after the user has been to Google and back
    _db("DELETE", "provider_connections", params=_mine(p.user_id, status="in.(pending,error)"))
    state = secrets.token_urlsafe(32)
    row = _db("POST", "provider_connections", prefer="return=representation",
              json={"user_id": p.user_id, "provider": google.PROVIDER, "status": "pending", "scopes": [google.SCOPE]})[0]
    _db("POST", "provider_connection_credentials", json={
        "provider_connection_id": row["id"], "oauth_state_hash": state_hash(state), "oauth_state_created_at": google.iso(datetime.now(timezone.utc))})
    response = _json({"authorizationUrl": google.authorization_url(client_id, redirect_uri, state)})
    # The same browser has to come back with this cookie, so a consent link cannot be handed to someone else.
    response.set_cookie(STATE_COOKIE, state, max_age=int(STATE_TTL.total_seconds()), path=CALLBACK_PATH, httponly=True,
                        samesite="lax", secure=redirect_uri.startswith("https://"))
    return response


def _back(outcome: str) -> RedirectResponse:
    response = RedirectResponse(_app_url() + "/calendar?" + outcome, status_code=302)
    response.delete_cookie(STATE_COOKIE, path=CALLBACK_PATH)
    return response


@router.get("/callback")
def get_callback(request: Request):
    """Google's redirect: a plain browser navigation, so the user is identified by the state, not a bearer token."""
    q = request.query_params
    state, cookie = q.get("state") or "", request.cookies.get(STATE_COOKIE) or ""
    if not state or not hmac.compare_digest(state, cookie):
        return _back("error=google")
    rows = _db("GET", "provider_connection_credentials", params={
        "oauth_state_hash": "eq." + state_hash(state), "select": "provider_connection_id,oauth_state_created_at"})
    if not rows:
        return _back("error=google")
    connection_id = rows[0]["provider_connection_id"]
    pending = {"id": "eq." + connection_id, "status": "eq.pending"}
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(rows[0]["oauth_state_created_at"])
        found = _db("GET", "provider_connections", params=dict(pending, select="user_id"))
        if not found or not q.get("code") or q.get("error") or not timedelta(0) <= age <= STATE_TTL:
            raise EngineError("consent was declined or the request expired")
        user_id = found[0]["user_id"]
        tokens = google.exchange_code(_http(), _env("GOOGLE_CLIENT_ID"), _env("GOOGLE_CLIENT_SECRET"), _redirect_uri(), q["code"])
        email = google.account_email(_http(), tokens["access_token"])
        _forget(user_id, id="neq." + connection_id)  # one Google connection per user: the new one replaces the old
        now = google.iso(datetime.now(timezone.utc))
        _db("PATCH", "provider_connection_credentials", params={"provider_connection_id": "eq." + connection_id}, json={
            "oauth_state_hash": None, "oauth_state_created_at": None, "refresh_token_ciphertext": encrypt(tokens["refresh_token"]), "updated_at": now})
        _db("PATCH", "provider_connections", params=pending, json={"status": "connected", "connected_at": now, "provider_account_id": email})
    except (EngineError, SupabaseError) as exc:
        log.warning("Google Calendar connection failed: %s", exc)
        _db("DELETE", "provider_connections", params=pending)
        return _back("error=google")
    return _back("sync=google")


def _existing_events(user_id: str, time_min: datetime, time_max: datetime) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    while True:
        page = _db("GET", "calendar_events", params=_mine(
            user_id, select="id,provider_event_id", order="id", limit=str(PAGE), offset=str(len(rows)),
            **{"and": "(starts_at.gte.%s,starts_at.lt.%s)" % (google.iso(time_min), google.iso(time_max))})) or []
        rows += page
        if len(page) < PAGE:
            return rows


@router.post("/sync")
def post_sync(p: Principal = Depends(current_principal)):
    connection = _connected(p.user_id)
    if not connection:
        raise EngineError("Connect a Google Calendar first")
    one = {"id": "eq." + connection["id"]}
    try:
        ciphertext = _refresh_token(connection["id"])
        if not ciphertext:
            raise google.ReconnectNeeded("Calendar credential is missing; reconnect your calendar")
        access_token = google.refresh_access_token(_http(), _env("GOOGLE_CLIENT_ID"), _env("GOOGLE_CLIENT_SECRET"), decrypt(ciphertext))
        time_min, time_max = google.sync_window()
        rows = google.event_rows(_http(), access_token, p.user_id, time_min, time_max)
    except google.ReconnectNeeded:
        _db("PATCH", "provider_connections", params=one, json={"status": "error"})
        raise
    # Write first, then remove what Google no longer has: a failure part-way never leaves the user with fewer events,
    # and rows that still exist keep their id (event_analytics hangs off it). History before the window is kept.
    for i in range(0, len(rows), BATCH):
        _db("POST", "calendar_events", params={"on_conflict": "user_id,provider,provider_event_id"}, json=rows[i:i + BATCH],
            prefer="resolution=merge-duplicates,return=minimal")
    keep = {r["provider_event_id"] for r in rows}
    stale = [r["id"] for r in _existing_events(p.user_id, time_min, time_max) if r["provider_event_id"] not in keep]
    for i in range(0, len(stale), 100):
        _db("DELETE", "calendar_events", params=_mine(p.user_id, id="in.(%s)" % ",".join(stale[i:i + 100])))
    update: Dict[str, Any] = {"last_synced_at": google.iso(datetime.now(timezone.utc))}
    if not connection.get("provider_account_id"):
        update["provider_account_id"] = google.account_email(_http(), access_token)
    _db("PATCH", "provider_connections", params=one, json=update)
    return _json({"imported": len(rows)})


@router.post("/disconnect")
def post_disconnect(p: Principal = Depends(current_principal)):
    """Revoke the authorization at Google and delete the connection together with every event imported through it."""
    _forget(p.user_id)
    _db("DELETE", "calendar_events", params=_mine(p.user_id))
    return _json({"disconnected": True})
