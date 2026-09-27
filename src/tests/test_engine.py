"""Engine unit tests on synthetic data: features, baselines, matching, reality, attribution, habits, what-if."""
import math
import random
import unittest
from datetime import date, timedelta

from stressless import timeutil as tu
from stressless.engine import attribution as A
from stressless.engine import baselines as bl
from stressless.engine.features import day_features
from stressless.engine.habits import rank_habits
from stressless.engine.matching import hr_norm_curve, rolling_mean, workout_signature
from stressless.engine.reality import reality_checks
from stressless.engine.suggestions import to_ics
from stressless.engine.whatif import apply_modifications, predict_day
from stressless.models import (CalendarEvent, Dataset, HeartRateDay, LocationVisit, Persona, SleepNight)
from stressless.connectors.ics_calendar import parse_ics
from tests.helpers import ANCHOR

D = date(2026, 9, 25)  # a Friday
P = Persona(key="t", name="T", tagline="", description="", usual_bedtime=23.0, usual_wake=7.0)


def ev(i, title, s, e, typ, d=D, **kw):
    return CalendarEvent(id="e%d" % i, title=title, start=tu.at(d, s), end=tu.at(d, e), type=typ, **kw)


def visit(i, ptype, s, e, d=D, name=None):
    return LocationVisit(id="v%d" % i, place_type=ptype, place_name=name or ptype, start=tu.at(d, s), end=tu.at(d, e))


def hr_day(d, base=62, spikes=()):
    bpm = [base + ((m * 7) % 5) for m in range(1440)]
    for s, e, level in spikes:
        for m in range(int(s * 60), int(e * 60)):
            bpm[m] = level
    return HeartRateDay(date=d, bpm=bpm)


def night(d, score, bed=23.0, dur=430, hrv=50.0, rhr=56, worn=True):
    if not worn:
        return SleepNight(date=d, worn=False)
    return SleepNight(date=d, worn=True, in_bed_start=tu.at(d, bed), sleep_onset=tu.at(d, bed) + timedelta(minutes=15),
                      wake_time=tu.at(d, bed) + timedelta(minutes=dur + 40), duration_min=dur, interruptions=1, awake_min=12,
                      hrv_ms=hrv, resting_hr=rhr, resp_rate=14.5, wrist_temp_dev=0.0, spo2=97.0, score=score, score_parts={})


class FeatureTests(unittest.TestCase):
    def test_spec_rules(self):
        evs = [ev(1, "Run", 7, 7.75, "workout"), ev(2, "Standup", 9, 9.5, "meeting"), ev(3, "A", 13, 14, "meeting"), ev(4, "B", 14, 15, "meeting"),
               ev(5, "C", 15.1, 16, "meeting"), ev(6, "D", 16.1, 17, "meeting"), ev(7, "Late", 19, 20.5, "meeting"), ev(8, "Dinner", 21, 24.5, "social"),
               ev(9, "Flight", 5.5, 8, "travel", notes="tz_shift=+1")]
        f = day_features(None, D, events=evs)
        self.assertEqual(f.early_start, 1)                 # the 05:30 flight, not the run
        self.assertEqual(f.max_b2b_run, 4)
        self.assertAlmostEqual(f.last_meeting_end_hour, 20.5)
        self.assertAlmostEqual(f.late_meeting_hours, 2.5)
        self.assertEqual(f.evening_social, 1)
        self.assertAlmostEqual(f.social_end_hour, 24.5)
        self.assertEqual(f.workout_slot, "morning")
        self.assertEqual(f.tz_shift_hours, 1.0)
        self.assertEqual(f.is_weekend, 1)                  # Friday night
        self.assertEqual(day_features(None, date(2026, 9, 27), events=[]).is_weekend, 0)  # Sunday night

    def test_run_alone_is_not_early_start_and_bedtime_relative_late(self):
        f = day_features(None, D, events=[ev(1, "Run", 7, 7.75, "workout")])
        self.assertEqual(f.early_start, 0)
        ds = Dataset(persona=Persona(key="r", name="R", tagline="", description="", usual_bedtime=0.25), seed=0, source="demo", start=D, end=D, today=D)
        self.assertEqual(day_features(ds, D, events=[ev(1, "Gym", 20.75, 21.75, "workout")]).workout_slot, "late")
        self.assertEqual(day_features(None, D, events=[ev(1, "Gym", 18.0, 19.0, "workout")]).workout_slot, "evening")

    def test_protected_by_title(self):
        self.assertEqual(day_features(None, D, events=[ev(1, "Wind down", 21, 22, "personal")]).protected_evening, 1)


