"""Try the report generation without the web app or the database.

    uv run python tools/report_try.py daily                      # demo input + rule report (free)
    uv run python tools/report_try.py weekly --save /tmp/w.json  # keep the input for later runs
    uv run python tools/report_try.py daily --call               # real call with the configured daily model
    uv run python tools/report_try.py weekly --input /tmp/w.json --call --model claude-haiku-5-5

--call spends real money (a few tenths of a cent to a few cents) and needs ANTHROPIC_API_KEY. Inputs are built from
the simulated demo data; pass --input to use a saved ReportInput instead, for example one built from real data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from stressless.engine.pipeline import Engine  # noqa: E402
from stressless.engine.report_input import daily_input, weekly_input  # noqa: E402
from stressless.engine.report_writer import ClaudeReportWriter, build_request, model_for, write_rules  # noqa: E402
from stressless.reports import ReportInput  # noqa: E402
from stressless.sim import generate_dataset  # noqa: E402

PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}  # $/MTok


def build_input(kind: str, args) -> ReportInput:
    if args.input:
        with open(args.input, encoding="utf-8") as fh:
            return ReportInput.model_validate_json(fh.read())
    today = date.fromisoformat(args.date) if args.date else date.today()
    engine = Engine(generate_dataset(args.persona, seed=args.seed, days=70, anchor=today))
    if kind == "daily":
        return daily_input(engine, today)
    return weekly_input(engine, today - timedelta(days=today.weekday() + 7))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=("daily", "weekly"))
    ap.add_argument("--date", help="the morning to report on (default today)")
    ap.add_argument("--persona", default="alex", choices=("alex", "sam", "robin"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--input", help="a saved ReportInput JSON file instead of demo data")
    ap.add_argument("--save", help="write the input to this file")
    ap.add_argument("--call", action="store_true", help="call the model (costs money)")
    ap.add_argument("--model", help="override the model for this run")
    args = ap.parse_args()

    inp = build_input(args.kind, args)
    if args.input and inp.kind != args.kind:
        ap.error("%s is a %s input" % (args.input, inp.kind))
    if args.save:
        with open(args.save, "w", encoding="utf-8") as fh:
            fh.write(inp.model_dump_json(indent=2))
    print("== input (%d characters) ==" % len(inp.model_dump_json()))
    print(inp.model_dump_json(indent=2))

    if not args.call:
        print("\n== rule report (free; add --call for the model) ==")
        print(write_rules(inp).content.model_dump_json(indent=2))
        req = build_request(inp, args.model)
        print("\nWould call %s, effort %s." % (req["model"], req["output_config"]["effort"]))
        return

    written = ClaudeReportWriter().write(inp, args.model)
    print("\n== %s report ==" % written.model)
    print(written.content.model_dump_json(indent=2))
    u = written.usage or {}
    model = args.model or model_for(inp.kind)
    price = PRICES.get(model)
    cost = (u.get("input_tokens", 0) * price[0] + u.get("output_tokens", 0) * price[1]) / 1e6 if price else None
    print("\nTokens: %s%s" % (json.dumps(u), " · about $%.4f" % cost if cost is not None else ""))


if __name__ == "__main__":
    main()
