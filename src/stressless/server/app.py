"""Localhost HTTP server, application state, persona switching and background pre-generation (SPEC §8.1)."""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from ..engine.pipeline import Engine
from ..models import Dataset, dataset_from_dict, dumps
from ..sim import PERSONA_ORDER, generate_dataset
from ..store import Store
from ..timeutil import today_local
from . import api

log = logging.getLogger("stressless.server")
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
        ".woff2": "font/woff2", ".map": "application/json"}


class AppState:
    def __init__(self, root: str, data_dir: str, persona: str = "alex", seed: int = 7, days: int = 70,
                 anchor: Optional[date] = None, showcase: bool = True, regenerate: bool = False, dataset: Optional[Dataset] = None) -> None:
        self.root = root
        self.web_root = os.path.realpath(os.path.join(root, "web"))
        self.data_dir = data_dir
        self.seed = seed
        self.days = days
        self.anchor = anchor
        self.showcase = showcase
        self.lock = threading.RLock()
        self.pregen: Dict[str, str] = {}
        self.health: Dict[str, bool] = {}
        os.makedirs(data_dir, exist_ok=True)
        self.store = Store(os.path.join(data_dir, "stressless.db"))
        if dataset is not None:
            ds = dataset
            self.store.save_dataset(ds)
        else:
            ds = None if regenerate else self.store.load_dataset()
            meta = self.store.meta()
            if ds is not None and (meta.get("persona") != persona or meta.get("seed") != str(seed)):
                ds = None
            if ds is not None and anchor is None and ds.today != today_local(ds.persona.tz) and ds.source == "demo":
                log.info("Dataset was for %s; regenerating for %s", ds.today, today_local(ds.persona.tz))
                ds = None
            if ds is None:
                ds = self._generate(persona, seed)
                self.store.save_dataset(ds)
        self.engine = Engine(ds, self.store)

    # ---------------------------------------------------------------- data --
    def _generate(self, persona: str, seed: int) -> Dataset:
        t0 = time.time()
        ds = generate_dataset(persona, seed=seed, days=self.days, anchor=self.anchor, showcase=self.showcase)
        log.info("generated %s (seed %d) in %.2fs", persona, seed, time.time() - t0)
        return ds

    def _pregen_path(self, persona: str, seed: int) -> str:
        anchor = (self.anchor or self.engine.ds.today).isoformat()
        return os.path.join(self.data_dir, "pregen-%s-%d-%s-%d%s.json" % (persona, seed, anchor, self.days, "" if self.showcase else "-plain"))

    def start_pregeneration(self) -> None:
        def work() -> None:
            for key in PERSONA_ORDER:
                if key == self.engine.ds.persona.key:
                    continue
                path = self._pregen_path(key, self.seed)
                try:
                    if not os.path.exists(path):
                        ds = self._generate(key, self.seed)
                        tmp = path + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as fh:
                            fh.write(dumps(ds))
                        os.replace(tmp, path)
                    self.pregen[key] = "ready"
                except Exception as exc:  # pragma: no cover
                    log.warning("pre-generation of %s failed: %s", key, exc)
                    self.pregen[key] = "error"
        for key in PERSONA_ORDER:
            if key != self.engine.ds.persona.key:
                self.pregen[key] = "ready" if os.path.exists(self._pregen_path(key, self.seed)) else "pending"
        threading.Thread(target=work, name="pregen", daemon=True).start()

    def switch(self, persona: str, seed: int) -> None:
        ds = None
        path = self._pregen_path(persona, seed)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    ds = dataset_from_dict(json.load(fh))
            except Exception as exc:
                log.warning("cached dataset unreadable (%s); regenerating", exc)
        if ds is None:
            ds = self._generate(persona, seed)
        engine = Engine(ds, None)
        with self.lock:
            self.seed = seed
            self.store.save_dataset(ds)          # clears user state when identity changes
            engine.store = self.store
            self.store.apply_to(ds)
            engine.invalidate()
            self.engine = engine
        self.start_pregeneration()

    def reset(self) -> None:
        with self.lock:
            self.store.clear()
            for f in os.listdir(self.data_dir):
                if f.startswith("pregen-") and f.endswith(".json"):
                    try:
                        os.remove(os.path.join(self.data_dir, f))
                    except OSError:
                        pass
            ds = self._generate("alex", 7)
            self.seed = 7
            self.store.save_dataset(ds)
            self.engine = Engine(ds, self.store)
        self.start_pregeneration()

    def run_health_checks(self) -> Dict[str, bool]:
        e = self.engine
        checks = {}
        for name, fn in (("report", lambda: e.morning_report(e.ds.today)), ("week", lambda: e.week(e.ds.today)),
                         ("habits", lambda: e.habits(e.ds.today)), ("reality", lambda: e.reality()),
                         ("day", lambda: e.day_bundle(e.ds.end)), ("model", lambda: e.model_summary(e.ds.today))):
            try:
                fn()
                checks[name] = True
            except Exception as exc:  # pragma: no cover
                log.error("health check %s failed: %s", name, exc)
                checks[name] = False
        self.health = checks
        return checks


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "StressLess/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # replaced by our own line in _finish
        pass

    def _send(self, status: int, ctype: str, data: bytes, headers: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _handle(self, method: str) -> None:
        t0 = time.time()
        parts = urlsplit(self.path)
        path = unquote(parts.path)
        query = {k: v[-1] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        status = 500
        try:
            if path.startswith("/api/"):
                body = None
                if method == "POST":
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(length) if length else b""
                    try:
                        body = json.loads(raw.decode("utf-8")) if raw else {}
                    except ValueError:
                        self._send(400, "application/json; charset=utf-8", b'{"error": "body must be JSON"}')
                        status = 400
                        return
                status, ctype, data, headers = api.dispatch(self.server.state, method, path, query, body)
                self._send(status, ctype, data, headers)
            elif method in ("GET", "HEAD"):
                status = self._static(path)
            else:
                self._send(405, "application/json; charset=utf-8", b'{"error": "method not allowed"}')
                status = 405
        finally:
            sys.stderr.write("%s %s %d %dms\n" % (method, path, status, int((time.time() - t0) * 1000)))

    def _static(self, path: str) -> int:
        web_root = self.server.state.web_root
        rel = path.lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(web_root, rel))
        if not full.startswith(web_root + os.sep) and full != web_root:
            self._send(403, "text/plain; charset=utf-8", b"forbidden")
            return 403
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return 404
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as fh:
            data = fh.read()
        self._send(200, MIME.get(ext, "application/octet-stream"), data)
        return 200

    def do_GET(self) -> None:
        self._handle("GET")

    def do_HEAD(self) -> None:
        self._handle("HEAD")

    def do_POST(self) -> None:
        self._handle("POST")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, state: AppState) -> None:
        super().__init__(addr, handler)
        self.state = state


def make_server(state: AppState, host: str = "127.0.0.1", port: int = 8765) -> Server:
    if port == 0:
        return Server((host, 0), Handler, state)
    last: Optional[Exception] = None
    for p in range(port, port + 21):
        try:
            return Server((host, p), Handler, state)
        except OSError as exc:
            last = exc
            if exc.errno not in (48, 98, 10048):
                raise
    raise RuntimeError("no free port in %d..%d (%s)" % (port, port + 20, last))