class BaselineTests(unittest.TestCase):
    def test_robust_baseline_and_z(self):
        med, scale = bl.robust_baseline([70, 72, 74, 76, 78, 100])
        self.assertAlmostEqual(med, 75)
        self.assertGreater(scale, 0)
        self.assertEqual(bl.robust_baseline([1, 2]), (None, None))
        self.assertIsNone(bl.z(None, {"median": 1, "scale": 1}))
        self.assertAlmostEqual(bl.z(80, {"median": 75, "scale": 5}), 1.0)

    def test_bedtime_minutes_unit(self):
        n = night(D, 80, bed=23.25)
        self.assertAlmostEqual(bl.night_metric(n, "bedtime_min"), 675)


class MatchingTests(unittest.TestCase):
    def test_rolling_mean_ignores_none(self):
        self.assertEqual(rolling_mean([1, None, 3], 3), [1.0, 2.0, 3.0])

    def test_norm_and_workout_signature(self):
        days = [D - timedelta(days=k) for k in range(1, 15)]
        ds = Dataset(persona=P, seed=0, source="demo", start=days[-1], end=D, today=D + timedelta(days=1), hr_days=[hr_day(d) for d in days] + [hr_day(D, spikes=[(18, 19, 140)])])
        norm = hr_norm_curve(ds, D)
        self.assertEqual(len(norm), 1440)
        self.assertTrue(all(v is not None for v in norm))
        sig = workout_signature(ds, tu.at(D, 18), tu.at(D, 19))
        self.assertEqual(sig["minutes_over_120"], 60)


class RealityTests(unittest.TestCase):
    def _ds(self, events, visits, hr):
        return Dataset(persona=P, seed=0, source="demo", start=D - timedelta(days=1), end=D, today=D + timedelta(days=1), events=events, visits=visits, hr_days=[hr])

    def test_skipped_gym_is_contradicted(self):
        ds = self._ds([ev(1, "Gym", 18, 19, "workout", location_hint="SATS")], [visit(1, "home", 0, 24)], hr_day(D))
        checks = reality_checks(ds, D, D, {})
        self.assertEqual([c.kind for c in checks], ["booked_not_seen"])
        self.assertIn("gym", checks[0].question)

    def test_attended_gym_confirmed_by_hr(self):
        ds = self._ds([ev(1, "Gym", 18, 19, "workout")], [visit(1, "home", 0, 24)], hr_day(D, spikes=[(18, 19, 140)]))
        self.assertEqual(reality_checks(ds, D, D, {}), [])

    def test_wfh_meeting_never_asks(self):
        ds = self._ds([ev(1, "Standup", 9, 10, "meeting", location_hint="Office")], [visit(1, "home", 0, 24)], hr_day(D))
        self.assertEqual(reality_checks(ds, D, D, {}), [])

    def test_unbooked_gym_and_lunch(self):
        ds = self._ds([], [visit(1, "home", 0, 12), visit(2, "restaurant", 12, 13), visit(3, "home", 13, 18), visit(4, "gym", 18, 19.1, name="SATS Odenplan"), visit(5, "home", 19.1, 24)], hr_day(D, spikes=[(18, 19, 138)]))
        checks = reality_checks(ds, D, D, {})
        self.assertEqual([c.kind for c in checks], ["seen_not_booked"])
        self.assertEqual(checks[0].suggested_event.type, "workout")
        self.assertTrue(checks[0].suggested_event.id.startswith("ev-detected-"))

    def test_answers_applied_and_persist(self):
        ds = self._ds([ev(1, "Gym", 18, 19, "workout")], [visit(1, "home", 0, 24)], hr_day(D))
        cid = reality_checks(ds, D, D, {})[0].id
        ds.set_attended("e1", False)
        checks = reality_checks(ds, D, D, {cid: {"answer": "no", "ts": "2026-09-26T08:00:00+02:00"}})
        self.assertEqual(checks[0].status, "no")
        self.assertIsNotNone(checks[0].answered_at)


