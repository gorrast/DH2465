"""Lifestyle patterns: planted relationships are found, nothing after ``upto`` is used, and they reach the report input."""
import unittest
from datetime import timedelta

from datetime import datetime

from stressless.connectors.base import classify_event
from stressless.engine.lifestyle import active_on, daytime_hr, focus_hr, lifestyle_patterns
from stressless.models import CalendarEvent, MediaPlay, WatchWorkout
from stressless.timeutil import tz
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

    def test_links_against_sleep_research_are_flagged_and_their_hints_dropped(self):
        ds = planted()
        for d in ds.night_dates():                                # flip it: late phone evenings go with better nights
            n = ds.night(d)
            if n.worn and n.score is not None and d.toordinal() % 3 == 0:
                n.score += 24
                n.duration_min += 90
        p = {p.key: p for p in lifestyle_patterns(ds, ANCHOR)}["late_screen"]
        self.assertEqual(p.direction, "helped")
        self.assertTrue(p.against_research)
        self.assertFalse(self.patterns["late_screen"].against_research)
        links = {q.key: q for q in daily_input(Engine(ds), ANCHOR).patterns}
        if p.hint:
            self.assertNotIn("pattern.late_screen", links)
        else:
            self.assertTrue(links["pattern.late_screen"].against_research)

    def test_no_calendar_no_meeting_counts(self):
        ds = fresh_dataset()
        ds.events = ds.events[:1]                                 # one stray event is not a connected calendar
        ds.reindex()
        inp = daily_input(Engine(ds), ANCHOR)
        self.assertNotIn("calendar.meetings", inp.keys())
        self.assertNotIn("calm day", inp.days[0].tags)
        self.assertNotIn("calendar.meetings", weekly_input(Engine(ds), MONDAY).keys())

    def test_weak_signal_is_a_hint_with_low_confidence(self):
        from stressless.engine.lifestyle import LifestylePattern, OutcomeEffect
        o = OutcomeEffect(key="score", label="Sleep score", unit="points", good="up", n_with=5, n_without=20, mean_with=78,
                          mean_without=81, effect=-3.0, ci_low=-7.0, ci_high=0.5, confidence="low", tier="hint", strength=0.1)
        p = LifestylePattern(key="alcohol", title="Evenings with alcohol", description="evenings with alcohol", threshold=1,
                             n_with=5, n_without=20, outcomes=[o])
        self.assertTrue(p.hint)
        self.assertEqual((p.confidence, p.direction), ("low", "hurt"))
        self.assertIn("early hint", p.detail())



def with_music_and_workouts():
    """Demo data with planted cross-source links:
    * days with Metallica (every 4th): 30 min less sleep and a daytime heart rate 6 bpm higher;
    * gym days (every 5th): a sleep score 15 points lower; run days (every 5th, offset): 15 points higher."""
    ds = fresh_dataset()
    z = tz(ds.persona.tz)
    for a in ds.activity:                     # only the planted workouts below
        a.workouts = []
    ds.events = [e for e in ds.events if e.type != "workout"]
    for d in ds.night_dates():
        o = d.toordinal()
        artist = "Metallica" if o % 4 == 0 else "Bon Iver"
        ds.media.append(MediaPlay(start=datetime(d.year, d.month, d.day, 17, tzinfo=z), minutes=40, title="Track",
                                  creator=artist, kind="music"))
        kind = "strength" if o % 5 == 0 else ("run" if o % 5 == 2 else None)
        a = ds.activity_on(d)
        if kind and a is not None:
            a.workouts.append(WatchWorkout(id="w%d" % o, kind=kind, start=datetime(d.year, d.month, d.day, 7, tzinfo=z),
                                           end=datetime(d.year, d.month, d.day, 8, tzinfo=z), avg_hr=140, max_hr=170))
        n = ds.night(d)
        if n.worn and n.score is not None:
            if artist == "Metallica":
                n.duration_min -= 30
            n.score += -15 if kind == "strength" else (15 if kind == "run" else 0)
        h = ds.hr(d)
        if h is not None and artist == "Metallica":
            h.bpm = [None if b is None else b + 6 for b in h.bpm]
    ds.reindex()
    return ds


class CrossSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = with_music_and_workouts()
        cls.patterns = {p.key: p for p in lifestyle_patterns(cls.ds, ANCHOR)}

    def test_an_artist_becomes_a_link_with_sleep_and_daytime_heart_rate(self):
        p = self.patterns["artist_metallica"]
        self.assertEqual(p.description, "days you listened to Metallica")
        self.assertEqual(p.sources[0], "music")
        self.assertTrue(p.cross_source)
        effects = {o.key: o for o in p.reportable}
        self.assertLess(effects["duration_min"].effect, -15)
        self.assertGreater(effects["day_hr"].effect, 3)
        self.assertIn("daytime heart rate", p.detail())
        self.assertIn("during those days", p.detail())

    def test_gym_and_runs_are_told_apart(self):
        gym, cardio = self.patterns["gym_days"], self.patterns["cardio_days"]
        self.assertEqual((gym.direction, cardio.direction), ("hurt", "helped"))
        self.assertEqual(gym.sources[0], "exercise")

    def test_daytime_heart_rate_leaves_out_workouts(self):
        d = next(d for d in self.ds.night_dates() if self.ds.activity_on(d) and self.ds.activity_on(d).workouts
                 and self.ds.hr(d) and d.toordinal() % 4 != 0)
        h = self.ds.hr(d)
        h.bpm = [None if b is None else 60 for b in h.bpm]
        for m in range(7 * 60, 8 * 60):
            h.bpm[m] = 180
        try:
            self.assertEqual(daytime_hr(self.ds, d), 60)
        finally:
            self.ds.reindex()

    def test_links_reach_the_report_input_with_sources_and_days(self):
        engine = Engine(self.ds)
        daily = daily_input(engine, ANCHOR)
        links = [p for p in daily.patterns if p.sources]
        self.assertTrue(links)
        self.assertTrue(all(p.happened is not None for p in links))
        self.assertIn("pattern.artist_metallica", {p.key for p in links})
        self.assertEqual(daily.days[0].day, NIGHT)
        self.assertTrue(any("of music, mostly" in t for t in daily.days[0].tags))
        weekly = weekly_input(engine, MONDAY)
        self.assertTrue(any(p.happened for p in weekly.patterns))
        self.assertEqual(len(weekly.keys()), len(weekly.metrics) + len(weekly.patterns))

    def test_no_media_no_music_links(self):
        keys = {p.key for p in lifestyle_patterns(fresh_dataset(), ANCHOR)}
        self.assertFalse({k for k in keys if k.startswith("artist_") or k in ("big_listening", "late_listening")})



def with_classes_and_study_music():
    """Demo data with a recurring class and study music:
    * 'Statistics lecture' every 4th day (a recurring series): daytime heart rate 6 bpm higher, sleep score 12 lower;
    * a study block every other day; on every second one Ludovico Einaudi plays through it, with 40 fewer phone
      pickups and a heart rate 12 bpm lower while studying (clear of the simulator's day-to-day swing)."""
    ds = fresh_dataset()
    z = tz(ds.persona.tz)
    for d in ds.night_dates():
        o = d.toordinal()
        at = lambda h: datetime(d.year, d.month, d.day, h, tzinfo=z)  # noqa: E731
        h, n = ds.hr(d), ds.night(d)
        ds.day_metrics.setdefault(d, {}).update({"screen.minutes": 200.0, "screen.pickups": 70.0})
        if o % 4 == 0:
            ds.events.append(CalendarEvent(id="stats-%d" % o, title="Statistics lecture", start=at(9), end=at(11),
                                           type="meeting", recurring_key="stats"))
            if h is not None:
                h.bpm = [b if b is None or not (9 * 60 <= m < 22 * 60) else b + 6 for m, b in enumerate(h.bpm)]
            if n.worn and n.score is not None:
                n.score -= 12
        if o % 2 == 1:
            ds.events.append(CalendarEvent(id="study-%d" % o, title="Study session", start=at(14), end=at(16), type="focus"))
            if o % 4 == 1:
                for k in range(24):
                    ds.media.append(MediaPlay(start=at(14) + timedelta(minutes=5 * k), minutes=5, title="Track",
                                              creator="Ludovico Einaudi", kind="music"))
                ds.day_metrics[d]["screen.pickups"] = 30.0
                if h is not None:
                    h.bpm = [b if b is None or not (14 * 60 <= m < 16 * 60) else b - 12 for m, b in enumerate(h.bpm)]
    ds.reindex()
    return ds


class SeriesAndFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = with_classes_and_study_music()
        cls.patterns = {p.key: p for p in lifestyle_patterns(cls.ds, ANCHOR)}

    def test_a_recurring_class_becomes_a_link_named_after_it(self):
        p = self.patterns["series_statistics_lecture"]
        self.assertEqual(p.direction, "hurt")
        self.assertEqual(p.sources[0], "calendar")
        effects = {o.key: o for o in p.reportable}
        self.assertGreater(effects["day_hr"].effect, 3)
        self.assertLess(effects["score"].effect, -5)
        self.assertIn("days with Statistics lecture", p.detail())

    def test_study_music_is_compared_on_study_days_only(self):
        p = self.patterns["focus_music_ludovico_einaudi"]
        self.assertEqual(p.direction, "helped")
        self.assertEqual(p.sources[0], "music")
        effects = {o.key: o for o in p.reportable}
        self.assertLess(effects["pickups"].effect, -20)
        self.assertLess(effects["focus_hr"].effect, -3)
        focus_days = {e.start.date() for e in self.ds.events if e.type == "focus" and e.start.date() < ANCHOR}
        self.assertLessEqual(p.n_with + p.n_without, len(focus_days))
        self.assertIn("heart rate during focus time", p.detail())

    def test_focus_heart_rate_needs_focus_time(self):
        d = next(d for d in self.ds.night_dates() if self.ds.hr(d) and not any(
            e.type == "focus" for e in self.ds.events_on(d)))
        self.assertIsNone(focus_hr(self.ds, d))

    def test_study_blocks_count_as_focus_time(self):
        for title in ("Study session", "Studying for the exam", "Plugga statistik", "Exam prep"):
            self.assertEqual(classify_event(title), "focus", title)


if __name__ == "__main__":
    unittest.main()
