#!/usr/bin/env python3
"""Render every StressLess view with headless Chrome and fail on client-side errors.

Usage: python3 tools/screenshot.py [--url http://127.0.0.1:8765] [--out docs/screenshots] [--anchor 2026-09-27] [--mock]
Starts its own server on a free port when --url is not given.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def views(today):
    yesterday = __import__("datetime").date.fromisoformat(today) - __import__("datetime").timedelta(days=1)
    return [("morning", "#/morning/%s" % today), ("morning-reveal", "#/morning/%s?reveal=1" % today), ("replay", "#/replay/%s?t=1020" % yesterday.isoformat()),
            ("week", "#/week"), ("habits", "#/habits"), ("reality", "#/reality"), ("planner", "#/planner/%s" % today), ("data", "#/data"), ("lab", "#/lab")]


def render(url, png, dom, theme=None):
    full = url + ("&" if "?" in url.split("#")[0] else "?") if False else url
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--enable-logging=stderr", "--v=0",
           "--virtual-time-budget=7000", "--window-size=1440,1000", "--screenshot=%s" % png, url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    console = [l for l in r.stderr.splitlines() if "CONSOLE" in l and ("error" in l.lower() or "Uncaught" in l)]
    d = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=7000", "--window-size=1440,1000", "--dump-dom", url], capture_output=True, text=True, timeout=120)
    Path(dom).write_text(d.stdout)
    bad = "sl-error-entry" in d.stdout or 'class="card error-card"' in d.stdout
    return console, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--anchor", default="")
    ap.add_argument("--theme", default=None)
    args = ap.parse_args()
    if not os.path.exists(CHROME):
        sys.exit("Google Chrome not found at %s" % CHROME)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    server = None
    url = args.url
    if url is None:
        from datetime import date
        from stressless.server.app import AppState, make_server
        state = AppState(str(ROOT), tempfile.mkdtemp(prefix="sl-shots-"), anchor=date.fromisoformat(args.anchor) if args.anchor else None)
        server = make_server(state, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/" % server.server_address[1]
        today = state.engine.ds.today.isoformat()
    else:
        import json, urllib.request
        today = json.loads(urllib.request.urlopen(url.rstrip("/") + "/api/meta").read())["today"]
    failures = 0
    rows = []
    for name, hash_ in views(today):
        target = url.rstrip("/") + "/index.html" + ("?theme=%s" % args.theme if args.theme else "") + hash_
        png = str(out / ("%s.png" % name)); dom = str(out / ("%s.dom.html" % name))
        console, bad = render(target, png, dom, args.theme)
        ok = not console and not bad
        failures += 0 if ok else 1
        rows.append((name, "ok" if ok else "FAIL", len(console), "dom-error" if bad else ""))
        print("%-16s %-5s console-errors=%d %s" % rows[-1])
        for c in console[:3]:
            print("    " + re.sub(r".*CONSOLE", "CONSOLE", c)[:200])
    if server is not None:
        server.shutdown()
    print("\n%d/%d views clean -> %s" % (len(rows) - failures, len(rows), out))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
