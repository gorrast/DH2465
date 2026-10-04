"""Connectors (ICS, Apple Health, Takeout) and the per-user store."""
import copy
import json
import os
import tempfile
import unittest
from datetime import date

from stressless.connectors.apple_health import parse_export
from stressless.connectors.base import classify_event, classify_place, parse_ts
from stressless.connectors.build import build_dataset, imported_persona
from stressless.connectors.google_takeout import parse_timeline
from stressless.connectors.ics_calendar import parse_ics
from stressless.models import CalendarEvent
from stressless.store import MemoryStore
from stressless import timeutil as tu
from tests.helpers import ANCHOR, dataset

ICS = "\r\n".join([
    "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:abc", "DTSTART;TZID=Europe/Stockholm:20260907T090000", "DTEND;TZID=Europe/Stockholm:20260907T093000",
    "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20260930T220000Z", "EXDATE;TZID=Europe/Stockholm:20260914T090000,20260921T090000", "SUMMARY:Weekly standup", "LOCATION:Room Björk",
    "ATTENDEE:mailto:a@x", "ATTENDEE:mailto:b@x", "END:VEVENT",
    "BEGIN:VEVENT", "UID:abc", "RECURRENCE-ID;TZID=Europe/Stockholm:20260916T090000", "DTSTART;TZID=Europe/Stockholm:20260916T100000", "DURATION:PT45M", "SUMMARY:Weekly standup (moved)", "END:VEVENT",
    "BEGIN:VEVENT", "UID:gym1", "DTSTART:20260910T160000Z", "DTEND:20260910T170000Z", "SUMMARY:Gym", "END:VEVENT",
    "BEGIN:VEVENT", "UID:allday", "DTSTART;VALUE=DATE:20260911", "SUMMARY:Holiday", "END:VEVENT",
    "BEGIN:VEVENT", "UID:c", "STATUS:CANCELLED", "DTSTART:20260912T100000Z", "DTEND:20260912T110000Z", "SUMMARY:Cancelled thing", "END:VEVENT",
    "BEGIN:VEVENT", "UID:win", "DTSTART;TZID=W. Europe Standard Time:20260913T180000", "DTEND;TZID=W. Europe Standard Time:20260913T210000", "SUMMARY:Dinner with", " Sara", "END:VEVENT",
    "END:VCALENDAR", ""])

APPLE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [<!ELEMENT HealthData (Record*)>]>
<HealthData locale="en_SE">
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" unit="count/min" startDate="2026-09-20 08:00:10 +0200" endDate="2026-09-20 08:00:10 +0200" value="62"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" unit="count/min" startDate="2026-09-20 08:00:40 +0200" endDate="2026-09-20 08:00:40 +0200" value="66"/>
 <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" sourceName="Watch" unit="ms" startDate="2026-09-21 03:00:00 +0200" endDate="2026-09-21 03:05:00 +0200" value="48.5"/>
 <Record type="HKQuantityTypeIdentifierRestingHeartRate" sourceName="Watch" unit="count/min" startDate="2026-09-21 06:00:00 +0200" endDate="2026-09-21 06:00:00 +0200" value="55"/>
 <Record type="HKQuantityTypeIdentifierOxygenSaturation" sourceName="Watch" unit="%" startDate="2026-09-21 02:00:00 +0200" endDate="2026-09-21 02:00:00 +0200" value="0.97"/>
 <Record type="HKQuantityTypeIdentifierRespiratoryRate" sourceName="Watch" unit="count/min" startDate="2026-09-21 02:00:00 +0200" endDate="2026-09-21 02:00:00 +0200" value="14.2"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Phone" unit="count" startDate="2026-09-20 12:00:00 +0200" endDate="2026-09-20 12:10:00 +0200" value="850"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Nima's iPhone" value="HKCategoryValueSleepAnalysisInBed" startDate="2026-09-20 23:00:00 +0200" endDate="2026-09-21 07:00:00 +0200"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Nima's Apple Watch" value="HKCategoryValueSleepAnalysisInBed" startDate="2026-09-20 23:05:00 +0200" endDate="2026-09-21 06:55:00 +0200"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Nima's Apple Watch" value="HKCategoryValueSleepAnalysisAsleepCore" startDate="2026-09-20 23:20:00 +0200" endDate="2026-09-21 01:20:00 +0200"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Nima's Apple Watch" value="HKCategoryValueSleepAnalysisAsleepDeep" startDate="2026-09-21 01:20:00 +0200" endDate="2026-09-21 02:20:00 +0200"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Nima's Apple Watch" value="HKCategoryValueSleepAnalysisAwake" startDate="2026-09-21 02:20:00 +0200" endDate="2026-09-21 02:30:00 +0200"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Nima's Apple Watch" value="HKCategoryValueSleepAnalysisAsleepREM" startDate="2026-09-21 02:30:00 +0200" endDate="2026-09-21 06:50:00 +0200"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="45" durationUnit="min" totalEnergyBurned="410" startDate="2026-09-20 07:00:00 +0200" endDate="2026-09-20 07:45:00 +0200" sourceName="Watch"/>