def synthetic_dataset(n=200, seed=1, sd=3.0, coefs=None):
    rng = random.Random(seed)
    coefs = coefs or {"meetings_over_3": -2.0, "late_meeting_hours": -4.0, "evening_social": -8.0, "workout_morning": 5.0, "travel": -9.0}
    start = date(2026, 1, 5)
    events, nights = [], []
    for i in range(n):
        d = start + timedelta(days=i)
        evs = []
        nm = rng.choice([1, 2, 4, 5, 6, 7])
        for k in range(nm):
            evs.append(ev(len(events) + len(evs) + 1, "M", 9 + k, 9.75 + k, "meeting", d=d))
        late = rng.random() < 0.3
        if late:
            evs.append(ev(len(events) + len(evs) + 1, "Late", 19, 20.5, "meeting", d=d))
        soc = rng.random() < 0.25
        if soc:
            evs.append(ev(len(events) + len(evs) + 1, "Dinner", 19, 22.5, "social", d=d))
        wm = rng.random() < 0.3
        if wm:
            evs.append(ev(len(events) + len(evs) + 1, "Run", 7, 7.75, "workout", d=d))
        trv = rng.random() < 0.1
        if trv:
            evs.append(ev(len(events) + len(evs) + 1, "Flight", 10, 12, "travel", d=d))
        events += evs
        reg = day_features(None, d, events=evs).regressors()
        y = 85 + sum(coefs.get(k, 0.0) * v for k, v in reg.items()) + rng.gauss(0, sd)
        nights.append(night(d, max(0, min(100, round(y)))))
    return Dataset(persona=P, seed=seed, source="demo", start=start, end=start + timedelta(days=n - 1), today=start + timedelta(days=n), events=events, nights=nights), coefs


