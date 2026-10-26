"""Routes for the generated daily and weekly reports.

* ``GET  /api/reports``                  — today's periods, their status, and the data sources (readiness dialog)
* ``GET  /api/reports/{kind}/{period}``  — one stored report
* ``POST /api/reports/{kind}/{period}``  — generate it: daily only for today, weekly only for the week that just ended;
  ``?regenerate=true`` throws the stored one away first (dev servers only, ``ENVIRONMENT`` other than ``PROD``)
* ``POST /api/reports/consent``          — the user agrees to AI-written reports (``profiles.consented_at``)

A period is claimed in the database before the model is called, so it can never cost more than one call. The model
is skipped (rule writer instead) when it is switched off, the global daily cap is reached, the user has not
consented (real data only), the claim went stale, or the call fails.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ..connectors.real_data import real_sources
from ..engine.pipeline import EngineError, NotFound
from ..engine.report_input import daily_input, weekly_input
from ..engine.report_writer import ClaudeReportWriter, ReportWriterError, Written, claude_enabled, write_rules
from ..models import to_jsonable
from ..reports import Report, ReportInput, SourceStatus
from ..timeutil import parse_date
from . import session
from .auth import Principal, current_principal

log = logging.getLogger("stressless.server.reports")
router = APIRouter()
KINDS = ("daily", "weekly")
STALE_AFTER = timedelta(minutes=5)             # a pending claim older than this is treated as a failed generation


class ReportBusy(EngineError):
    status = 409


class Forbidden(EngineError):
    status = 403


def is_dev() -> bool:
    """Anything but ENVIRONMENT=PROD is a dev server, where a stored report may be generated again for testing."""
    return os.environ.get("ENVIRONMENT", "").strip().upper() != "PROD"


def daily_cap() -> int:
    return int(os.environ.get("STRESSLESS_REPORT_DAILY_CAP", "50"))


def _json(payload: Any, status: int = 200) -> Response:
    import json
    return Response(content=json.dumps(to_jsonable(payload), ensure_ascii=False, allow_nan=False), status_code=status,
                    media_type="application/json; charset=utf-8", headers={"Cache-Control": "no-store"})


def current_periods(today: date) -> Dict[str, date]:
    """Daily: this morning. Weekly: the Monday of the last full week (Monday to Sunday) before today."""
    return {"daily": today, "weekly": today - timedelta(days=today.weekday() + 7)}


def _parse(kind: str, period: str) -> date:
    if kind not in KINDS:
        raise NotFound("Unknown report kind %r" % kind)
    try:
        d = parse_date(period)
    except ValueError:
        raise EngineError("Bad date %r (expected YYYY-MM-DD)" % period)
    if kind == "weekly" and d.weekday() != 0:
        raise EngineError("A weekly report starts on a Monday")
    return d


def sources_for(engine, morning: date, store=None) -> List[SourceStatus]:
    """Data-source status for the readiness dialog: from the sync tables with real data, from the dataset in the demo."""
    ds = engine.ds
    if ds.source != "demo":
        return real_sources(store or engine.store, ds, morning)
    worn = [n for n in ds.nights if n.worn and n.date < morning]
    last = max(worn, key=lambda n: n.date) if worn else None
    data_until = (last.out_of_bed or last.wake_time) if last else None
    night = ds.night(morning - timedelta(days=1))
    past_events = [e.end for e in ds.events if e.end.date() < morning]
    return [
        SourceStatus(key="watch", label="Watch: sleep and heart rate", connected=bool(ds.nights), data_until=data_until,
                     synced_at=ds.generated_at, required=True, ready=bool(night and night.worn and night.score is not None)),
        SourceStatus(key="calendar", label="Calendar", connected=bool(ds.events),
                     data_until=max(past_events) if past_events else None, synced_at=ds.generated_at, required=False,
                     ready=bool(ds.events)),
    ]


def _row_status(row: Optional[Dict[str, Any]]) -> str:
    return row["status"] if row else "none"


def _is_stale(row: Dict[str, Any]) -> bool:
    created = row.get("created_at")
    if created is None:
        return True
    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - created > STALE_AFTER


def generate(engine, store, kind: str, period: date, writer: Optional[ClaudeReportWriter] = None) -> Report:
    """Return the report for (kind, period), generating it at most once."""
    row = store.report_row(kind, period)
    if row and row["status"] == "ready":
        return row["report"]
    if row and not _is_stale(row):
        raise ReportBusy("This report is being generated. Try again in a moment.")
    if row is None:
        over_cap = store.reports_last_day() >= daily_cap()
        if not store.claim_report(kind, period):           # someone else claimed it in between
            return generate(engine, store, kind, period, writer)
    else:
        over_cap = True                                    # stale claim: finish it without another model call
        log.warning("finishing a stale %s report for %s with rules", kind, period)

    report_input: ReportInput = daily_input(engine, period) if kind == "daily" else weekly_input(engine, period)
    consented = engine.ds.source == "demo" or store.consented()
    written: Optional[Written] = None
    if claude_enabled() and not over_cap and consented:
        try:
            written = (writer or ClaudeReportWriter()).write(report_input)
            log.info("%s report for %s written by %s, usage %s", kind, period, written.model, written.usage)
        except ReportWriterError as exc:
            log.warning("%s report for %s: %s; using rules", kind, period, exc)
    if written is None:
        written = write_rules(report_input)
    report = Report(kind=kind, period_start=report_input.period_start, period_end=report_input.period_end,
                    generated_at=datetime.now(timezone.utc), mode=written.mode, model=written.model,
                    input=report_input, content=written.content, sources=sources_for(engine, report_input.period_start, store))
    store.save_report(report)
    return report


# ----------------------------------------------------------------- routes --
@router.get("/api/reports")
def get_reports(p: Principal = Depends(current_principal)):
    with session.engine_session(p.user_id, p.store) as e:
        today = e.ds.today
        periods = current_periods(today)
        sources = sources_for(e, today, p.store)
        return _json({
            "today": today,
            "daily": {"period": periods["daily"], "status": _row_status(p.store.report_row("daily", periods["daily"]))},
            "weekly": {"period": periods["weekly"], "status": _row_status(p.store.report_row("weekly", periods["weekly"]))},
            "sources": [s.model_dump(mode="json") for s in sources],
            "ready": all(s.ready for s in sources if s.required),
            "consented": e.ds.source == "demo" or p.store.consented(),
            "ai": claude_enabled(),
            "dev": is_dev(),
        })


@router.post("/api/reports/consent")
def post_consent(p: Principal = Depends(current_principal)):
    p.store.set_consent()
    return _json({"consented": True})


@router.get("/api/reports/{kind}/{period}")
def get_report(kind: str, period: str, p: Principal = Depends(current_principal)):
    d = _parse(kind, period)
    row = p.store.report_row(kind, d)
    return _json({"status": _row_status(row),
                  "report": row["report"].model_dump(mode="json") if row and row.get("report") else None})


@router.post("/api/reports/{kind}/{period}")
def post_report(kind: str, period: str, regenerate: bool = False, p: Principal = Depends(current_principal)):
    d = _parse(kind, period)
    if regenerate and not is_dev():
        raise Forbidden("Reports can only be generated again on a dev server.")
    with session.engine_session(p.user_id, p.store) as e:
        expected = current_periods(e.ds.today)[kind]
        if d != expected:
            raise EngineError("Only the %s report for %s can be generated now." % (kind, expected.isoformat()))
        if kind == "daily" and not all(s.ready for s in sources_for(e, d, p.store) if s.required):
            raise EngineError("Last night's watch data has not arrived yet.")
        if kind == "weekly" and not any(e.ds.night(d + timedelta(days=k)) and e.ds.night(d + timedelta(days=k)).worn
                                        for k in range(7)):
            raise EngineError("There is no watch data for that week.")
        if regenerate:
            log.info("dev: discarding the stored %s report for %s", kind, d)
            p.store.discard_report(kind, d)
        report = generate(e, p.store, kind, d)
        return _json({"status": "ready", "report": report.model_dump(mode="json")})
