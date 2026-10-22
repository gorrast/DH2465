"""Per-request engines on stateless functions (SPEC §8.1).

A user's dataset is identified by (persona, seed, today) and regenerated on demand — about 0.15 s — then the user's
own state is replayed onto it. Warm instances keep recently generated datasets and recently used engines in small LRU
caches, so most requests skip both generation and model fitting.

The app runs on each signed-in user's own data, read from the real-data tables (``connectors.real_data``). It changes
whenever the phone syncs, so an engine is reused for at most REAL_TTL seconds. The simulated personas are only kept
for the older test suites (STRESSLESS_DATA=demo) until the simulator is removed.
"""
from __future__ import annotations

import copy
import logging
import os
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, Hashable, Iterator, Optional, Tuple

from ..connectors.real_data import load_dataset, valid_tz
from ..engine.pipeline import Engine
from ..models import Dataset
from ..sim import PERSONAS, generate_dataset, get_persona
from ..store import UserStore
from ..timeutil import parse_date, today_local

log = logging.getLogger("stressless.server.session")
DAYS = 70
DEFAULT_PERSONA, DEFAULT_SEED = "alex", 7
REAL_TTL = 60


def real_data() -> bool:
    return os.environ.get("STRESSLESS_DATA", "real").lower() != "demo"


class _LRU:
    def __init__(self, size: int) -> None:
        self.size = size
        self.data: "OrderedDict[Hashable, Any]" = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: Hashable) -> Any:
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key]
        return None

    def put(self, key: Hashable, value: Any) -> None:
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)

    def drop(self, pred) -> None:
        with self.lock:
            for k in [k for k in self.data if pred(k)]:
                del self.data[k]


_datasets = _LRU(6)
_engines = _LRU(32)
_user_locks: Dict[str, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def anchor_override() -> Optional[date]:
    """STRESSLESS_ANCHOR=YYYY-MM-DD freezes "today" for every user (stable demos and screenshots)."""
    raw = os.environ.get("STRESSLESS_ANCHOR")
    return parse_date(raw) if raw else None


def today_for(persona: str) -> date:
    return anchor_override() or today_local(get_persona(persona).tz)


def pristine_dataset(persona: str, seed: int, today: date) -> Dataset:
    key = (persona, seed, today)
    ds = _datasets.get(key)
    if ds is None:
        t0 = time.time()
        ds = generate_dataset(persona, seed=seed, days=DAYS, anchor=today)
        log.info("generated %s (seed %d, %s) in %.2fs", persona, seed, today, time.time() - t0)
        _datasets.put(key, ds)
    return copy.deepcopy(ds)


def _identity(store: UserStore) -> Tuple[str, int, date]:
    """The user's dataset identity; rolls over to a fresh dataset (and clears answers) when the day changes."""
    prof = store.profile()
    persona = prof["persona"] if prof["persona"] in PERSONAS else DEFAULT_PERSONA
    seed = int(prof["seed"])
    today = today_for(persona)
    if prof.get("anchor") != today.isoformat():
        if prof.get("anchor") is not None:
            log.info("dataset was for %s; regenerating for %s", prof.get("anchor"), today)
            store.clear_user_state()
        store.set_profile(persona, seed, today.isoformat())
    return persona, seed, today


def _real_engine_for(user_id: str, store: UserStore) -> Engine:
    today = anchor_override() or today_local(valid_tz(store.time_zone()))
    key = (user_id, "real", today, store.state_version(), int(time.time() // REAL_TTL))
    engine = _engines.get(key)
    if engine is None:
        engine = Engine(load_dataset(store, today), store)
        _engines.drop(lambda k: k[0] == user_id)
        _engines.put(key, engine)
    engine.store = store
    return engine


def _engine_for(user_id: str, store: UserStore) -> Engine:
    if real_data():
        return _real_engine_for(user_id, store)
    persona, seed, today = _identity(store)
    key = (user_id, persona, seed, today, store.state_version())
    engine = _engines.get(key)
    if engine is None:
        engine = Engine(pristine_dataset(persona, seed, today), store)
    engine.store = store
    return engine


def _remember(user_id: str, engine: Engine) -> None:
    """Cache the engine under its current state; drop entries for the user's older states."""
    ds = engine.ds
    key = (user_id, ds.persona.key, ds.seed, ds.today, engine.store.state_version())
    _engines.drop(lambda k: k[0] == user_id and k != key)
    _engines.put(key, engine)


def _user_lock(user_id: str) -> threading.Lock:
    with _user_locks_guard:
        return _user_locks.setdefault(user_id, threading.Lock())


@contextmanager
def engine_session(user_id: str, store: UserStore) -> Iterator[Engine]:
    """The user's engine for the duration of one request; serialized per user because engines are not thread-safe."""
    with _user_lock(user_id):
        engine = _engine_for(user_id, store)
        yield engine
        if not real_data():
            _remember(user_id, engine)


def switch_persona(user_id: str, store: UserStore, persona: str, seed: int) -> None:
    with _user_lock(user_id):
        prof = store.profile()
        today = today_for(persona)
        if (prof["persona"], int(prof["seed"]), prof.get("anchor")) != (persona, int(seed), today.isoformat()):
            store.clear_user_state()                 # a different dataset: answers no longer apply
        store.set_profile(persona, int(seed), today.isoformat())
        _engines.drop(lambda k: k[0] == user_id)


def forget(user_id: str) -> None:
    """Drop the user's cached engines after a write the engine reads (a check-in), so the next request reloads."""
    _engines.drop(lambda k: k[0] == user_id)


def reset(user_id: str, store: UserStore) -> None:
    with _user_lock(user_id):
        store.clear_user_state()
        store.set_profile(DEFAULT_PERSONA, DEFAULT_SEED, today_for(DEFAULT_PERSONA).isoformat())
        _engines.drop(lambda k: k[0] == user_id)