class AttributionTests(unittest.TestCase):
    def test_recovers_known_coefficients(self):
        ds, coefs = synthetic_dataset()
        fit = A.fit(ds, ds.today, bootstrap=100)
        for k, v in coefs.items():
            tol = 0.6 if fit.n_active[k] >= 60 else 1.5     # rare factors (travel ~10 %) are estimated from few nights
            self.assertLess(abs(fit.coef[k] - v), tol, "%s: %.2f vs %.2f (n_active %d)" % (k, fit.coef[k], v, fit.n_active[k]))
            ci = fit.ci[k]
            self.assertTrue(ci[0] - 0.5 <= v <= ci[1] + 0.5, "%s interval %s misses %s" % (k, ci, v))
        self.assertGreater(fit.r2_loo, 0.7)
        self.assertLessEqual(fit.r2_loo, fit.r2 + 1e-9)

    def test_loo_lambda_grows_with_noise(self):
        quiet, _ = synthetic_dataset(n=60, sd=1.0)
        noisy, _ = synthetic_dataset(n=60, sd=15.0, seed=2)
        self.assertLessEqual(A.fit(quiet, quiet.today, bootstrap=0).ridge_lambda, A.fit(noisy, noisy.today, bootstrap=0).ridge_lambda)

    def test_insufficient_history(self):
        ds, _ = synthetic_dataset(n=8)
        fit = A.fit(ds, ds.today)
        self.assertTrue(fit.insufficient)
        self.assertTrue(all(v == 0.0 for v in fit.coef.values()))

    def test_active_only_causes_and_intervals(self):
        ds, _ = synthetic_dataset()
        fit = A.fit(ds, ds.today, bootstrap=100)
        norm = [70.0] * 1440
        seen = 0
        for k in range(1, 40):
            morning = ds.today - timedelta(days=k)
            reg = day_features(ds, morning - timedelta(days=1)).regressors()
            causes, helpers, prox, meta = A.explain_night(ds, morning, fit, norm)
            for c in causes + helpers:
                self.assertNotEqual(reg[c.factor], 0.0, "%s listed while inactive" % c.factor)
                self.assertNotEqual(c.factor, "is_weekend")
                if c.points_low is not None:
                    self.assertLessEqual(c.points_low, c.points_high)
            seen += len(causes)
            self.assertIn(meta["unexplained_note"], (None, meta["unexplained_note"]))
        self.assertGreater(seen, 0)

    def test_summary_and_predict_interval(self):
        ds, _ = synthetic_dataset(n=80)
        fit = A.fit(ds, ds.today, bootstrap=100)
        s = A.summary(fit)
        self.assertEqual(len(s.coefficients), 10)
        self.assertIsNotNone(s.r2_loo)
        before = {k: 0.0 for k in fit.keys}
        after = dict(before); after["late_meeting_hours"] = 2.0
        lo, hi = A.predict_interval(fit, before, after)
        self.assertLess(lo, 0); self.assertLessEqual(lo, hi)

    def test_spearman(self):
        self.assertAlmostEqual(A.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(A.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)
        self.assertIsNone(A.spearman([1, 2], [1, 2]))


class HabitsTests(unittest.TestCase):
    def test_stratified_effect_removes_weekend_confound(self):
        # weekend nights score +15; a "habit" that only happens on weekends should show ~0 stratified effect
        start = date(2026, 1, 5)
        events, nights = [], []
        rng = random.Random(3)
        for i in range(84):
            d = start + timedelta(days=i)
            weekend = tu.is_weekend_night(d)
            if weekend and rng.random() < 0.7:
                events.append(ev(i, "Dinner", 19, 22.5, "social", d=d))
            nights.append(night(d, 75 + (15 if weekend else 0) + rng.gauss(0, 2)))
        ds = Dataset(persona=P, seed=0, source="demo", start=start, end=start + timedelta(days=83), today=start + timedelta(days=84), events=events, nights=nights)
        habits = {h.key: h for h in rank_habits(ds, ds.today, bootstrap=200)}
        soc = habits["evening_social"]
        self.assertGreater(abs(soc.raw_effect), 5)
        self.assertLess(abs(soc.effect), 3, "stratified effect should be near zero, got %s" % soc.effect)


class WhatIfTests(unittest.TestCase):
    def test_modifications_and_prediction(self):
        ds, coefs = synthetic_dataset(n=120)
        fit = A.fit(ds, ds.today, bootstrap=100)
        d = ds.end
        late = next(e for e in ds.events_on(d) if e.type == "meeting" and e.end.hour >= 19) if any(e.type == "meeting" and e.end.hour >= 19 for e in ds.events_on(d)) else None
        if late is None:
            ds.add_event(ev(9999, "Late", 19, 20.5, "meeting", d=d)); late = ds.event("e9999")
        res = predict_day(ds, d, [{"op": "end_at", "event_id": late.id, "hour": 18.0}], fit)
        self.assertGreater(res.delta, 0)
        self.assertLessEqual(res.delta_low, res.delta_high)
        self.assertIn("late_meeting_hours", res.changed_factors)
        with self.assertRaises(ValueError):
            apply_modifications(ds.events_on(d), [{"op": "remove", "event_id": "nope"}], d, P.tz)
        added = apply_modifications([], [{"op": "add", "event": {"title": "X", "start": tu.at(d, 21).isoformat(), "end": tu.at(d, 22).isoformat(), "type": "protected"}}], d, P.tz)
        self.assertEqual(added[0].type, "protected")


class IcsRoundTripTests(unittest.TestCase):
    def test_to_ics_parses_back(self):
        e = ev(1, "Wind down (StressLess)", 21, 22, "protected")
        text = to_ics(e)
        self.assertIn("\r\n", text)
        self.assertTrue(all(len(l.encode("utf-8")) <= 75 for l in text.split("\r\n")))
        parsed = parse_ics(text, "Europe/Stockholm", D - timedelta(days=1), D + timedelta(days=1))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].start.astimezone(e.start.tzinfo), e.start)
        self.assertEqual(parsed[0].end.astimezone(e.end.tzinfo), e.end)


if __name__ == "__main__":
    unittest.main()
