"""Report schemas: round trip, daily/weekly discrimination, evidence check, structured-output compatibility."""
import json
import unittest
from datetime import date, datetime, timezone

from pydantic import ValidationError

from stressless.store.memory import MemoryStore
from stressless.reports import (DailyContent, Metric, Pattern, Report, ReportInput, WeeklyContent, unknown_evidence)

DAILY = {
    "headline": "A short night after a late meeting",
    "summary": "Your sleep score was 68, 9 below your usual 77.",
    "findings": [{"title": "Late meeting", "body": "It is associated with shorter sleep for you.", "tone": "watch",
                  "confidence": "high", "evidence": ["pattern.late_meeting", "sleep.score"]}],
    "fun_fact": None,
    "suggestion": "Protect 21:00 to 22:00 tonight.",
    "caveats": [],
}
WEEKLY = dict({k: v for k, v in DAILY.items() if k != "suggestion"}, best_day={"day": "2026-10-03", "reason": "A calm day."},
              hardest_day=None, next_week="Keep the morning workouts.")


def report_input(kind="daily"):
    return ReportInput(
        kind=kind, period_start=date(2026, 10, 5), period_end=date(2026, 10, 5), n_nights=40,
        metrics=[Metric(key="sleep.score", label="Sleep score", source="watch", value=68, unit="points", baseline=77, delta=-9, status="watch")],
        patterns=[Pattern(key="pattern.late_meeting", title="Late meetings", detail="6 points lower on 8 nights.", direction="hurt", effect=-6, n=8, confidence="high")])


def report(kind, content):
    return Report(kind=kind, period_start=date(2026, 10, 5), period_end=date(2026, 10, 5),
                  generated_at=datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc), mode="claude", model="claude-haiku-5-5",
                  input=report_input(kind), content=content)


class ReportSchemaTests(unittest.TestCase):
    def test_round_trip_keeps_content_type(self):
        for kind, raw, cls in (("daily", DAILY, DailyContent), ("weekly", WEEKLY, WeeklyContent)):
            back = Report.model_validate_json(report(kind, raw).model_dump_json())
            self.assertIsInstance(back.content, cls)
            self.assertEqual(type(back.content), cls)

    def test_a_stored_weekly_report_with_the_old_fields_still_loads(self):
        old = json.loads(report("weekly", WEEKLY).model_dump_json())
        old["content"].update(trend="A little below your usual week.", suggestion="Protect 21:00 to 22:00.")
        back = Report.model_validate(old)
        self.assertIsInstance(back.content, WeeklyContent)
        self.assertFalse({"trend", "suggestion"} & set(back.content.model_dump()))

    def test_content_must_match_kind(self):
        with self.assertRaises(ValidationError):
            report("weekly", DAILY)
        with self.assertRaises(ValidationError):
            report("daily", WEEKLY)

    def test_unknown_evidence(self):
        content = DailyContent.model_validate(DAILY)
        self.assertEqual(unknown_evidence(content, report_input()), [])
        content.findings[0].evidence.append("made.up")
        self.assertEqual(unknown_evidence(content, report_input()), ["made.up"])

    def test_content_schemas_fit_structured_outputs(self):
        from anthropic import transform_schema
        for cls in (DailyContent, WeeklyContent):
            text = json.dumps(transform_schema(cls))
            self.assertNotIn('"additionalProperties": true', text)
            self.assertNotIn('"additionalProperties": {', text)


class ReportStoreTests(unittest.TestCase):
    def test_a_period_can_be_claimed_once_and_finished_once(self):
        st, day = MemoryStore(), date(2026, 10, 5)
        self.assertIsNone(st.report_row("daily", day))
        self.assertTrue(st.claim_report("daily", day))
        self.assertFalse(st.claim_report("daily", day))
        self.assertEqual(st.report_row("daily", day)["status"], "pending")
        st.save_report(report("daily", DAILY))
        row = st.report_row("daily", day)
        self.assertEqual((row["status"], row["report"].content.headline), ("ready", DAILY["headline"]))
        st.save_report(report("daily", dict(DAILY, headline="Second try")))
        self.assertEqual(st.report_row("daily", day)["report"].content.headline, DAILY["headline"])
        st.clear_user_state()
        self.assertFalse(st.claim_report("daily", day))
        self.assertTrue(st.claim_report("weekly", day))
        self.assertEqual(st.reports_last_day(), 2)


if __name__ == "__main__":
    unittest.main()
