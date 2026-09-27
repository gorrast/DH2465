"""Simulator tests: determinism, ranges, showcase guarantees, truth bookkeeping (SPEC §10)."""
import json
import statistics
import unittest
from datetime import timedelta

from stressless.engine.features import day_features
from stressless.models import dumps
from stressless.sim import PERSONA_ORDER, generate_dataset
from stressless.sim.physiology import CALENDAR_KEYS, poisson_invcdf
from stressless.sim.sleep_score import compute_score, rating
from tests.helpers import ANCHOR, dataset


class SleepScoreTests(unittest.TestCase):
    def test_bounds_and_parts(self):
        s, parts = compute_score({"duration_min": 480, "bedtime_min": 665, "interruptions": 0, "awake_min": 0, "sleep_need_min": 480}, [665] * 5)
        self.assertEqual(s, 100)
        self.assertEqual(set(parts), {"duration", "consistency", "interruptions"})
        s2, _ = compute_score({"duration_min": 200, "bedtime_min": 800, "interruptions": 6, "awake_min": 90, "sleep_need_min": 480}, [665] * 5)
        self.assertTrue(0 <= s2 < s)

    def test_consistency_is_asymmetric(self):
        late, _ = compute_score({"duration_min": 420, "bedtime_min": 725, "interruptions": 1, "awake_min": 10, "sleep_need_min": 480}, [665] * 5)
        early, _ = compute_score({"duration_min": 420, "bedtime_min": 605, "interruptions": 1, "awake_min": 10, "sleep_need_min": 480}, [665] * 5)
        self.assertGreater(early, late)

    def test_rating_bands(self):
        self.assertEqual(rating(40), "Very low"); self.assertEqual(rating(61), "OK"); self.assertEqual(rating(96), "Very high"); self.assertEqual(rating(None), "No data")

    def test_poisson_monotone_in_lambda(self):
        for u in (0.1, 0.5, 0.9):
            self.assertLessEqual(poisson_invcdf(0.5, u), poisson_invcdf(2.0, u))


class DatasetTests(unittest.TestCase):
    def test_deterministic(self):
        a = generate_dataset("alex", seed=3, anchor=ANCHOR, days=30)
        b = generate_dataset("alex", seed=3, anchor=ANCHOR, days=30)
        a.generated_at = b.generated_at = None
        self.assertEqual(dumps(a), dumps(b))

    def test_ranges_and_shapes(self):
        for key in PERSONA_ORDER:
            ds = dataset(key)
            self.assertEqual((ds.end - ds.start).days + 1, 70)
            self.assertEqual(len(ds.nights), 70)
            self.assertEqual(len(ds.hr_days), 71)                       # start..today
            for hr in ds.hr_days:
                self.assertEqual(len(hr.bpm), 1440)
                vals = [b for b in hr.bpm if b is not None]
                self.assertTrue(all(38 <= v <= 195 for v in vals), key)
            scores = [n.score for n in ds.nights if n.worn]
            self.assertTrue(all(0 <= s <= 100 for s in scores))
            self.assertTrue(74 <= statistics.median(scores) <= 88, "%s median %s" % (key, statistics.median(scores)))
            self.assertTrue(6 <= statistics.pstdev(scores) <= 14.5, "%s sd %.1f" % (key, statistics.pstdev(scores)))
            self.assertTrue(all(e.attended is None for e in ds.events), "attended must stay None")
            ids = [e.id for e in ds.events] + [v.id for v in ds.visits]
            self.assertEqual(len(ids), len(set(ids)), "duplicate ids")
            self.assertTrue(all(n.duration_min >= 180 for n in ds.nights if n.worn))

    def test_showcase_guarantees(self):
        for key in PERSONA_ORDER:
            for seed in (1, 2, 3, 4, 5):
                ds = generate_dataset(key, seed=seed, anchor=ANCHOR)
                last7 = [ds.night(ds.end - timedelta(days=k)) for k in range(7)]
                self.assertTrue(all(n.worn for n in last7), "%s seed %d: unworn night in the last 7" % (key, seed))
                hr = ds.hr(ds.end)
                self.assertTrue(all(b is not None for b in hr.bpm[22 * 60:]), "charging gap on hero night")
                truth = ds.truth.nights[-1]
                self.assertGreaterEqual(sum(1 for k in CALENDAR_KEYS if truth.regressors.get(k)), 3, "%s seed %d: hero day has too few factors" % (key, seed))
                today_meetings = [e for e in ds.events_on(ds.today) if e.type == "meeting"]
                self.assertTrue(any((e.end.hour + e.end.minute / 60.0) >= 19.5 for e in today_meetings), "%s seed %d: no late meeting today" % (key, seed))
                skipped = ds.truth.hidden_summary.get("skipped_gym_day")
                unbooked = ds.truth.hidden_summary.get("unbooked_gym_day")
                self.assertTrue(skipped and unbooked, "%s seed %d: showcase reality checks missing" % (key, seed))
                illness = ds.truth.hidden_summary["illness_nights"]
                self.assertEqual(illness, [(ds.end - timedelta(days=k)).isoformat() for k in (12, 11, 10)])
                counts = {k: sum(1 for tn in ds.truth.nights if tn.regressors.get(k)) for k in CALENDAR_KEYS}
                self.assertTrue(all(v >= 5 for v in counts.values()), "%s seed %d coverage %s" % (key, seed, counts))

    def test_truth_contributions_single_factor(self):
        ds = dataset("alex")
        found = 0
        for tn in ds.truth.nights:
            active = [k for k in CALENDAR_KEYS if tn.regressors.get(k)]
            if len(active) == 1 and tn.counterfactual_score is not None:
                night = ds.night(tn.date)
                if night.worn:
                    self.assertAlmostEqual(tn.contributions[active[0]], night.score - tn.counterfactual_score, places=6)
                    found += 1
        self.assertGreater(found, 0)

    def test_realised_signs_match_design(self):
        for key in PERSONA_ORDER:
            ds = dataset(key)
            for k, design in ds.truth.effect_table_design.items():
                direct = ds.truth.effect_table_direct.get(k)
                n_active = sum(1 for tn in ds.truth.nights if tn.regressors.get(k))
                if design != 0 and direct is not None and n_active >= 8:
                    self.assertEqual(direct > 0, design > 0, "%s %s realised %.1f vs design %.1f" % (key, k, direct, design))

    def test_features_shared_with_engine(self):
        ds = dataset("alex")
        att = {t.event_id: t.attended for t in ds.truth.events}
        for tn in ds.truth.nights[-5:]:
            events = [e for e in ds.events_on(tn.date, include_unattended=True) if att.get(e.id, True)]
            self.assertEqual(day_features(ds, tn.date, events=events).regressors(), tn.regressors)


if __name__ == "__main__":
    unittest.main()
