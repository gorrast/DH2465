"""Per-user state behind one interface (SPEC §6.2).

The dataset itself is never stored: it is regenerated deterministically from the user's profile (persona, seed,
anchor date). Only the user's own deltas — reality-check answers, events they added, accepted suggestions and cached
narratives — are persisted, and replayed onto a pristine dataset with ``apply_to``.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Dict, List, Optional

from ..models import CalendarEvent, Dataset
from ..reports import Report

DEFAULT_PROFILE = {"persona": "alex", "seed": 7, "anchor": None}


class UserStore:
    """Abstract per-user store. Subclasses implement the storage primitives below."""

    # ------------------------------------------------------------- profile --
    def profile(self) -> Dict[str, Any]:
        """{"persona": str, "seed": int, "anchor": "YYYY-MM-DD" | None} — the identity of the user's demo dataset."""
        raise NotImplementedError

    def set_profile(self, persona: str, seed: int, anchor: Optional[str]) -> None:
        raise NotImplementedError

    # ---------------------------------------------------------- user state --
    def answers(self) -> Dict[str, Dict[str, Any]]:
        raise NotImplementedError

    def save_answer(self, check_id: str, answer: str, event_id: Optional[str], visit_id: Optional[str]) -> None:
        raise NotImplementedError

    def user_events(self) -> List[CalendarEvent]:
        raise NotImplementedError

    def add_user_event(self, ev: CalendarEvent) -> None:
        raise NotImplementedError

    def accepted(self) -> Dict[str, str]:
        raise NotImplementedError

    def save_accepted(self, suggestion_id: str, event_id: str) -> None:
        raise NotImplementedError

    def get_narrative(self, key: str) -> Optional[str]:
        raise NotImplementedError

    def set_narrative(self, key: str, mode: str, text: str) -> None:
        raise NotImplementedError

    def clear_user_state(self) -> None:
        """Remove answers, added events, accepted suggestions and narratives (the profile and reports stay)."""
        raise NotImplementedError

    def set_consent(self) -> None:
        """Record that the user agreed to AI-written reports (``profiles.consented_at = now()``)."""
        raise NotImplementedError

    def time_zone(self) -> str:
        """The user's IANA time zone (``profiles.time_zone``); it defines "today", "last night" and the week."""
        raise NotImplementedError

    def rows(self, table: str, column: Optional[str] = None, lo: Optional[str] = None, hi: Optional[str] = None
             ) -> List[Dict[str, Any]]:
        """The user's rows of a real-data table, optionally with ``lo <= column <= hi`` (ISO strings), ordered by
        ``column``. Rows look like PostgREST JSON: timestamps and dates as ISO strings."""
        raise NotImplementedError

    def consented(self) -> bool:
        """Whether the user agreed to their summaries being sent to the AI service (``profiles.consented_at``)."""
        raise NotImplementedError

    # ------------------------------------------------------------- reports --
    # One report per kind and period. It is claimed before the model is called, so a period can never cost
    # more than one call; nothing here deletes a report.
    def report_row(self, kind: str, period_start: date) -> Optional[Dict[str, Any]]:
        """{"status": "pending" | "ready", "report": Report | None, "created_at": ISO string}, or None."""
        raise NotImplementedError

    def claim_report(self, kind: str, period_start: date) -> bool:
        """Reserve the period. False when it was already claimed (pending or ready)."""
        raise NotImplementedError

    def save_report(self, report: Report) -> None:
        """Fill in a claimed, still pending report."""
        raise NotImplementedError

    def reports_last_day(self) -> int:
        """Reports claimed by all users in the last 24 hours (the global cap on model calls)."""
        raise NotImplementedError

    def media_events(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def media_documents(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def replace_media(self, provider: str, events: List[Dict[str, Any]], documents: List[Dict[str, Any]]) -> None:
        """Replace file histories/snapshots; Last.fm batches merge by event ID and update sync metadata atomically."""
        raise NotImplementedError

    def clear_media(self, provider: str, document_kind: str) -> None:
        """Delete the user's events of ``provider`` and their media documents of ``document_kind`` (a disconnect)."""
        raise NotImplementedError

    def pending_netflix_artwork(self, limit: int = 200) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def update_netflix_artwork(self, updates: List[Dict[str, Any]]) -> None:
        """Patch only artwork fields for matching Netflix lookup keys, preserving all history."""
        raise NotImplementedError

    # ------------------------------------------------------------- derived --
    def apply_to(self, ds: Dataset) -> None:
        """Mechanically replay user state onto a pristine dataset."""
        for ev in self.user_events():
            if ds.event(ev.id) is None:
                ds.add_event(ev)
        for check_id, a in self.answers().items():
            if a.get("event_id") and ds.event(a["event_id"]) is not None and a.get("answer") in ("yes", "no"):
                ds.set_attended(a["event_id"], a["answer"] == "yes")

    def state_version(self) -> str:
        answers = sorted((k, v.get("answer"), v.get("event_id")) for k, v in self.answers().items())
        blob = json.dumps([answers, sorted(self.accepted().items()), sorted(e.id for e in self.user_events())], sort_keys=True, default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]
