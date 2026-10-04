"""FastAPI app: the JSON API (SPEC §8.2). Same routes and payloads as the original localhost server, per signed-in user.

Run locally with ``uvicorn api.index:app --port 8000``; on Vercel ``api/index.py`` serves it under /api.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from typing import Any, Dict, Optional

from fastapi import Body, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..engine.pipeline import EngineError
from ..engine.reasoning import reasoning_mode
from ..models import to_jsonable
from ..sim.personas import PERSONA_ORDER, PERSONAS
from ..store import SupabaseError
from ..timeutil import parse_date
from . import session
from .auth import Principal, current_principal

log = logging.getLogger("stressless.server")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="StressLess API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
JSON_TYPE = "application/json; charset=utf-8"


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
