"""Lifestyle patterns: planted relationships are found, nothing after ``upto`` is used, and they reach the report input."""
import unittest
from datetime import timedelta

from stressless.engine.lifestyle import active_on, lifestyle_patterns
from stressless.engine.pipeline import Engine
from stressless.engine.report_input import daily_input, weekly_input
from stressless.engine.report_writer import write_rules
from stressless.reports import unknown_evidence
from tests.helpers import ANCHOR, fresh_dataset

NIGHT = ANCHOR - timedelta(days=1)
MONDAY = ANCHOR - timedelta(days=ANCHOR.weekday() + 7)


def planted():
    """Demo data where every third day has few steps and a lot of late phone use, and the night after is worse."""
    ds = fresh_dataset()
    for a in ds.activity:
        a.steps = 3000 if a.date.toordinal() % 3 == 0 else 11000 + 37 * (a.date.toordinal() % 7)
    for d in ds.night_dates():
        ds.day_metrics[d] = {"screen.minutes": 200.0, "screen.pickups": 60.0,
                             "screen.late_minutes": 70.0 if d.toordinal() % 3 == 0 else 5.0 + d.toordinal() % 4}
        n = ds.night(d)
        if n.worn and n.score is not None and d.toordinal() % 3 == 0:
            n.score -= 12
            n.duration_min -= 45
    # Make sure yesterday is one of the planted days, so the daily report has a pattern to apply.
    ds.activity_on(NIGHT).steps = 3000
    ds.day_metrics[NIGHT]["screen.late_minutes"] = 70.0
    return ds


class LifestyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = planted()
        cls.patterns = {p.key: p for p in lifestyle_patterns(cls.ds, ANCHOR)}

    def test_planted_low_steps_hurt_sleep(self):
        p = self.patterns["low_steps"]
        self.assertEqual(p.direction, "hurt")
        keys = {o.key for o in p.reportable}
        self.assertIn("score", keys)
        self.assertIn("duration_min", keys)
        self.assertLess(next(o for o in p.outcomes if o.key == "duration_min").effect, -20)
        self.assertIn("steps", p.description)
        self.assertIn("less sleep", p.detail())

    def test_threshold_is_personal(self):
        p = self.patterns["low_steps"]
        self.assertGreaterEqual(p.threshold, 3000)
        self.assertLess(p.threshold, 11000)
        self.assertTrue(active_on(self.ds, p, NIGHT))

    def test_screen_time_from_daily_metrics(self):
        p = self.patterns["late_screen"]
        self.assertEqual(p.direction, "hurt")
        # No screen data, no screen patterns.
        bare = lifestyle_patterns(fresh_dataset(), ANCHOR)
        self.assertFalse({"late_screen", "heavy_screen", "many_pickups"} & {p.key for p in bare})

    def test_nothing_from_upto_onwards_is_used(self):
        upto = ANCHOR - timedelta(days=10)
        before = [(p.key, p.threshold, [(o.key, o.effect, o.n_with) for o in p.outcomes]) for p in lifestyle_patterns(self.ds, upto)]
        ds = planted()
        for d in ds.night_dates():
            if d >= upto:
                n = ds.night(d)
                if n.worn and n.score is not None:
                    n.score, n.duration_min = 10, 100
                ds.activity_on(d).steps = 25000
                ds.day_metrics[d]["screen.late_minutes"] = 300.0
        after = [(p.key, p.threshold, [(o.key, o.effect, o.n_with) for o in p.outcomes]) for p in lifestyle_patterns(ds, upto)]
        self.assertEqual(before, after)

    def test_patterns_reach_the_report_input(self):
        engine = Engine(self.ds)
        daily = daily_input(engine, ANCHOR)
        keys = {p.key for p in daily.patterns}
        self.assertIn("pattern.low_steps", keys)
        p = next(p for p in daily.patterns if p.key == "pattern.low_steps")
        self.assertEqual(p.direction, "hurt")
        self.assertIsNotNone(p.outcome)
        self.assertLessEqual(p.effect_low, p.effect)
        self.assertGreaterEqual(p.effect_high, p.effect)
        self.assertIn("screen.late_minutes", daily.keys())
        self.assertEqual(len(daily.keys()), len(daily.metrics) + len(daily.patterns))

        weekly = weekly_input(engine, MONDAY)
        self.assertTrue({"pattern.low_steps", "pattern.late_screen"} & {p.key for p in weekly.patterns})
        self.assertIn("screen.minutes", weekly.keys())
        self.assertTrue(any("low-step day" in t for d in weekly.days for t in d.tags))
        for inp in (daily, weekly):
            self.assertEqual(unknown_evidence(write_rules(inp).content, inp), [])


    def test_alcohol_check_ins_become_a_pattern_even_from_few_evenings(self):
        ds = fresh_dataset()
        nights = [d for d in ds.night_dates() if ds.night(d).worn and ds.night(d).score is not None][-30:]
        for i, d in enumerate(nights):
            drinks = i % 5 == 0                                       # 6 evenings with alcohol out of 30 logged
            ds.day_metrics[d] = {"intake.alcohol_units": 3.0 if drinks else 0.0, "intake.coffee_cups": 2.0}
            if drinks:
                n = ds.night(d)
                n.hrv_ms *= 0.8
                n.resting_hr += 4
        p = {p.key: p for p in lifestyle_patterns(ds, ANCHOR)}["alcohol"]
        self.assertEqual(p.description, "evenings with alcohol")
        self.assertEqual(p.direction, "hurt")
        self.assertIn(p.primary.key, ("hrv_ms", "resting_hr"))
        self.assertIn("evenings with alcohol", p.detail())
        # Coffee never varied, so there is nothing to compare.
        self.assertNotIn("more_coffee", {q.key for q in lifestyle_patterns(ds, ANCHOR)})

    def test_weak_signal_is_a_hint_with_low_confidence(self):
        from stressless.engine.lifestyle import LifestylePattern, OutcomeEffect
        o = OutcomeEffect(key="score", label="Sleep score", unit="points", good="up", n_with=5, n_without=20, mean_with=78,
                          mean_without=81, effect=-3.0, ci_low=-7.0, ci_high=0.5, confidence="low", tier="hint", strength=0.1)
        p = LifestylePattern(key="alcohol", title="Evenings with alcohol", description="evenings with alcohol", threshold=1,
                             n_with=5, n_without=20, outcomes=[o])
        self.assertTrue(p.hint)
        self.assertEqual((p.confidence, p.direction), ("low", "hurt"))
        self.assertIn("early hint", p.detail())


if __name__ == "__main__":
    unittest.main()
