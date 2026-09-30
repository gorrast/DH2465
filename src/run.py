#!/usr/bin/env python3
"""StressLess — run the local demo. See README.md.

    python3 run.py                 # generate data (first run), start the server, open the browser
    python3 run.py --demo-check    # pre-flight checklist before presenting
    python3 run.py --report today  # print this morning's report in the terminal
"""
import sys

if sys.version_info < (3, 9):
    sys.exit("StressLess needs Python 3.9 or newer. On macOS run `xcode-select --install` or install python.org Python.")

import argparse
import logging
import os
import tempfile
import threading
import webbrowser
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
sys.path.insert(0, str(ROOT))


def _data_dir(arg):
    path = Path(arg) if arg else ROOT / "data"
    try:
        path.mkdir(parents=True, exist_ok=True)
        (path / ".write-test").write_text("ok")
        (path / ".write-test").unlink()
        return str(path)
    except (OSError, PermissionError):
        fallback = Path(tempfile.gettempdir()) / "stressless"
        fallback.mkdir(parents=True, exist_ok=True)
        print("Warning: %s is not writable; using %s" % (path, fallback), file=sys.stderr)
        return str(fallback)


def build_parser():
    p = argparse.ArgumentParser(description="StressLess local demo")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--persona", default="alex", choices=["alex", "sam", "robin"])
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--days", type=int, default=70)
    p.add_argument("--anchor", type=str, default=None, help="freeze 'today' (YYYY-MM-DD)")
    p.add_argument("--regenerate", action="store_true")
    p.add_argument("--no-showcase", action="store_true", help="disable the scripted demo night")
    p.add_argument("--data-dir", type=str, default=None)
    p.add_argument("--report", type=str, default=None, metavar="DATE", help="print the morning report for DATE or 'today'")
    p.add_argument("--json", action="store_true")
    p.add_argument("--demo-check", action="store_true")
    p.add_argument("--import-health", type=str, default=None, metavar="EXPORT_XML")
    p.add_argument("--import-ics", type=str, default=None, metavar="CALENDAR_ICS")
    p.add_argument("--import-timeline", type=str, default=None, metavar="PATH")
    p.add_argument("--persona-name", type=str, default="You")
    p.add_argument("--test", action="store_true")
    p.add_argument("--screenshots", action="store_true")
    p.add_argument("--out", type=str, default=str(ROOT / "docs" / "screenshots"))
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def build_state(args):
    from stressless.server.app import AppState
    anchor = date.fromisoformat(args.anchor) if args.anchor else None
    dataset = None
    if args.import_health or args.import_ics or args.import_timeline:
        dataset = import_dataset(args, anchor)
    return AppState(str(ROOT), _data_dir(args.data_dir), persona=args.persona, seed=args.seed, days=args.days, anchor=anchor,
                    showcase=not args.no_showcase, regenerate=args.regenerate, dataset=dataset)


def import_dataset(args, anchor):
    from stressless.connectors import build_dataset, imported_persona
    from stressless.timeutil import today_local
    today = anchor or today_local()
    start = today.fromordinal(today.toordinal() - args.days)
    persona = imported_persona(args.persona_name)
    events, visits, hr_days, nights, activity = [], [], [], [], []
    if args.import_ics:
        from stressless.connectors.ics_calendar import parse_ics
        with open(args.import_ics, encoding="utf-8", errors="replace") as fh:
            events = parse_ics(fh.read(), persona.tz, start, today.fromordinal(today.toordinal() + 7))
        print("Calendar: %d events" % len(events))
    if args.import_health:
        from stressless.connectors.apple_health import parse_export
        hr_days, nights, activity = parse_export(args.import_health, persona.tz, start, today)
        print("Apple Health: %d days of heart rate, %d nights" % (len(hr_days), sum(1 for n in nights if n.worn)))
    if args.import_timeline:
        from stressless.connectors.google_takeout import parse_timeline
        visits = parse_timeline(args.import_timeline, persona.tz, start, today)
        print("Location history: %d visits" % len(visits))
    return build_dataset(persona, events, visits, hr_days, nights, activity, today, days=args.days)


def cmd_report(state, args):
    from stressless.models import dumps
    engine = state.engine
    d = engine.ds.today if args.report == "today" else date.fromisoformat(args.report)
    report = engine.morning_report(d)
    print(dumps(report, indent=2) if args.json else engine.report_markdown(report))


def cmd_demo_check(state):
    result = state.engine.demo_check()
    print("StressLess pre-flight — %s, %s\n" % (state.engine.ds.persona.name, state.engine.ds.today))
    for c in result["checks"]:
        print("  [%s] %s — %s" % ("ok" if c["ok"] else "FAIL", c["name"], c["detail"]))
    print("\n%s" % ("All checks passed. Ready to present." if result["ok"] else "Some checks failed."))
    return 0 if result["ok"] else 1


def cmd_serve(state, args):
    from stressless.server.app import make_server
    checks = state.run_health_checks()
    failed = [k for k, v in checks.items() if not v]
    print("Health: %s" % ("all %d checks passed" % len(checks) if not failed else "FAILED %s" % ", ".join(failed)))
    server = make_server(state, "127.0.0.1", args.port)
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    ds = state.engine.ds
    print("StressLess — %s (%s), %s to %s, today %s" % (ds.persona.name, ds.persona.tagline, ds.start, ds.end, ds.today))
    print("Reasoning: %s · data dir: %s" % (state.engine.reasoner.mode, state.data_dir))
    print("URL: %s" % url)
    print("Press Ctrl+C to stop.", flush=True)
    state.start_pregeneration()
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.test:
        import unittest
        os.chdir(str(ROOT))
        return 0 if unittest.main(module=None, argv=["", "discover", "-s", "tests", "-t", str(ROOT), "-v"], exit=False).result.wasSuccessful() else 1
    if args.screenshots:
        import subprocess
        return subprocess.call([sys.executable, str(ROOT / "tools" / "screenshot.py"), "--out", args.out, "--anchor", args.anchor or ""])
    state = build_state(args)
    if args.report:
        cmd_report(state, args)
        return 0
    if args.demo_check:
        return cmd_demo_check(state)
    return cmd_serve(state, args)


if __name__ == "__main__":
    sys.exit(main())
