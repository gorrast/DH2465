"""In-memory UserStore for tests and offline use."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..models import CalendarEvent
from .base import DEFAULT_PROFILE, UserStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryStore(UserStore):
    def __init__(self) -> None:
        self._profile: Dict[str, Any] = dict(DEFAULT_PROFILE)
        self._answers: Dict[str, Dict[str, Any]] = {}
        self._events: Dict[str, CalendarEvent] = {}
        self._accepted: Dict[str, str] = {}
        self._narratives: Dict[str, str] = {}

    def profile(self) -> Dict[str, Any]:
        return dict(self._profile)

    def set_profile(self, persona: str, seed: int, anchor: Optional[str]) -> None:
        self._profile = {"persona": persona, "seed": int(seed), "anchor": anchor}

    def answers(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self._answers.items()}

    def save_answer(self, check_id: str, answer: str, event_id: Optional[str], visit_id: Optional[str]) -> None:
        self._answers[check_id] = {"answer": answer, "event_id": event_id, "visit_id": visit_id, "ts": _now()}

    def user_events(self) -> List[CalendarEvent]:
        return [copy.deepcopy(e) for e in self._events.values()]

    def add_user_event(self, ev: CalendarEvent) -> None:
        self._events[ev.id] = copy.deepcopy(ev)

    def accepted(self) -> Dict[str, str]:
        return dict(self._accepted)

    def save_accepted(self, suggestion_id: str, event_id: str) -> None:
        self._accepted[suggestion_id] = event_id

    def get_narrative(self, key: str) -> Optional[str]:
        return self._narratives.get(key)

    def set_narrative(self, key: str, mode: str, text: str) -> None:
        self._narratives[key] = text

    def clear_user_state(self) -> None:
        self._answers.clear()
        self._events.clear()
        self._accepted.clear()
        self._narratives.clear()
