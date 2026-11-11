"""Report generation: inputs from the engine, rule and Claude writers (fake client), and the claim-once flow."""
import json
import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from stressless.engine.pipeline import Engine
from stressless.engine.report_input import daily_input, told_links, weekly_input
from stressless.engine.report_input import OBVIOUS
from stressless.engine.report_writer import ClaudeReportWriter, ReportWriterError, build_request, write_rules
from stressless.reports import CONTENT_MODELS, DailyContent, unknown_evidence
from stressless.server.reports import ReportBusy, current_periods, generate
from stressless.store import MemoryStore
from tests.helpers import ANCHOR, fresh_dataset

MONDAY = ANCHOR - timedelta(days=ANCHOR.weekday() + 7)


class FakeClient:
    """Stands in for anthropic.Anthropic: records requests and answers with a canned parsed report."""

    def __init__(self, stop_reason="end_turn", evidence=None, fail=False):
        """``evidence``: the keys the finding cites; by default the input's first link and the sleep score."""
        self.calls = []
        self.stop_reason, self.evidence, self.fail = stop_reason, evidence, fail
        self.messages = SimpleNamespace(parse=self._parse)
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **req):
        self.calls.append(req)
        if self.fail:
            raise RuntimeError("network down")
        evidence = self.evidence
        if evidence is None:
            sent = json.loads(req["messages"][0]["content"].split("\n\n", 1)[1])
            evidence = [p["key"] for p in sent["patterns"][:1]] + ["sleep.score"]
        fields = dict(headline="A short night", summary="Your score was 64.", fun_fact=None, caveats=[],
                      findings=[{"title": "Late meeting", "body": "Likely a factor.", "tone": "watch", "confidence": "high",
                                 "evidence": evidence}])
        if req["output_format"].__name__ == "DailyContent":
            fields.update(suggestion=None)
        else:
            fields.update(best_day=None, hardest_day=None, next_week="Fewer late meetings.")
        return SimpleNamespace(parsed_output=req["output_format"](**fields), stop_reason=self.stop_reason,
                               model=req["model"], usage=SimpleNamespace(input_tokens=1200, output_tokens=400))


class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = fresh_dataset()
        cls.engine = Engine(cls.ds)

    def test_daily_input_has_metrics_patterns_and_the_whole_calendar(self):
        inp = daily_input(self.engine, ANCHOR)
        self.assertEqual((inp.kind, inp.period_start, inp.period_end), ("daily", ANCHOR, ANCHOR))
        self.assertIn("sleep.score", inp.keys())
        self.assertTrue(inp.patterns)
        self.assertEqual(len(inp.keys()), len(inp.metrics) + len(inp.patterns))     # keys are unique
        self.assertEqual(len(inp.calendar), len(self.ds.events))

    def test_request_sends_every_calendar_event_with_every_field(self):
        for inp in (daily_input(self.engine, ANCHOR), weekly_input(self.engine, MONDAY)):
            sent = json.loads(build_request(inp)["messages"][0]["content"].split("\n\n", 1)[1])
            self.assertEqual(len(sent["calendar"]), len(self.ds.events))
            by_id = {e["id"]: e for e in sent["calendar"]}
            for ev in self.ds.events:
                e = by_id[ev.id]
                self.assertEqual((e["title"], e["type"], e["location_hint"], e["attendees"], e["recurring_key"],
                                  e["source"], e["attended"], e["notes"]),
                                 (ev.title, ev.type, ev.location_hint, ev.attendees, ev.recurring_key, ev.source,
                                  ev.attended, ev.notes))
                self.assertEqual((e["start"], e["end"]), (ev.start.isoformat(), ev.end.isoformat()))

    def test_anonymized_request_hides_titles_places_and_notes(self):
        inp = weekly_input(self.engine, MONDAY)
        with mock.patch.dict(os.environ, {"STRESSLESS_ANONYMIZE_CALENDAR": "true"}):
            body = build_request(inp)["messages"][0]["content"].split("\n\n", 1)[1]
        sent = json.loads(body)
        self.assertEqual(len(sent["calendar"]), len(self.ds.events))
        for e in sent["calendar"]:
            self.assertIsNone(e["location_hint"])
            self.assertIsNone(e["notes"])
            self.assertRegex(e["title"], r"^[A-Z][a-z]+ \d+$")
        for title in {ev.title for ev in self.ds.events if len(ev.title) > 3}:
            self.assertNotIn('"' + title + '"', body)

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
        link = self.inp.patterns[0].key
        written = ClaudeReportWriter(FakeClient(evidence=[link, "sleep.score", "made.up"])).write(self.inp)
        self.assertEqual(written.content.findings[0].evidence, [link, "sleep.score"])
        self.assertEqual(written.usage, {"input_tokens": 1200, "output_tokens": 400})

    def test_a_finding_on_a_metric_alone_is_not_kept(self):
        """The pages show HRV and the sleep score already; a report with only such findings falls back to rules."""
        with self.assertRaises(ReportWriterError):
            ClaudeReportWriter(FakeClient(evidence=["hrv.overnight"])).write(self.inp)

    def test_the_daily_input_is_about_yesterday_and_leaves_out_what_the_page_shows(self):
        self.assertTrue(self.inp.patterns)
        self.assertTrue(all(p.sources and p.happened for p in self.inp.patterns))      # links that happened, only
        self.assertFalse(OBVIOUS & {p.key[len("pattern."):] for p in self.inp.patterns})
        self.assertTrue(all(not f.evidence or f.evidence[0].startswith("pattern.")
                            for f in write_rules(self.inp).content.findings))


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

    def test_the_weekly_report_does_not_repeat_the_daily_one(self):
        """Generated after today's daily report, the weekly one leaves out the links the daily told (and other links
        about the same thing)."""
        today = self.engine.ds.today
        daily = generate(self.engine, self.store, "daily", today, ClaudeReportWriter(FakeClient()))
        told = told_links(daily)
        cited = {k[len("pattern."):] for f in daily.content.findings for k in f.evidence if k.startswith("pattern.")}
        self.assertTrue(cited and cited <= told)
        weekly = generate(self.engine, self.store, "weekly", current_periods(today)["weekly"], ClaudeReportWriter(FakeClient()))
        after = {p.key[len("pattern."):] for p in weekly.input.patterns}
        self.assertTrue(after)                                     # the freed places go to other links
        self.assertFalse(after & cited)

    def test_current_periods(self):
        periods = current_periods(ANCHOR)                         # ANCHOR is a Sunday
        self.assertEqual(periods["daily"], ANCHOR)
        self.assertEqual(periods["weekly"].weekday(), 0)
        self.assertEqual(periods["weekly"] + timedelta(days=13), ANCHOR)


if __name__ == "__main__":
    unittest.main()
