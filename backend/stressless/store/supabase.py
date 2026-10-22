"""UserStore backed by Supabase Postgres through PostgREST (schema: supabase/migrations).

Every request carries the signed-in user's access token, so row-level security does the per-user isolation; this
class never sees another user's rows. One RPC call loads the whole state snapshot, writes update the snapshot in place.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from ..models import CalendarEvent, from_dict, to_jsonable
from ..reports import Report
from .base import DEFAULT_PROFILE, UserStore

log = logging.getLogger("stressless.store.supabase")
_client: Optional[httpx.Client] = None
PAGE = 1000


class SupabaseError(Exception):
    pass


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=10.0)
    return _client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SupabaseStore(UserStore):
    def __init__(self, url: str, anon_key: str, access_token: str, user_id: str) -> None:
        self.rest = url.rstrip("/") + "/rest/v1"
        self.user_id = user_id
        self.headers = {"apikey": anon_key, "Authorization": "Bearer " + access_token, "Content-Type": "application/json"}
        self._snap: Optional[Dict[str, Any]] = None

    # ---------------------------------------------------------------- http --
    def _call(self, method: str, path: str, *, params: Optional[Dict[str, str]] = None, json: Any = None,
              prefer: Optional[str] = None) -> Any:
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        try:
            r = _http().request(method, self.rest + path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise SupabaseError("Supabase unreachable: %s" % exc) from exc
        if r.status_code >= 400:
            raise SupabaseError("Supabase %s %s -> %d %s" % (method, path, r.status_code, r.text[:300]))
        return r.json() if r.content else None

    def _upsert(self, table: str, row: Dict[str, Any], on_conflict: str) -> None:
        row = dict(row, user_id=self.user_id)
        self._call("POST", "/" + table, params={"on_conflict": on_conflict}, json=row, prefer="resolution=merge-duplicates,return=minimal")

    def _state(self) -> Dict[str, Any]:
        if self._snap is None:
            raw = self._call("POST", "/rpc/stressless_state", json={}) or {}
            events: Dict[str, CalendarEvent] = {}
            for row in raw.get("user_events") or []:
                try:
                    ev = from_dict(CalendarEvent, row["event"])
                    events[ev.id] = ev
                except Exception as exc:
                    log.warning("skipping unreadable user event: %s", exc)
            self._snap = {
                "profile": raw.get("profile"),
                "answers": {a["check_id"]: {"answer": a["answer"], "event_id": a.get("event_id"), "visit_id": a.get("visit_id"), "ts": a.get("ts")}
                            for a in raw.get("answers") or []},
                "events": events,
                "accepted": {a["suggestion_id"]: a["event_id"] for a in raw.get("accepted") or []},
            }
        return self._snap

    # ------------------------------------------------------------- profile --
    def profile(self) -> Dict[str, Any]:
        p = self._state()["profile"]
        if not p:
            return dict(DEFAULT_PROFILE)
        return {"persona": p.get("persona") or "alex", "seed": int(p.get("seed") if p.get("seed") is not None else 7), "anchor": p.get("anchor")}

    def set_profile(self, persona: str, seed: int, anchor: Optional[str]) -> None:
        self._upsert("profiles", {"persona": persona, "seed": int(seed), "anchor": anchor, "updated_at": _now()}, "user_id")
        self._state()["profile"] = {"persona": persona, "seed": int(seed), "anchor": anchor}

    # ---------------------------------------------------------- user state --
    def answers(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self._state()["answers"].items()}

    def save_answer(self, check_id: str, answer: str, event_id: Optional[str], visit_id: Optional[str]) -> None:
        row = {"check_id": check_id, "answer": answer, "event_id": event_id, "visit_id": visit_id, "ts": _now()}
        self._upsert("answers", row, "user_id,check_id")
        self._state()["answers"][check_id] = {k: row[k] for k in ("answer", "event_id", "visit_id", "ts")}

    def user_events(self) -> List[CalendarEvent]:
        return list(self._state()["events"].values())

    def add_user_event(self, ev: CalendarEvent) -> None:
        self._upsert("user_events", {"id": ev.id, "event": to_jsonable(ev), "ts": _now()}, "user_id,id")
        self._state()["events"][ev.id] = ev

    def accepted(self) -> Dict[str, str]:
        return dict(self._state()["accepted"])

    def save_accepted(self, suggestion_id: str, event_id: str) -> None:
        self._upsert("accepted", {"suggestion_id": suggestion_id, "event_id": event_id, "ts": _now()}, "user_id,suggestion_id")
        self._state()["accepted"][suggestion_id] = event_id

    def get_narrative(self, key: str) -> Optional[str]:
        rows = self._call("GET", "/narratives", params={"select": "text", "key": "eq." + key, "limit": "1"})
        return rows[0]["text"] if rows else None

    def set_narrative(self, key: str, mode: str, text: str) -> None:
        self._upsert("narratives", {"key": key, "mode": mode, "text": text, "ts": _now()}, "user_id,key")

    def clear_user_state(self) -> None:
        self._call("POST", "/rpc/stressless_clear_state", json={})
        snap = self._state()
        snap["answers"], snap["events"], snap["accepted"] = {}, {}, {}

    def set_consent(self) -> None:
        now = _now()
        self._upsert("profiles", {"consented_at": now}, "user_id")
        self._state()["profile"] = dict(self._state()["profile"] or {}, consented_at=now)

    def time_zone(self) -> str:
        return (self._state()["profile"] or {}).get("time_zone") or "Europe/Stockholm"

    def rows(self, table: str, column: Optional[str] = None, lo: Optional[str] = None, hi: Optional[str] = None
             ) -> List[Dict[str, Any]]:
        """Read through RLS (the user's own rows), 1000 rows per request, the PostgREST default maximum."""
        params = {"select": "*"}
        conds = ["%s.gte.%s" % (column, lo)] * (lo is not None) + ["%s.lte.%s" % (column, hi)] * (hi is not None)
        if column:
            params["order"] = column
        if conds:
            params["and"] = "(%s)" % ",".join(conds)
        out: List[Dict[str, Any]] = []
        while True:
            page = self._call("GET", "/" + table, params=dict(params, limit=str(PAGE), offset=str(len(out)))) or []
            out.extend(page)
            if len(page) < PAGE:
                return out

    def consented(self) -> bool:
        return bool((self._state()["profile"] or {}).get("consented_at"))

    # ------------------------------------------------------------- reports --
    @staticmethod
    def _report_filter(kind: str, period_start: date) -> Dict[str, str]:
        return {"kind": "eq." + kind, "period_start": "eq." + period_start.isoformat()}

    def report_row(self, kind: str, period_start: date) -> Optional[Dict[str, Any]]:
        params = dict(self._report_filter(kind, period_start), select="status,report,created_at", limit="1")
        rows = self._call("GET", "/reports", params=params)
        if not rows:
            return None
        row = rows[0]
        return {"status": row["status"], "created_at": row["created_at"],
                "report": Report.model_validate(row["report"]) if row.get("report") else None}

    def claim_report(self, kind: str, period_start: date) -> bool:
        row = {"user_id": self.user_id, "kind": kind, "period_start": period_start.isoformat()}
        rows = self._call("POST", "/reports", params={"on_conflict": "user_id,kind,period_start", "select": "kind"}, json=row,
                          prefer="resolution=ignore-duplicates,return=representation")
        return bool(rows)

    def save_report(self, report: Report) -> None:
        body = {"status": "ready", "mode": report.mode, "model": report.model, "report": report.model_dump(mode="json"),
                "updated_at": _now()}
        params = dict(self._report_filter(report.kind, report.period_start), status="eq.pending")
        self._call("PATCH", "/reports", params=params, json=body, prefer="return=minimal")

    def reports_last_day(self) -> int:
        return int(self._call("POST", "/rpc/stressless_reports_last_day", json={}) or 0)
    def media_events(self) -> List[Dict[str, Any]]:
        return self._call("GET", "/media_events", params={"select": "id,provider,occurred_at,title,creator,minutes,source,imported_at", "order": "occurred_at.desc"}) or []

    def media_documents(self) -> List[Dict[str, Any]]:
        return self._call("GET", "/media_documents", params={"select": "id,filename,kind,payload,imported_at", "order": "imported_at.desc"}) or []

    def replace_media(self, provider: str, events: List[Dict[str, Any]], documents: List[Dict[str, Any]]) -> None:
        self._call("POST", "/rpc/stressless_replace_media", json={
            "p_provider": provider, "p_events": events, "p_documents": documents,
        })
