"""Real-data loader: demo data written out as real-data table rows (PostgREST JSON), read back into a Dataset."""
import json
import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

from fastapi.testclient import TestClient

from stressless.connectors.real_data import load_dataset, real_sources
from stressless.engine.pipeline import Engine
from stressless.engine.report_input import daily_input
from stressless.models import to_jsonable
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore
from stressless.timeutil import tz
from tests.helpers import ANCHOR, dataset

CONN = "11111111-1111-1111-1111-111111111111"


def _iso(dt):
    return dt.isoformat() if dt else None


def rows_from(ds):
    """The tables the API's ingest would write, filled from a simulated dataset."""
    nights = [{"night_date": n.date.isoformat(), "source": "health_connect", "utc_offset_min": 120,
               "in_bed_at": _iso(n.in_bed_start), "onset_at": _iso(n.sleep_onset), "wake_at": _iso(n.wake_time),
               "out_of_bed_at": _iso(n.out_of_bed), "asleep_min": n.duration_min, "deep_min": n.deep_min,
               "rem_min": n.rem_min, "core_min": n.core_min, "awake_min": n.awake_min, "interruptions": n.interruptions,
               "has_stages": bool(n.stages), "stages": [{"kind": s.kind, "start": _iso(s.start), "end": _iso(s.end)} for s in n.stages],
               "hrv_rmssd_ms": n.hrv_ms, "hrv_sdnn_ms": None, "resting_hr": n.resting_hr, "resp_rate": n.resp_rate,
               "spo2": n.spo2, "skin_temp_dev": n.wrist_temp_dev, "score": n.score, "score_parts": n.score_parts,
               "score_source": "stressless", "algorithm_version": "v1"}
              for n in ds.nights if n.worn]
    hr = [{"day": h.date.isoformat(), "source": "health_connect", "utc_offset_min": 120, "bpm": h.bpm,
           "worn_minutes": sum(1 for b in h.bpm if b is not None)} for h in ds.hr_days]
    activity = [{"day": a.date.isoformat(), "source": "health_connect", "utc_offset_min": 120, "steps": a.steps,
                 "active_min": a.active_minutes, "hourly_steps": a.hourly_steps,
                 "workouts": [{"kind": w.kind, "start": _iso(w.start), "end": _iso(w.end), "avg_hr": w.avg_hr,
                               "max_hr": w.max_hr, "calories": w.calories} for w in a.workouts]} for a in ds.activity]
    events = [{"id": "ev-%d" % i, "provider": "google_calendar", "title": e.title, "category": e.type,
               "starts_at": _iso(e.start), "ends_at": _iso(e.end), "location": e.location_hint,
               "attendee_count": e.attendees, "recurring_key": e.recurring_key} for i, e in enumerate(ds.events)]
    last = max(n.out_of_bed for n in ds.nights if n.worn and n.out_of_bed)
    return {"sleep_nights": nights, "heart_rate_days": hr, "daily_activity": activity, "calendar_events": events,
            "provider_connections": [{"id": CONN, "provider": "health_connect", "status": "connected",
                                      "last_synced_at": _iso(last)}],
            "connection_streams": [{"connection_id": CONN, "data_type": "sleep_session", "permitted": True,
                                    "data_until": _iso(last), "last_synced_at": _iso(last)}]}


def real_store():
    store = MemoryStore()
    store.tables = json.loads(json.dumps(rows_from(dataset())))      # exactly what JSON can carry
    return store


class LoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = dataset()
        cls.ds = load_dataset(real_store(), ANCHOR)

    def test_nights_scores_and_heart_rate_survive_the_round_trip(self):
        self.assertEqual(self.ds.source, "real")
        for n in self.ds.nights:
            demo = self.demo.night(n.date)
            self.assertEqual((n.worn, n.score), (demo.worn, demo.score) if demo and demo.worn else (False, None), n.date)
        d = ANCHOR - timedelta(days=1)
        self.assertEqual(self.ds.hr(d).bpm, self.demo.hr(d).bpm)
        self.assertEqual(self.ds.night(d).stages[0].start, self.demo.night(d).stages[0].start)
        self.assertEqual(len(self.ds.events_on(d)), len(self.demo.events_on(d)))

    def test_personal_baselines_come_from_history(self):
        p = self.ds.persona
        self.assertEqual(p.tz, "Europe/Stockholm")
        self.assertAlmostEqual(p.resting_hr, self.demo.persona.resting_hr, delta=6)
        self.assertAlmostEqual(p.usual_bedtime, self.demo.persona.usual_bedtime, delta=1.0)
        self.assertTrue(420 <= p.sleep_need_min <= 570)

    def test_reports_build_from_real_data(self):
        inp = daily_input(Engine(self.ds), ANCHOR)
        demo_inp = daily_input(Engine(self.demo), ANCHOR)
        score = next(m for m in inp.metrics if m.key == "sleep.score")
        self.assertEqual(score.value, next(m for m in demo_inp.metrics if m.key == "sleep.score").value)
        self.assertTrue(inp.patterns)

    def test_watch_workouts_drive_the_workout_slot_but_plain_walks_do_not(self):
        from stressless.engine.features import day_features
        store = real_store()
        d = ANCHOR - timedelta(days=3)
        z = tz("Europe/Stockholm")
        at = lambda h, m=0: datetime(d.year, d.month, d.day, h, m, tzinfo=z).isoformat()
        store.tables["calendar_events"] = [e for e in store.tables["calendar_events"]
                                           if not (e["category"] == "workout" and e["starts_at"][:10] == d.isoformat())]
        row = next(a for a in store.tables["daily_activity"] if a["day"] == d.isoformat())
        row["workouts"] = [{"kind": "walk", "start": at(7), "end": at(7, 30), "avg_hr": 90, "max_hr": 95, "counts_as_workout": False},
                           {"kind": "strength", "start": at(12), "end": at(12, 40), "avg_hr": 95, "max_hr": 110,
                            "counts_as_workout": True, "certain": False},
                           {"kind": "run", "start": at(21), "end": at(21, 45), "avg_hr": 150, "max_hr": 175, "calories": 400,
                            "counts_as_workout": True, "certain": True}]
        ds = load_dataset(store, ANCHOR)
        self.assertEqual([w.kind for w in ds.activity_on(d).workouts], ["strength", "run"])   # the plain walk is dropped
        f = day_features(ds, d)
        self.assertEqual((f.workout_slot, f.workout_minutes), ("late", 45))
        for day in (d, d - timedelta(days=1), d - timedelta(days=2)):          # the demo keeps to the calendar
            self.assertEqual(day_features(self.demo, day), day_features(self.demo, day, events=self.demo.events_on(day)))

    def test_a_booked_workout_is_confirmed_by_an_overlapping_session_and_never_replaced(self):
        from stressless.engine.reality import reality_checks
        store = real_store()
        ev = next(e for e in store.tables["calendar_events"] if e["category"] == "workout"
                  and datetime.fromisoformat(e["ends_at"]).date() < ANCHOR - timedelta(days=2))
        s, e = datetime.fromisoformat(ev["starts_at"]), datetime.fromisoformat(ev["ends_at"])
        d = s.date()
        hr = next(h for h in store.tables["heart_rate_days"] if h["day"] == d.isoformat())
        a, b = s.hour * 60 + s.minute, e.hour * 60 + e.minute
        hr["bpm"][a:b] = [72] * (b - a)                     # nothing in the heart rate either
        row = next(r for r in store.tables["daily_activity"] if r["day"] == d.isoformat())
        later = (e + timedelta(hours=4)).isoformat(), (e + timedelta(hours=5)).isoformat()
        row["workouts"] = [{"kind": "run", "start": later[0], "end": later[1], "avg_hr": 150, "max_hr": 170,
                            "counts_as_workout": True, "certain": True}]

        def check(st):
            ds = load_dataset(st, ANCHOR)
            return next((c for c in reality_checks(ds, d, d, {}) if c.event_id == str(ev["id"])), None)

        c = check(store)                                    # a run hours later does not stand in for the booking
        self.assertIsNotNone(c)
        self.assertEqual(c.kind, "booked_not_seen")
        texts = [x.text for x in c.evidence]
        self.assertIn("Nothing logged by your watch or phone at that time", texts)
        self.assertTrue(any(t.startswith("Logged run") for t in texts), texts)

        row["workouts"].append({"kind": "strength", "start": s.isoformat(), "end": (s + timedelta(minutes=30)).isoformat(),
                                "avg_hr": 95, "max_hr": 110, "counts_as_workout": True, "certain": False})
        self.assertIsNone(check(store))                     # an overlapping session confirms it, certain or not

    def test_the_seeded_demo_account_keeps_the_calendar_rules(self):
        from stressless.engine.features import day_features
        store = real_store()
        for n in store.tables["sleep_nights"]:
            n["data_origin"] = "seed-demo"                # what tools/seed_demo.py writes
        d = ANCHOR - timedelta(days=3)
        z = tz("Europe/Stockholm")
        at = lambda h, m=0: datetime(d.year, d.month, d.day, h, m, tzinfo=z).isoformat()
        store.tables["calendar_events"] = [e for e in store.tables["calendar_events"]
                                           if not (e["category"] == "workout" and e["starts_at"][:10] == d.isoformat())]
        row = next(a for a in store.tables["daily_activity"] if a["day"] == d.isoformat())
        row["workouts"] = [{"kind": "run", "start": at(21), "end": at(21, 45), "avg_hr": 150, "max_hr": 175, "calories": 400}]
        ds = load_dataset(store, ANCHOR)
        self.assertTrue(ds.seeded_demo)
        self.assertFalse(ds.phone_rules)
        self.assertEqual(day_features(ds, d).workout_slot, "none")    # an unbooked logged workout does not count here
        self.assertFalse(load_dataset(real_store(), ANCHOR).seeded_demo)

    def test_screen_time_metrics_are_loaded_up_to_yesterday(self):
        store = real_store()
        y = ANCHOR - timedelta(days=1)
        store.tables["daily_metrics"] = [
            {"day": y.isoformat(), "metric_key": "screen.late_minutes", "value": 42.5, "source": "screen_time"},
            {"day": ANCHOR.isoformat(), "metric_key": "screen.minutes", "value": 30, "source": "screen_time"}]   # today: partial
        ds = load_dataset(store, ANCHOR)
        self.assertEqual(ds.metric_on(y, "screen.late_minutes"), 42.5)
        self.assertIsNone(ds.metric_on(ANCHOR, "screen.minutes"))
        inp = daily_input(Engine(ds), ANCHOR)
        self.assertEqual(next(m for m in inp.metrics if m.key == "screen.late_minutes").value, 42.5)

    def test_media_plays_are_loaded_in_local_time_from_their_end(self):
        store = real_store()
        y = ANCHOR - timedelta(days=1)
        store.tables["media_events"] = [
            {"id": "m1", "provider": "spotify", "occurred_at": y.isoformat() + "T21:30:00+00:00", "title": "Holocene",
             "creator": "Bon Iver", "minutes": 30, "source": {"media_kind": "music"}},
            {"id": "m2", "provider": "netflix", "occurred_at": y.isoformat() + "T20:00:00+00:00", "title": "Dark",
             "creator": None, "minutes": 50, "source": {}},
            {"id": "m3", "provider": "spotify", "occurred_at": ANCHOR.isoformat() + "T08:00:00+00:00", "title": "Today",
             "creator": "X", "minutes": 3, "source": {}}]                                            # today: not loaded
        ds = load_dataset(store, ANCHOR)
        plays = ds.media_on(y)
        self.assertEqual([(m.creator, m.kind) for m in plays], [(None, "video"), ("Bon Iver", "music")])
        self.assertEqual((plays[1].start.hour, plays[1].start.minute), (23, 0))                 # 21:30 UTC ends 23:30 CEST
        self.assertEqual(ds.media_on(ANCHOR), [])
        inp = daily_input(Engine(ds), ANCHOR)
        self.assertEqual(next(m for m in inp.metrics if m.key == "music.minutes").value, 30)
        self.assertIn("30 min of music, mostly Bon Iver", inp.days[0].tags)

    def test_only_unlocks_are_loaded_from_the_screen_events(self):
        store = real_store()
        y = ANCHOR - timedelta(days=1)
        ev = lambda rid, ts, kind, data_type="screen_event": {  # noqa: E731
            "id": rid, "source": "screen_time", "data_type": data_type, "source_record_id": rid, "start_at": ts,
            "end_at": None, "payload": {"type": kind} if kind else {}}
        store.tables["source_records"] = [
            ev("u1", y.isoformat() + "T12:00:00+00:00", "unlock"),
            ev("s1", y.isoformat() + "T11:59:00+00:00", "screen_on"),
            ev("a1", y.isoformat() + "T12:01:00+00:00", None, "app_usage"),
            ev("u2", ANCHOR.isoformat() + "T08:00:00+00:00", "unlock")]                      # today: not loaded
        ds = load_dataset(store, ANCHOR)
        local = datetime.fromisoformat(y.isoformat() + "T12:00:00+00:00").astimezone(tz(store.time_zone()))
        self.assertEqual(ds.unlocks_on(y), [local])                                           # local time, unlocks only
        self.assertEqual(ds.unlocks_on(ANCHOR), [])

    def test_uncategorized_events_are_classified_and_hrv_measure_is_not_mixed(self):
        store = real_store()
        store.tables["calendar_events"][0]["category"] = "uncategorized"
        for r in store.tables["sleep_nights"][:3]:                   # a few SDNN nights in an RMSSD history
            r["hrv_sdnn_ms"], r["hrv_rmssd_ms"] = 99.0, None
        ds = load_dataset(store, ANCHOR)
        self.assertNotEqual(ds.events[0].type, "uncategorized")
        self.assertNotIn(99.0, [n.hrv_ms for n in ds.nights])

    def test_readiness_comes_from_the_sync_tables(self):
        sources = real_sources(real_store(), self.ds, ANCHOR)
        health = sources[0]
        self.assertEqual((health.key, health.connected, health.required, health.ready), ("health_connect", True, True, True))
        self.assertIsNotNone(health.data_until)
        empty = MemoryStore()
        self.assertEqual([(s.key, s.connected, s.required) for s in real_sources(empty, self.ds, ANCHOR)],
                         [("health", False, True)])


