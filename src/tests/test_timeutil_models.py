"""Lead-owned tests for the shared backbone: timeutil and models."""
import json
import unittest
from datetime import date, datetime

from stressless import timeutil as tu
from stressless.models import (CalendarEvent, Dataset, Persona, SleepNight, HeartRateDay,
                               dataset_from_dict, dumps, from_dict, new_id, to_jsonable)


class TimeUtilTests(unittest.TestCase):
    def test_at_and_fractional_hours(self):
        dt = tu.at(date(2026, 9, 26), 20.5)
        self.assertEqual((dt.hour, dt.minute), (20, 30))
        self.assertEqual(str(dt.tzinfo), "Europe/Stockholm")

    def test_night_date_rolls_back_before_noon(self):
        self.assertEqual(tu.night_date(tu.at(date(2026, 9, 27), 0.5)), date(2026, 9, 26))
        self.assertEqual(tu.night_date(tu.at(date(2026, 9, 26), 23)), date(2026, 9, 26))

    def test_parse_dt_handles_zulu_and_naive(self):
        z = tu.parse_dt("2026-09-26T18:30:00Z")
        self.assertEqual((z.hour, z.minute), (20, 30))
        naive = tu.parse_dt("2026-09-26T20:30")
        self.assertEqual(naive.utcoffset().total_seconds(), 7200)

    def test_minute_of_day_and_hours_float(self):
        dt = tu.at(date(2026, 9, 26), 20, 45)
        self.assertEqual(tu.minute_of_day(dt), 20 * 60 + 45)
        self.assertAlmostEqual(tu.hours_float(dt), 20.75)

    def test_overlap_and_ranges(self):
        d = date(2026, 9, 26)
        self.assertEqual(tu.overlap_minutes(tu.at(d, 9), tu.at(d, 10), tu.at(d, 9.5), tu.at(d, 11)), 30)
        self.assertEqual(tu.overlap_minutes(tu.at(d, 9), tu.at(d, 10), tu.at(d, 10), tu.at(d, 11)), 0)
        self.assertEqual(len(tu.day_range(d, date(2026, 9, 30))), 5)
        self.assertEqual(tu.day_range(d, date(2026, 9, 25)), [])

    def test_formatters(self):
        self.assertEqual(tu.fmt_minutes(95), "1 h 35 min")
        self.assertEqual(tu.fmt_minutes(-40), "-40 min")
        self.assertEqual(tu.fmt_minutes(120), "2 h")
        self.assertEqual(tu.fmt_hm(tu.at(date(2026, 9, 26), 7, 5)), "07:05")


class ModelsTests(unittest.TestCase):
    def _dataset(self):
        p = Persona(key="alex", name="Alex", tagline="t", description="d")
        d = date(2026, 9, 26)
        ev = CalendarEvent(id="ev-1", title="Standup", start=tu.at(d, 9), end=tu.at(d, 9.5), type="meeting")
        ev2 = CalendarEvent(id="ev-2", title="Gym", start=tu.at(d, 18), end=tu.at(d, 19), type="workout", attended=False)
        night = SleepNight(date=d, worn=True, in_bed_start=tu.at(d, 23), score=68, score_parts={"duration": 40})
        hr = HeartRateDay(date=d, bpm=[60] * 1000 + [None] * 440)
        return Dataset(persona=p, seed=1, source="demo", start=date(2026, 7, 19), end=d, today=date(2026, 9, 27),
                       events=[ev, ev2], nights=[night], hr_days=[hr])

    def test_roundtrip(self):
        ds = self._dataset()
        ds2 = dataset_from_dict(json.loads(dumps(ds)))
        self.assertEqual(ds2.events[0].start, ds.events[0].start)
        self.assertEqual(ds2.night(date(2026, 9, 26)).score, 68)
        self.assertEqual(ds2.events[1].attended, False)
        self.assertAlmostEqual(ds2.hr(date(2026, 9, 26)).worn_fraction(), 1000 / 1440)

    def test_indexes_exclude_unattended(self):
        ds = self._dataset()
        self.assertEqual([e.id for e in ds.events_on(date(2026, 9, 26))], ["ev-1"])
        self.assertEqual(len(ds.events_on(date(2026, 9, 26), include_unattended=True)), 2)
        ds.set_attended("ev-2", True)
        self.assertEqual(len(ds.events_on(date(2026, 9, 26))), 2)

    def test_add_event_reindexes(self):
        ds = self._dataset()
        d = date(2026, 9, 27)
        ds.add_event(CalendarEvent(id="ev-3", title="Wind down", start=tu.at(d, 21), end=tu.at(d, 22), type="protected"))
        self.assertEqual(ds.event("ev-3").type, "protected")
        self.assertEqual(len(ds.events_on(d)), 1)

    def test_to_jsonable_datetimes(self):
        out = to_jsonable({"when": tu.at(date(2026, 9, 26), 20.5), "d": date(2026, 9, 26)})
        self.assertEqual(out["when"], "2026-09-26T20:30+02:00")
        self.assertEqual(out["d"], "2026-09-26")

    def test_from_dict_ignores_unknown_keys(self):
        ev = from_dict(CalendarEvent, {"id": "x", "title": "t", "start": "2026-09-26T09:00+02:00",
                                       "end": "2026-09-26T10:00+02:00", "type": "meeting", "bogus": 1})
        self.assertEqual(ev.duration_min, 60)

    def test_new_id_is_url_safe(self):
        self.assertEqual(new_id("ev", date(2026, 9, 26), "Weekly sync/2"), "ev-2026-09-26-Weekly_sync_2")

    def test_regressors_keys(self):
        from stressless.models import DayFeatures, REGRESSOR_KEYS
        f = DayFeatures(date=date(2026, 9, 26), n_meetings=6, max_b2b_run=4, late_meeting_hours=2.5, workout_slot="late")
        r = f.regressors()
        self.assertEqual(tuple(r.keys()), REGRESSOR_KEYS)
        self.assertEqual(r["meetings_over_3"], 3.0)
        self.assertEqual(r["b2b_over_2"], 2.0)
        self.assertEqual(r["workout_late"], 1.0)


if __name__ == "__main__":
    unittest.main()
