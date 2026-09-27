"""JSON API routes (SPEC §8.2). Each handler returns (status, payload) or (status, content_type, bytes, headers)."""
from __future__ import annotations

import logging
import re
import sys
import traceback
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import __version__
from ..engine.pipeline import EngineError, NotFound
from ..engine.reasoning import reasoning_mode
from ..models import to_jsonable
from ..sim.personas import PERSONAS, PERSONA_ORDER
from ..timeutil import parse_date

log = logging.getLogger("stressless.server.api")
Route = Tuple[str, "re.Pattern[str]", Callable[..., Any]]
ROUTES: List[Route] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


def _int_or_none(v: Optional[str]) -> Optional[int]:
    if v is None or v == "" or v == "null":
        return None
    return int(v)


def _date(s: str) -> date:
    try:
        return parse_date(s)
    except ValueError:
        raise EngineError("Bad date %r (expected YYYY-MM-DD)" % s)


def meta_payload(state) -> Dict[str, Any]:
    ds = state.engine.ds
    personas = []
    for key in PERSONA_ORDER:
        p = PERSONAS[key]
        ready = (key == ds.persona.key) or state.pregen.get(key) == "ready"
        personas.append({"key": key, "name": p.name, "tagline": p.tagline, "ready": ready})
    return {
        "persona": {"key": ds.persona.key, "name": ds.persona.name, "tagline": ds.persona.tagline, "description": ds.persona.description, "tz": ds.persona.tz},
        "personas": personas, "seed": ds.seed, "days": (ds.end - ds.start).days + 1, "source": ds.source,
        "start": ds.start, "end": ds.end, "today": ds.today, "anchor_mode": state.anchor is not None,
        "n_nights": sum(1 for n in ds.nights if n.worn and n.score is not None), "reasoning_mode": reasoning_mode(),
        "version": __version__, "history_days_options": [7, 14, 28, None], "generated_at": ds.generated_at, "showcase": ds.showcase,
    }


@route("GET", "/api/meta")
def get_meta(state, m, q, body):
    return 200, meta_payload(state)


@route("GET", "/api/health")
def get_health(state, m, q, body):
    ds = state.engine.ds
    return 200, {"ok": all(state.health.values()) if state.health else True, "python": sys.version.split()[0], "version": __version__,
                 "persona": ds.persona.key, "n_nights": sum(1 for n in ds.nights if n.worn), "today": ds.today, "checks": state.health}


@route("GET", r"/api/report/(\d{4}-\d{2}-\d{2})\.md")
def get_report_md(state, m, q, body):
    report = state.engine.morning_report(_date(m.group(1)), _int_or_none(q.get("history_days")))
    return 200, "text/markdown; charset=utf-8", state.engine.report_markdown(report).encode("utf-8"), {}


@route("GET", r"/api/report/(\d{4}-\d{2}-\d{2})")
def get_report(state, m, q, body):
    return 200, state.engine.morning_report(_date(m.group(1)), _int_or_none(q.get("history_days")))


@route("GET", r"/api/day/(\d{4}-\d{2}-\d{2})")
def get_day(state, m, q, body):
    return 200, state.engine.day_bundle(_date(m.group(1)))


@route("GET", "/api/week")
def get_week(state, m, q, body):
    end = _date(q["end"]) if q.get("end") else state.engine.ds.today
    return 200, state.engine.week(end, _int_or_none(q.get("history_days")))


@route("GET", "/api/habits")
def get_habits(state, m, q, body):
    upto = _date(q["upto"]) if q.get("upto") else state.engine.ds.today
    hd = _int_or_none(q.get("history_days"))
    return 200, {"habits": state.engine.habits(upto, hd), "model": state.engine.model_summary(upto, hd)}


@route("GET", "/api/model")
def get_model(state, m, q, body):
    upto = _date(q["upto"]) if q.get("upto") else state.engine.ds.today
    return 200, state.engine.model_summary(upto, _int_or_none(q.get("history_days")))


@route("GET", "/api/reality")
def get_reality(state, m, q, body):
    return 200, state.engine.reality()


@route("POST", r"/api/reality/([A-Za-z0-9_:\-]+)/answer")
def post_answer(state, m, q, body):
    return 200, state.engine.answer(m.group(1), str((body or {}).get("answer", "")))


@route("POST", "/api/whatif")
def post_whatif(state, m, q, body):
    body = body or {}
    if "date" not in body:
        raise EngineError("whatif needs a date")
    return 200, state.engine.whatif(_date(str(body["date"])), body.get("mods") or [])


@route("POST", r"/api/suggestions/(\d{4}-\d{2}-\d{2})/([A-Za-z0-9_:\-]+)/accept")
def post_accept(state, m, q, body):
    s, ev, ics = state.engine.accept_suggestion(_date(m.group(1)), m.group(2))
    return 200, {"suggestion": s, "event": ev, "ics": ics}


@route("GET", r"/api/suggestions/(\d{4}-\d{2}-\d{2})/([A-Za-z0-9_:\-]+)\.ics")
def get_ics(state, m, q, body):
    ics = state.engine.suggestion_ics(_date(m.group(1)), m.group(2))
    return 200, "text/calendar; charset=utf-8", ics.encode("utf-8"), {"Content-Disposition": 'attachment; filename="stressless-%s.ics"' % m.group(2)}


@route("GET", "/api/validation")
def get_validation(state, m, q, body):
    return 200, state.engine.validation()


@route("POST", "/api/persona")
def post_persona(state, m, q, body):
    body = body or {}
    key = str(body.get("persona") or state.engine.ds.persona.key)
    if key not in PERSONAS:
        raise EngineError("unknown persona %r" % key)
    seed = body.get("seed")
    seed = int(seed) if seed not in (None, "") else state.seed
    state.switch(key, seed)
    return 200, meta_payload(state)


@route("POST", "/api/reset")
def post_reset(state, m, q, body):
    state.reset()
    return 200, meta_payload(state)


@route("POST", "/api/log")
def post_log(state, m, q, body):
    body = body or {}
    log.warning("client %s: %s %s", body.get("level", "log"), str(body.get("message", ""))[:500], str(body.get("stack", ""))[:800])
    return 200, {"ok": True}


def dispatch(state, method: str, path: str, query: Dict[str, str], body: Optional[Dict[str, Any]]):
    """Return (status, content_type, bytes, extra_headers)."""
    for m_method, pattern, fn in ROUTES:
        m = pattern.match(path)
        if m and m_method == method:
            try:
                with state.lock:
                    result = fn(state, m, query, body)
            except EngineError as exc:
                return exc.status, "application/json; charset=utf-8", _json({"error": str(exc)}), {}
            except ValueError as exc:
                return 400, "application/json; charset=utf-8", _json({"error": str(exc)}), {}
            except Exception as exc:  # pragma: no cover
                traceback.print_exc(file=sys.stderr)
                return 500, "application/json; charset=utf-8", _json({"error": "%s: %s" % (type(exc).__name__, exc)}), {}
            if len(result) == 2:
                status, payload = result
                return status, "application/json; charset=utf-8", _json(payload), {}
            return result
    for m_method, pattern, fn in ROUTES:
        if pattern.match(path):
            return 405, "application/json; charset=utf-8", _json({"error": "method not allowed"}), {}
    return 404, "application/json; charset=utf-8", _json({"error": "no such route: %s" % path}), {}


def _json(payload: Any) -> bytes:
    import json
    return json.dumps(to_jsonable(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