@mock.patch.dict(os.environ, {"STRESSLESS_DATA": "real", "STRESSLESS_ANCHOR": ANCHOR.isoformat()})
class RealApiTests(unittest.TestCase):
    def setUp(self):
        self.store = real_store()
        app.dependency_overrides[current_principal] = lambda: Principal(user_id="real-user", store=self.store)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_daily_report_over_the_api(self):
        overview = self.client.get("/api/reports").json()
        self.assertTrue(overview["ready"])
        self.assertEqual(overview["sources"][0]["key"], "health_connect")
        r = self.client.post("/api/reports/daily/%s" % ANCHOR.isoformat())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertEqual(r.json()["report"]["mode"], "rules")              # no model configured in tests
        self.assertEqual(self.client.get("/api/meta").json()["source"], "real")

    def test_regenerate_only_off_prod(self):
        url = "/api/reports/daily/%s" % ANCHOR.isoformat()
        first = self.client.post(url).json()["report"]
        self.assertEqual(self.client.post(url).json()["report"]["generated_at"], first["generated_at"])     # stored
        with mock.patch.dict(os.environ, {"ENVIRONMENT": "PROD"}):
            self.assertEqual(self.client.post(url + "?regenerate=true").status_code, 403)
            self.assertFalse(self.client.get("/api/reports").json()["dev"])
        again = self.client.post(url + "?regenerate=true")                       # unset counts as dev
        self.assertEqual(again.status_code, 200, again.text[:300])
        self.assertNotEqual(again.json()["report"]["generated_at"], first["generated_at"])


if __name__ == "__main__":
    unittest.main()
