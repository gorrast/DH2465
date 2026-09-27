"""End-to-end acceptance: generate -> Engine -> report, for every persona (SPEC §10)."""
import json
import time
import unittest

from stressless.models import dumps
from tests.helpers import ANCHOR

try:
    from stressless.sim import generate_dataset, PERSONA_ORDER
    from stressless.engine.pipeline import Engine
    HAS_STACK = True
except Exception:  # pragma: no cover - only before integration
    HAS_STACK = False


def _fail_on_constant(s):
    raise ValueError("non-finite JSON constant: %s" % s)


@unittest.skipUnless(HAS_STACK, "simulator/engine not available yet")
class EndToEndTests(unittest.TestCase):
    def test_every_persona_generates_and_explains_today(self):
        for persona in PERSONA_ORDER:
            t0 = time.time()
            ds = generate_dataset(persona, seed=7, anchor=ANCHOR)
            gen_s = time.time() - t0
            self.assertLess(gen_s, 6.0, "%s generation took %.1fs" % (persona, gen_s))
            self.assertEqual(ds.today, ANCHOR)
            engine = Engine(ds)
            t1 = time.time()
            report = engine.morning_report(ANCHOR)
            rep_s = time.time() - t1
            self.assertLess(rep_s, 3.0, "%s first report took %.1fs" % (persona, rep_s))
            self.assertIsNotNone(report.score, persona)
            self.assertGreaterEqual(len(report.causes), 3, persona)
            self.assertNotEqual(report.causes[0].confidence, "low", persona)
            self.assertTrue(any(s.kind == "protect_evening" for s in report.suggestions), persona)
            md = engine.report_markdown(report)
            self.assertIn("likely cause", md.lower())
            body = dumps(report, allow_nan=False)
            json.loads(body, parse_constant=_fail_on_constant)

    def test_demo_check_passes_for_every_persona(self):
        for persona in PERSONA_ORDER:
            ds = generate_dataset(persona, seed=7, anchor=ANCHOR)
            result = Engine(ds).demo_check()
            failing = [c["name"] for c in result["checks"] if not c["ok"]]
            self.assertTrue(result["ok"], "%s failed demo checks: %s" % (persona, failing))

    def test_causes_only_list_active_factors(self):
        ds = generate_dataset("alex", seed=7, anchor=ANCHOR)
        engine = Engine(ds)
        from stressless.engine.features import day_features
        for offset in range(1, 15):
            morning = ANCHOR.fromordinal(ANCHOR.toordinal() - offset)
            report = engine.morning_report(morning)
            if report.score is None:
                continue
            reg = day_features(ds, report.night_date).regressors()
            for cause in report.causes + report.helpers:
                self.assertNotEqual(reg.get(cause.factor, 0.0), 0.0,
                                    "%s listed on %s although inactive" % (cause.factor, morning))


if __name__ == "__main__":
    unittest.main()
