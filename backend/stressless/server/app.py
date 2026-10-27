"""FastAPI app: the JSON API (SPEC §8.2). Same routes and payloads as the original localhost server, per signed-in user.

Run locally with ``uvicorn api.index:app --port 8000``; on Vercel ``api/index.py`` serves it under /api.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Body, Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..engine.pipeline import EngineError
from ..engine.reasoning import reasoning_mode
from ..models import to_jsonable
from ..connectors.media import parse_media, parse_spotify_file, parse_steam_file
from ..connectors.steam import SteamSyncError, fetch_steam_library, steam_sync_status
from ..connectors.lastfm import LastfmError, fetch_lastfm, lastfm_status, lastfm_artwork
from ..connectors.media_artwork import artwork_status, netflix_artwork_batch
from ..engine.media_insights import analyze_media
from ..sim.personas import PERSONA_ORDER, PERSONAS
from ..store import SupabaseError
from ..timeutil import parse_date
from . import calendar, checkins, phone_sync, session, reports
from .auth import Principal, current_principal

log = logging.getLogger("stressless.server")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="StressLess API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.include_router(calendar.router)
app.include_router(phone_sync.router)
app.include_router(checkins.router)
app.include_router(reports.router)
JSON_TYPE = "application/json; charset=utf-8"
MAX_MEDIA_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_MEDIA_UPLOAD_FILES = 20

# The phone app (correlate-app) runs in an Android WebView on https://localhost and calls the API cross-origin with a
# bearer token, so no cookies: credentials stay off. Add more with STRESSLESS_CORS_ORIGINS.
CORS_ORIGINS = ["https://localhost", "http://localhost"] + [
    o.strip() for o in os.environ.get("STRESSLESS_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])


# ------------------------------------------------------------------ helpers --
def J(payload: Any, status: int = 200) -> Response:
    body = json.dumps(to_jsonable(payload), ensure_ascii=False, allow_nan=False)
    return Response(content=body, status_code=status, media_type=JSON_TYPE, headers={"Cache-Control": "no-store"})


def _error(status: int, message: str) -> Response:
    return J({"error": message}, status)


def _int_or_none(v: Optional[str]) -> Optional[int]:
    if v is None or v == "" or v == "null":
        return None
    return int(v)


def _date(s: str) -> date:
    try:
        return parse_date(s)
    except ValueError:
        raise EngineError("Bad date %r (expected YYYY-MM-DD)" % s)


def meta_payload(engine) -> Dict[str, Any]:
    ds = engine.ds
    personas = [{"key": k, "name": PERSONAS[k].name, "tagline": PERSONAS[k].tagline, "ready": True} for k in PERSONA_ORDER]
    return {
        "persona": {"key": ds.persona.key, "name": ds.persona.name, "tagline": ds.persona.tagline, "description": ds.persona.description, "tz": ds.persona.tz},
        "personas": personas, "seed": ds.seed, "days": (ds.end - ds.start).days + 1, "source": ds.source,
        "start": ds.start, "end": ds.end, "today": ds.today, "anchor_mode": session.anchor_override() is not None,
        "n_nights": sum(1 for n in ds.nights if n.worn and n.score is not None), "reasoning_mode": reasoning_mode(),
        "version": __version__, "history_days_options": [7, 14, 28, None], "generated_at": ds.generated_at, "showcase": ds.showcase,
    }


# ----------------------------------------------------------------- errors --
@app.exception_handler(EngineError)
async def _engine_error(request: Request, exc: EngineError) -> Response:
    return _error(exc.status, str(exc))


@app.exception_handler(ValueError)
async def _value_error(request: Request, exc: ValueError) -> Response:
    return _error(400, str(exc))


@app.exception_handler(SupabaseError)
async def _supabase_error(request: Request, exc: SupabaseError) -> Response:
    log.error("%s", exc)
    return _error(502, "Storage error: %s" % exc)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
    return _error(400, "Bad request: %s" % "; ".join(str(e.get("msg")) for e in exc.errors()))


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 404:
        return _error(404, "no such route: %s" % request.url.path)
    return _error(exc.status_code, str(exc.detail))


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> Response:  # pragma: no cover
    log.exception("unhandled error on %s", request.url.path)
    return _error(500, "%s: %s" % (type(exc).__name__, exc))


# ----------------------------------------------------------------- routes --
@app.get("/api/health")
def get_health():
    return J({"ok": True, "python": sys.version.split()[0], "version": __version__, "reasoning_mode": reasoning_mode()})


@app.get("/api/meta")
def get_meta(p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        return J(meta_payload(e))


@app.get("/api/report/{day}.md")
def get_report_md(day: str, history_days: Optional[str] = None, p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        report = e.morning_report(_date(day), _int_or_none(history_days))
        return Response(content=e.report_markdown(report), media_type="text/markdown; charset=utf-8", headers={"Cache-Control": "no-store"})


@app.get("/api/report/{day}")
def get_report(day: str, history_days: Optional[str] = None, p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        return J(e.morning_report(_date(day), _int_or_none(history_days)))


@app.get("/api/day/{day}")
def get_day(day: str, p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        return J(e.day_bundle(_date(day)))


@app.get("/api/week")
def get_week(end: Optional[str] = None, history_days: Optional[str] = None, p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        return J(e.week(_date(end) if end else e.ds.today, _int_or_none(history_days)))


@app.get("/api/habits")
def get_habits(upto: Optional[str] = None, history_days: Optional[str] = None, p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        u = _date(upto) if upto else e.ds.today
        hd = _int_or_none(history_days)
        return J({"habits": e.habits(u, hd), "model": e.model_summary(u, hd)})


@app.get("/api/model")
def get_model(upto: Optional[str] = None, history_days: Optional[str] = None, p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        return J(e.model_summary(_date(upto) if upto else e.ds.today, _int_or_none(history_days)))


@app.get("/api/reality")
def get_reality(p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        return J(e.reality())


@app.post("/api/reality/{check_id}/answer")
def post_answer(check_id: str, body: Optional[Dict[str, Any]] = Body(None), p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        return J(e.answer(check_id, str((body or {}).get("answer", ""))))


@app.post("/api/whatif")
def post_whatif(body: Optional[Dict[str, Any]] = Body(None), p: Principal = Depends(current_principal)):
    body = body or {}
    if "date" not in body:
        raise EngineError("whatif needs a date")
    with session.engine_session(p.user_id, p.store) as e:
        return J(e.whatif(_date(str(body["date"])), body.get("mods") or []))


@app.post("/api/suggestions/{day}/{suggestion_id}/accept")
def post_accept(day: str, suggestion_id: str, p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        s, ev, ics = e.accept_suggestion(_date(day), suggestion_id)
        return J({"suggestion": s, "event": ev, "ics": ics})


@app.get("/api/suggestions/{day}/{suggestion_id}.ics")
def get_ics(day: str, suggestion_id: str, p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        ics = e.suggestion_ics(_date(day), suggestion_id)
    return Response(content=ics, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="stressless-%s.ics"' % suggestion_id, "Cache-Control": "no-store"})


@app.get("/api/validation")
def get_validation(p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        return J(e.validation())


def _media_payload(rows):
    totals = {provider: {"items": 0, "minutes": 0.0} for provider in ("spotify", "netflix", "lastfm", "youtube")}
    for row in rows:
        bucket = totals.setdefault(row["provider"], {"items": 0, "minutes": 0.0})
        bucket["items"] += 1
        bucket["minutes"] += float(row.get("minutes") or 0)
    recent = {provider: [row for row in rows if row["provider"] == provider][:50] for provider in totals}
    return {"events": rows[:100], "recent_by_provider": recent, "total": len(rows), "totals": totals}


@app.get("/api/media")
def get_media(provider: str | None = None, offset: int = 0, limit: int = 50, p: Principal = Depends(current_principal)):
    if provider not in (None, "spotify", "netflix", "lastfm", "youtube") or offset < 0 or not 1 <= limit <= 100:
        raise EngineError("Invalid media history filter or page")
    rows = p.store.media_events()
    rows.sort(key=lambda row: (row.get("occurred_at", ""), row.get("id", "")), reverse=True)
    if provider:
        filtered = [row for row in rows if row["provider"] == provider]
        return J({"events": filtered[offset:offset + limit], "total": len(filtered)})
    return J({**_media_payload(rows), "documents": p.store.media_documents()})


@app.get("/api/media/netflix/artwork")
def get_netflix_artwork_status(p: Principal = Depends(current_principal)):
    return J(artwork_status())


@app.post("/api/media/netflix/artwork")
def post_netflix_artwork(p: Principal = Depends(current_principal)):
    if not artwork_status()["configured"]:
        return _error(503, artwork_status()["message"])
    updates, error = netflix_artwork_batch(p.store.pending_netflix_artwork())
    if updates:
        p.store.update_netflix_artwork(updates)
    return J({"updates": updates, "has_more": bool(p.store.pending_netflix_artwork(1)), "error": error})


@app.get("/api/media/steam")
def get_steam_status(p: Principal = Depends(current_principal)):
    return J(steam_sync_status(p.user_id))


@app.post("/api/media/steam/sync")
def post_steam_sync(p: Principal = Depends(current_principal)):
    try:
        document = fetch_steam_library(p.user_id)
    except SteamSyncError as exc:
        return _error(exc.status, str(exc))
    # Same identity as a file import, so refreshing replaces just the Steam snapshot.
    p.store.replace_media("steam", [], [{
        "id": hashlib.sha256(b"steam-library").hexdigest()[:32],
        "filename": "Steam API", "kind": "steam_library", "payload": document,
    }])
    return get_media(p=p)


@app.get("/api/media/lastfm")
def get_lastfm_status(p: Principal = Depends(current_principal)):
    return J(lastfm_status(p.user_id))


@app.get("/api/media/lastfm/artwork")
def get_lastfm_artwork(artist: str, album: str, p: Principal = Depends(current_principal)):
    try:
        return J({"artwork_url": lastfm_artwork(p.user_id, artist, album)})
    except LastfmError as exc:
        return _error(exc.status, str(exc))


@app.post("/api/media/lastfm/sync")
def post_lastfm_sync(older: bool = False, p: Principal = Depends(current_principal)):
    previous = next((doc["payload"] for doc in p.store.media_documents() if doc.get("kind") == "lastfm_sync"), None)
    try:
        rows, state = fetch_lastfm(p.user_id, previous, older=older)
    except LastfmError as exc:
        return _error(exc.status, str(exc))
    p.store.replace_media("lastfm", rows, [{
        "id": hashlib.sha256(b"lastfm-sync").hexdigest()[:32], "filename": "Last.fm API",
        "kind": "lastfm_sync", "payload": state,
    }])
    return get_media(p=p)


@app.get("/api/media/insights")
def get_media_insights(p: Principal = Depends(current_principal)):
    # Last.fm remains display-only; unknown playback duration is not an engine input.
    rows = [row for row in p.store.media_events() if row.get("provider") != "lastfm"]
    with session.engine_session(p.user_id, p.store) as e:
        return J(analyze_media(e.ds, rows))


@app.post("/api/media/import")
async def post_media_import(provider: str, files: list[UploadFile] = File(...), p: Principal = Depends(current_principal), youtube_range: str = "90"):
    if provider == "youtube" and youtube_range not in ("30", "90", "all"):
        raise EngineError("Choose 30 days, 90 days or all history for YouTube")
    if provider not in ("spotify", "netflix", "steam", "youtube"):
        raise EngineError("unsupported media provider %r" % provider)
    if len(files) > MAX_MEDIA_UPLOAD_FILES:
        raise EngineError("Choose no more than 20 media export files at a time")
    rows = []
    documents = []
    seen = set()
    total_bytes = 0
    upload_limit = 32 * 1024 * 1024 if provider == "youtube" else MAX_MEDIA_UPLOAD_BYTES
    for upload in files:
        content = await upload.read(upload_limit - total_bytes + 1)
        total_bytes += len(content)
        if total_bytes > upload_limit:
            raise EngineError("Combined media exports must be %s MB or smaller" % (upload_limit // (1024 * 1024)))
        if provider == "spotify":
            parsed, document = parse_spotify_file(upload.filename or "spotify.json", content)
        elif provider == "steam":
            if len(files) != 1:
                raise EngineError("Choose one Steam library snapshot at a time")
            parsed, document = [], parse_steam_file(content)
        else:
            parsed, document = parse_media(provider, upload.filename or "media-export", content), None
        for row in parsed:
            key = "%s|%s|%s|%s" % (row["provider"], row["occurred_at"], row["title"], row["creator"] or "")
            if provider == "youtube":
                key += "|%s" % (row["source"].get("video_id") or "unavailable")
            if provider == "netflix":
                key += "|%s|%s" % (row["source"]["profile"], row["source"]["occurrence"])
            row["id"] = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            rows.append(row)
        if document:
            identity = "steam-library" if provider == "steam" else (upload.filename or "spotify.json")
            document["id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
            document["filename"] = upload.filename or "spotify.json"
            payload = {key: value for key, value in document.items() if key not in ("id", "filename", "payload")}
            documents.append({"id": document["id"], "filename": document["filename"], "kind": document["kind"], "payload": payload})
    if not rows and not documents:
        raise EngineError("No supported media records or summaries were found in these files")
    youtube_selection = {}
    if provider == "youtube":
        available = len(rows)
        rows.sort(key=lambda row: (row["occurred_at"], row["id"]), reverse=True)
        if youtube_range != "all":
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(youtube_range))
            rows = [row for row in rows if datetime.fromisoformat(row["occurred_at"]) >= cutoff]
        rows = rows[:5000]
        if not rows:
            raise EngineError("No YouTube viewing entries in the selected period. Choose a wider range; your saved history is unchanged.")
        youtube_selection = {"available": available, "skipped": available - len(rows), "youtube_range": youtube_range, "entry_limit": 5000}
    p.store.replace_media(provider, rows, documents)
    saved = p.store.media_events()
    saved.sort(key=lambda row: (row.get("occurred_at", ""), row.get("id", "")), reverse=True)
    imported = len(documents[0]["payload"]["games"]) if provider == "steam" else len(rows)
    return J({"imported": imported, **youtube_selection, **_media_payload(saved), "documents": p.store.media_documents()})


@app.post("/api/persona")
def post_persona(body: Optional[Dict[str, Any]] = Body(None), p: Principal = Depends(current_principal)):
    body = body or {}
    prof = p.store.profile()
    key = str(body.get("persona") or prof["persona"])
    if key not in PERSONAS:
        raise EngineError("unknown persona %r" % key)
    seed = body.get("seed")
    seed = int(seed) if seed not in (None, "") else int(prof["seed"])
    session.switch_persona(p.user_id, p.store, key, seed)
    with session.engine_session(p.user_id, p.store) as e:
        return J(meta_payload(e))


@app.post("/api/reset")
def post_reset(p: Principal = Depends(current_principal)):
    session.reset(p.user_id, p.store)
    with session.engine_session(p.user_id, p.store) as e:
        return J(meta_payload(e))


@app.post("/api/log")
def post_log(body: Optional[Dict[str, Any]] = Body(None)):
    body = body or {}
    log.warning("client %s: %s %s", body.get("level", "log"), str(body.get("message", ""))[:500], str(body.get("stack", ""))[:800])
    return J({"ok": True})
