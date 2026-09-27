"""sqlite persistence: the dataset blob plus the user's answers, added events and accepted suggestions (SPEC §6.2)."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..models import CalendarEvent, Dataset, dataset_from_dict, dumps, from_dict

log = logging.getLogger("stressless.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS dataset (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT);
CREATE TABLE IF NOT EXISTS answers (check_id TEXT PRIMARY KEY, answer TEXT, event_id TEXT, visit_id TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS user_events (id TEXT PRIMARY KEY, json TEXT);
CREATE TABLE IF NOT EXISTS accepted (suggestion_id TEXT PRIMARY KEY, event_id TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS narratives (key TEXT PRIMARY KEY, mode TEXT, text TEXT, ts TEXT);
"""
USER_TABLES = ("answers", "user_events", "accepted", "narratives")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------- dataset --
    def meta(self) -> Dict[str, str]:
        with self._lock:
            return {k: v for k, v in self._conn.execute("SELECT key, value FROM meta")}

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, "" if value is None else str(value)))
            self._conn.commit()

    def save_dataset(self, ds: Dataset) -> None:
        with self._lock:
            old = self.meta()
            new = {"persona": ds.persona.key, "seed": str(ds.seed), "anchor": ds.today.isoformat(), "days": str((ds.end - ds.start).days + 1),
                   "source": ds.source}
            if old and any(old.get(k) != new[k] for k in ("persona", "seed", "anchor")):
                log.info("dataset identity changed (%s -> %s); clearing user state", {k: old.get(k) for k in new}, new)
                self.clear_user_state()
            self._conn.execute("INSERT OR REPLACE INTO dataset(id, json) VALUES (1, ?)", (dumps(ds),))
            for k, v in new.items():
                self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (k, v))
            self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('saved_at', ?)", (_now(),))
            self._conn.commit()

    def load_dataset(self) -> Optional[Dataset]:
        with self._lock:
            row = self._conn.execute("SELECT json FROM dataset WHERE id = 1").fetchone()
        if not row:
            return None
        try:
            return dataset_from_dict(json.loads(row[0]))
        except Exception as exc:
            log.warning("stored dataset unreadable (%s); regenerating", exc)
            return None

    def apply_to(self, ds: Dataset) -> None:
        """Mechanically replay user state onto a pristine dataset."""
        for ev in self.user_events():
            if ds.event(ev.id) is None:
                ds.add_event(ev)
        for check_id, a in self.answers().items():
            if a.get("event_id") and ds.event(a["event_id"]) is not None and a.get("answer") in ("yes", "no"):
                ds.set_attended(a["event_id"], a["answer"] == "yes")

    # ---------------------------------------------------------- user state --
    def save_answer(self, check_id: str, answer: str, event_id: Optional[str], visit_id: Optional[str]) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO answers(check_id, answer, event_id, visit_id, ts) VALUES (?, ?, ?, ?, ?)",
                               (check_id, answer, event_id, visit_id, _now()))
            self._conn.commit()

    def answers(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT check_id, answer, event_id, visit_id, ts FROM answers").fetchall()
        return {r[0]: {"answer": r[1], "event_id": r[2], "visit_id": r[3], "ts": r[4]} for r in rows}

    def add_user_event(self, ev: CalendarEvent) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO user_events(id, json) VALUES (?, ?)", (ev.id, dumps(ev)))
            self._conn.commit()

    def user_events(self) -> List[CalendarEvent]:
        with self._lock:
            rows = self._conn.execute("SELECT json FROM user_events").fetchall()
        out = []
        for (j,) in rows:
            try:
                out.append(from_dict(CalendarEvent, json.loads(j)))
            except Exception as exc:
                log.warning("skipping unreadable user event: %s", exc)
        return out

    def save_accepted(self, suggestion_id: str, event_id: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO accepted(suggestion_id, event_id, ts) VALUES (?, ?, ?)", (suggestion_id, event_id, _now()))
            self._conn.commit()

    def accepted(self) -> Dict[str, str]:
        with self._lock:
            return {r[0]: r[1] for r in self._conn.execute("SELECT suggestion_id, event_id FROM accepted")}

    def get_narrative(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute("SELECT text FROM narratives WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_narrative(self, key: str, mode: str, text: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO narratives(key, mode, text, ts) VALUES (?, ?, ?, ?)", (key, mode, text, _now()))
            self._conn.commit()

    def state_version(self) -> str:
        blob = json.dumps([sorted(self.answers().items()), sorted(self.accepted().items()), sorted(e.id for e in self.user_events())], sort_keys=True, default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]

    def clear_user_state(self) -> None:
        with self._lock:
            for t in USER_TABLES:
                self._conn.execute("DELETE FROM %s" % t)
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            for t in USER_TABLES + ("dataset", "meta"):
                self._conn.execute("DELETE FROM %s" % t)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
