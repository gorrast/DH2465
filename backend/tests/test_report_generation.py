"""Report generation: inputs from the engine, rule and Claude writers (fake client), and the claim-once flow."""
import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from stressless.engine.pipeline import Engine
from stressless.engine.report_input import daily_input, weekly_input
from stressless.engine.report_writer import ClaudeReportWriter, build_request, write_rules
from stressless.reports import CONTENT_MODELS, DailyContent, unknown_evidence
from stressless.server.reports import ReportBusy, current_periods, generate
from stressless.store import MemoryStore
from tests.helpers import ANCHOR, fresh_dataset

MONDAY = ANCHOR - timedelta(days=ANCHOR.weekday() + 7)


class FakeClient:
    """Stands in for anthropic.Anthropic: records requests and answers with a canned parsed report."""

    def __init__(self, stop_reason="end_turn", evidence=("sleep.score",), fail=False):
        self.calls = []
        self.stop_reason, self.evidence, self.fail = stop_reason, list(evidence), fail
        self.messages = SimpleNamespace(parse=self._parse)
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **req):
        self.calls.append(req)
        if self.fail:
            raise RuntimeError("network down")
        fields = dict(headline="A short night", summary="Your score was 64.", fun_fact=None, suggestion=None, caveats=[],
                      findings=[{"title": "Late meeting", "body": "Likely a factor.", "tone": "watch", "confidence": "high",
                                 "evidence": self.evidence}])
        if req["output_format"].__name__ == "WeeklyContent":
            fields.update(trend="Below usual.", best_day=None, hardest_day=None, next_week="Fewer late meetings.")
        return SimpleNamespace(parsed_output=req["output_format"](**fields), stop_reason=self.stop_reason,
                               model=req["model"], usage=SimpleNamespace(input_tokens=1200, output_tokens=400))


class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = fresh_dataset()
        cls.engine = Engine(cls.ds)

    def test_daily_input_has_metrics_patterns_and_no_event_names(self):
        """No event titles, except those of recurring series that became a link (an agreed exception)."""
        inp = daily_input(self.engine, ANCHOR)
        self.assertEqual((inp.kind, inp.period_start, inp.period_end), ("daily", ANCHOR, ANCHOR))
        self.assertIn("sleep.score", inp.keys())
        self.assertTrue(inp.patterns)
        self.assertEqual(len(inp.keys()), len(inp.metrics) + len(inp.patterns))     # keys are unique
        text = inp.model_dump_json()
        night = ANCHOR - timedelta(days=1)
        series = {p.title[len("Days with "):] for p in inp.patterns if p.key.startswith("pattern.series_")}
        for ev in self.ds.events_on(night, include_unattended=True) + self.ds.events_on(ANCHOR, include_unattended=True):
            if not (ev.recurring_key and ev.title in series):
                self.assertNotIn(ev.title, text)

    def test_weekly_input_covers_monday_to_sunday(self):
        inp = weekly_input(self.engine, MONDAY)
        self.assertEqual([d.day for d in inp.days], [MONDAY + timedelta(days=k) for k in range(7)])
        self.assertEqual(inp.period_end, MONDAY + timedelta(days=6))
        self.assertIn("sleep.score", inp.keys())

    def test_rule_writer_fits_the_schema_and_cites_known_keys(self):
        for inp in (daily_input(self.engine, ANCHOR), weekly_input(self.engine, MONDAY)):
            content = write_rules(inp).content
            self.assertIsInstance(content, CONTENT_MODELS[inp.kind])
            self.assertEqual(unknown_evidence(content, inp), [])
            self.assertTrue(content.findings)


class WriterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inp = daily_input(Engine(fresh_dataset()), ANCHOR)

    def test_request_uses_structured_output_and_per_kind_models(self):
        req = build_request(self.inp)
        self.assertIs(req["output_format"], DailyContent)
        self.assertEqual((req["model"], req["fallbacks"]), ("claude-sonnet-5-5", "default"))
        weekly = build_request(weekly_input(Engine(fresh_dataset()), MONDAY))
        self.assertEqual((weekly["model"], weekly["fallbacks"]), ("claude-sonnet-5-5", "default"))
        with mock.patch.dict(os.environ, {"STRESSLESS_DAILY_MODEL": "claude-haiku-5-5"}):
            req = build_request(self.inp)
            self.assertEqual(req["model"], "claude-haiku-5-5")
            self.assertNotIn("fallbacks", req)

    def test_unknown_evidence_is_dropped(self):
        written = ClaudeReportWriter(FakeClient(evidence=["sleep.score", "made.up"])).write(self.inp)
        self.assertEqual(written.content.findings[0].evidence, ["sleep.score"])
        self.assertEqual(written.usage, {"input_tokens": 1200, "output_tokens": 400})


@mock.patch.dict(os.environ, {"STRESSLESS_REASONER": "claude"})
class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(fresh_dataset())
        self.store = MemoryStore()

    def test_generates_once_then_returns_the_stored_report(self):
        client = FakeClient()
        first = generate(self.engine, self.store, "daily", ANCHOR, ClaudeReportWriter(client))
        again = generate(self.engine, self.store, "daily", ANCHOR, ClaudeReportWriter(client))
        self.assertEqual((first.mode, first.model, len(client.calls)), ("claude", "claude-sonnet-5-5", 1))
        self.assertEqual(again.content.headline, first.content.headline)
        self.assertEqual(self.store.report_row("daily", ANCHOR)["status"], "ready")

    def test_falls_back_to_rules(self):
        cases = {"refusal": FakeClient(stop_reason="refusal"), "error": FakeClient(fail=True),
                 "cut off": FakeClient(stop_reason="max_tokens")}
        for i, (name, client) in enumerate(cases.items()):
            report = generate(self.engine, self.store, "daily", ANCHOR - timedelta(days=i), ClaudeReportWriter(client))
            self.assertEqual(report.mode, "rules", name)

    def test_cap_and_consent_skip_the_model(self):
        client = FakeClient()
        with mock.patch.dict(os.environ, {"STRESSLESS_REPORT_DAILY_CAP": "0"}):
            self.assertEqual(generate(self.engine, self.store, "daily", ANCHOR, ClaudeReportWriter(client)).mode, "rules")
        self.engine.ds.source = "imported"                       # real data needs consent
        self.assertEqual(generate(self.engine, self.store, "weekly", MONDAY, ClaudeReportWriter(client)).mode, "rules")
        self.store.consented_at = "2026-10-15T08:00:00+00:00"
        report = generate(self.engine, self.store, "daily", ANCHOR - timedelta(days=1), ClaudeReportWriter(client))
        self.assertEqual(report.mode, "claude")
        self.assertEqual(len(client.calls), 1)

    def test_pending_claim_blocks_until_stale_then_finishes_with_rules(self):
        client = FakeClient()
        self.store.claim_report("daily", ANCHOR)
        with self.assertRaises(ReportBusy):
            generate(self.engine, self.store, "daily", ANCHOR, ClaudeReportWriter(client))
        self.store._reports[("daily", ANCHOR)]["created_at"] = "2026-01-01T00:00:00+00:00"
        report = generate(self.engine, self.store, "daily", ANCHOR, ClaudeReportWriter(client))
        self.assertEqual((report.mode, len(client.calls)), ("rules", 0))

    def test_current_periods(self):
        periods = current_periods(ANCHOR)                         # ANCHOR is a Sunday
        self.assertEqual(periods["daily"], ANCHOR)
        self.assertEqual(periods["weekly"].weekday(), 0)
        self.assertEqual(periods["weekly"] + timedelta(days=13), ANCHOR)


if __name__ == "__main__":
    unittest.main()
