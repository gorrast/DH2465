"""Per-user state behind one interface (SPEC §6.2).

The dataset itself is never stored: it is regenerated deterministically from the user's profile (persona, seed,
anchor date). Only the user's own deltas — reality-check answers, events they added, accepted suggestions and cached
narratives — are persisted, and replayed onto a pristine dataset with ``apply_to``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from ..models import CalendarEvent, Dataset

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
        """Remove answers, added events, accepted suggestions and narratives (the profile stays)."""
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