</HealthData>
"""

TAKEOUT_SLH = {"timelineObjects": [
    {"placeVisit": {"location": {"latitudeE7": 593421000, "longitudeE7": 180498000, "name": "Home", "semanticType": "TYPE_HOME"}, "duration": {"startTimestamp": "2026-09-20T00:00:00Z", "endTimestamp": "2026-09-20T06:30:00Z"}}},
    {"activitySegment": {"activityType": "IN_PASSENGER_VEHICLE", "duration": {"startTimestampMs": str(int(__import__("datetime").datetime(2026, 9, 20, 7, 0, tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)), "endTimestampMs": str(int(__import__("datetime").datetime(2026, 9, 20, 7, 30, tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000))}}},
    {"placeVisit": {"location": {"latitudeE7": 593428000, "longitudeE7": 180498000, "name": "SATS Odenplan"}, "duration": {"startTimestamp": "2026-09-20T16:00:00.123Z", "endTimestamp": "2026-09-20T17:05:00Z"}}},
]}
TAKEOUT_NEW = {"semanticSegments": [
    {"startTime": "2026-09-21T18:00:00.000+02:00", "endTime": "2026-09-21T20:30:00.000+02:00", "visit": {"topCandidate": {"placeLocation": {"latLng": "59.3355°, 18.0740°", "name": "Restaurang Prinsen"}, "semanticType": "UNKNOWN"}}},
    {"startTime": "2026-09-21T20:30:00.000+02:00", "endTime": "2026-09-21T21:00:00.000+02:00", "activity": {"topCandidate": {"type": "WALKING"}}},
]}


class BaseTests(unittest.TestCase):
    def test_parse_ts_forms(self):
        self.assertEqual(parse_ts("2024-03-01 07:12:33 +0100").isoformat(), "2024-03-01T07:12:33+01:00")
        self.assertEqual(parse_ts("2026-09-26T18:30:00Z").hour, 20)
        self.assertEqual(parse_ts("2026-09-26T18:30:00.1234567+02:00").microsecond, 123456)
        self.assertEqual(parse_ts("1700000000").year, 2023)

    def test_classifiers(self):
        self.assertEqual(classify_event("Gym", None), "workout"); self.assertEqual(classify_event("Dinner with Sara", "Tranan"), "social")
        self.assertEqual(classify_event("Flight ARN->BER", None), "travel"); self.assertEqual(classify_event("Roadmap review", "Room 4"), "meeting")
        self.assertEqual(classify_place("SATS Odenplan"), "gym"); self.assertEqual(classify_place("Home", "TYPE_HOME"), "home"); self.assertEqual(classify_place("Restaurang Prinsen"), "restaurant")


class IcsTests(unittest.TestCase):
    def test_rrule_exdate_override_duration(self):
        evs = parse_ics(ICS, "Europe/Stockholm", date(2026, 9, 1), date(2026, 9, 30))
        titles = [(e.start.strftime("%d %H:%M"), e.title) for e in evs]
        self.assertIn(("07 09:00", "Weekly standup"), titles)
        self.assertNotIn(("14 09:00", "Weekly standup"), titles)                # EXDATE
        self.assertNotIn(("21 09:00", "Weekly standup"), titles)                # EXDATE list
        self.assertIn(("16 10:00", "Weekly standup (moved)"), titles)           # RECURRENCE-ID override
        moved = next(e for e in evs if e.title.endswith("(moved)"))
        self.assertEqual(moved.duration_min, 45)                                 # DURATION on the override
        self.assertTrue(all(not e.title.startswith("Holiday") for e in evs))     # all-day skipped
        self.assertTrue(all("Cancelled" not in e.title for e in evs))
        dinner = next(e for e in evs if e.title.startswith("Dinner"))
        self.assertEqual(dinner.type, "social"); self.assertEqual(dinner.title, "Dinner withSara")
        gym = next(e for e in evs if e.title == "Gym")
        self.assertEqual((gym.start.hour, gym.type, gym.attendees), (18, "workout", 0))
        self.assertEqual(next(e for e in evs if e.title == "Weekly standup").attendees, 2)
        self.assertEqual(len({e.id for e in evs}), len(evs))


class AppleHealthTests(unittest.TestCase):
    def test_parse_export(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
            fh.write(APPLE); path = fh.name
        try:
            hr, nights, activity = parse_export(path, "Europe/Stockholm", date(2026, 9, 18), date(2026, 9, 22))
        finally:
            os.unlink(path)
        self.assertEqual(hr[0].date, date(2026, 9, 20)); self.assertEqual(hr[0].bpm[8 * 60], 64)
        n = next(x for x in nights if x.date == date(2026, 9, 20))
        self.assertTrue(n.worn); self.assertEqual(n.in_bed_start.hour, 23); self.assertEqual(n.in_bed_start.minute, 5)  # watch source preferred
        self.assertEqual(n.deep_min, 60); self.assertEqual(n.interruptions, 1); self.assertAlmostEqual(n.hrv_ms, 48.5); self.assertEqual(n.resting_hr, 55)
        self.assertAlmostEqual(n.spo2, 97.0); self.assertIsNotNone(n.score)
        act = next(a for a in activity if a.date == date(2026, 9, 20))
        self.assertEqual(act.steps, 850); self.assertEqual(act.workouts[0].kind, "run")


class TakeoutTests(unittest.TestCase):
    def test_both_formats(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "2026_SEPTEMBER.json"), "w") as fh:
            json.dump(TAKEOUT_SLH, fh)
        with open(os.path.join(tmp, "Timeline.json"), "w") as fh:
            json.dump(TAKEOUT_NEW, fh)
        visits = parse_timeline(tmp, "Europe/Stockholm", date(2026, 9, 19), date(2026, 9, 22))
        types = [(v.start.date().isoformat(), v.place_type) for v in visits]
        self.assertIn(("2026-09-20", "home"), types); self.assertIn(("2026-09-20", "gym"), types); self.assertIn(("2026-09-20", "transit"), types)
        self.assertIn(("2026-09-21", "restaurant"), types); self.assertIn(("2026-09-21", "transit"), types)
        gym = next(v for v in visits if v.place_type == "gym"); self.assertAlmostEqual(gym.lat, 59.3428, places=3)


class BuildTests(unittest.TestCase):
    def test_build_dataset_fills_nights(self):
        ds = build_dataset(imported_persona("Nima"), [], [], [], [], [], date(2026, 9, 27), days=10)
        self.assertEqual(len(ds.nights), 10); self.assertTrue(all(not n.worn for n in ds.nights)); self.assertEqual(ds.source, "imported")


class StoreTests(unittest.TestCase):
    def test_user_state_replay_and_version(self):
        ds = dataset("alex")
        st = MemoryStore()
        self.assertEqual(st.profile(), {"persona": "alex", "seed": 7, "anchor": None})
        st.set_profile("sam", 3, "2026-09-27"); self.assertEqual(st.profile()["persona"], "sam")
        ev = ds.events_on(ds.end)[0]
        v0 = st.state_version()
        st.save_answer("rc-" + ev.id, "no", ev.id, None)
        st.add_user_event(CalendarEvent(id="ev-user-1", title="Wind down", start=tu.at(ds.today, 21), end=tu.at(ds.today, 22), type="protected", source="user"))
        st.save_accepted("sg-x", "ev-user-1")
        self.assertNotEqual(st.state_version(), v0)
        fresh = copy.deepcopy(ds)
        st.apply_to(fresh)
        self.assertIs(fresh.event(ev.id).attended, False); self.assertIsNotNone(fresh.event("ev-user-1"))
        self.assertEqual(st.accepted(), {"sg-x": "ev-user-1"})
        st.set_narrative("k", "claude", "text"); self.assertEqual(st.get_narrative("k"), "text")
        st.clear_user_state()
        self.assertEqual(st.answers(), {}); self.assertEqual(st.accepted(), {}); self.assertEqual(st.user_events(), [])
        self.assertEqual(st.state_version(), v0); self.assertEqual(st.profile()["seed"], 3)


if __name__ == "__main__":
    unittest.main()
