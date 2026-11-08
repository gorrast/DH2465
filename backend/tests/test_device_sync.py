"""Phone sync: payload validation, the derived rows, and POST /api/sync against a fake PostgREST."""
import os
import unittest
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient

from stressless.connectors import device_sync as ds
from stressless.server import phone_sync
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore
from tests.test_calendar import Fake

H = 3600000   # one hour in ms
DEVICE = {"installId": "install-1234", "platform": "android", "label": "Pixel", "timeZone": "Europe/Stockholm", "tzOffsetMin": 120}


def local_ms(day: str, hour: float, offset_min: int = 120) -> int:
    """Epoch ms of a local wall-clock time on ``day`` at UTC+offset."""
    y, m, d = map(int, day.split("-"))
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000) + int(hour * H) - offset_min * 60000


def night(day, bed=22.5, wake=30.75, awake=None, sid=None, stage=4):
    """A Health Connect-shaped session from ``bed`` on ``day`` to ``wake`` (hours, > 24 = next morning)."""
    start, end = local_ms(day, bed), local_ms(day, wake)
    stages = [{"start": start, "end": end, "stage": stage}]
    if awake:
        a, b = local_ms(day, awake[0]), local_ms(day, awake[1])
        stages = [{"start": start, "end": a, "stage": 5}, {"start": a, "end": b, "stage": 1}, {"start": b, "end": end, "stage": 6}]
    return {"id": sid or "hc-" + day, "start": start, "end": end, "tzOffsetMin": 120, "source": "com.watch",
            "modifiedAt": "2026-10-12T07:00:00Z", "stages": stages}


def heart(day, start_h, minutes, bpm=60, rid=None, step_s=60):
    """A Health Connect-shaped heart-rate record: one sample every ``step_s`` seconds from ``start_h`` on ``day``."""
    start = local_ms(day, start_h)
    samples = [{"t": start + i * step_s * 1000, "bpm": bpm} for i in range(minutes * 60 // step_s)]
    return {"id": rid or "hr-%s-%s" % (day, start_h), "start": start, "end": start + minutes * 60000, "tzOffsetMin": 120,
            "source": "com.watch", "samples": samples}


def hrv(day, hour, ms, rid):
    return {"id": rid, "time": local_ms(day, hour), "tzOffsetMin": 120, "source": "com.watch", "rmssdMs": ms}


def session(day, start_h, minutes, kind="RUNNING", rid=None, **extra):
    start = local_ms(day, start_h)
    return dict({"id": rid or "ex-%s-%s" % (day, start_h), "start": start, "end": start + minutes * 60000, "tzOffsetMin": 120,
                 "source": "com.fit", "type": kind}, **extra)


def workouts(sessions, frm=("2026-10-10", 0), to=("2026-10-10", 23.9)):
    return {"from": local_ms(*frm), "to": local_ms(*to), "sessions": sessions}


def day_hr(day, bpm=70, **minutes):
    """A heart_rate_days row: ``bpm`` all day, other values for {"m<start>_<end>": bpm} minute ranges."""
    arr = [bpm] * 1440
    for k, v in minutes.items():
        a, b = map(int, k[1:].split("_"))
        arr[a:b] = [v] * (b - a)
    return {"day": day, "bpm": arr}


def batch(**parts):
    return ds.parse(dict({"device": DEVICE}, **parts))


class ParseAndDeriveTests(unittest.TestCase):
    def test_night_keyed_by_evening_with_bedtime_after_noon(self):
        rows = ds.sleep_night_rows(batch(sleep=[night("2026-10-10", bed=23.25)]))
        r = rows[0]
        self.assertEqual((r["night_date"], r["asleep_min"], r["core_min"], r["interruptions"], r["has_stages"]),
                         ("2026-10-10", 450, 450, 0, True))
        self.assertEqual(r["in_bed_at"], "2026-10-10T21:15:00.000Z")
        self.assertEqual(r["stages"][0]["kind"], "core")
        self.assertEqual(ds.bedtime_min(r["in_bed_at"], r["utc_offset_min"]), 675.0)

    def test_after_midnight_belongs_to_previous_evening(self):
        r = ds.sleep_night_rows(batch(sleep=[night("2026-10-10", bed=24 + 1 / 3)]))[0]
        self.assertEqual(r["night_date"], "2026-10-10")
        self.assertEqual(ds.bedtime_min(r["in_bed_at"], 120), 740.0)

    def test_stages_and_interruptions(self):
        r = ds.sleep_night_rows(batch(sleep=[night("2026-10-10", awake=(26, 26.5))]))[0]
        self.assertEqual((r["interruptions"], r["awake_min"], r["asleep_min"]), (1, 30, 465))
        self.assertEqual([s["kind"] for s in r["stages"]], ["deep", "awake", "rem"])

    def test_generic_sleep_has_no_stages(self):
        r = ds.sleep_night_rows(batch(sleep=[night("2026-10-10", stage=2)]))[0]
        self.assertEqual((r["has_stages"], r["asleep_min"], r["stages"]), (False, 495, []))

    def test_longest_session_wins_and_naps_are_dropped(self):
        nap = night("2026-10-10", bed=14, wake=14.5, sid="nap")
        rows = ds.sleep_night_rows(batch(sleep=[nap, night("2026-10-10", bed=23, wake=27, sid="short"), night("2026-10-10", sid="long")]))
        self.assertEqual([(r["night_date"], r["asleep_min"]) for r in rows], [("2026-10-10", 495)])

    def test_consistency_uses_stored_nights_before_the_upload(self):
        late = batch(sleep=[night("2026-10-10", bed=24, wake=32.25)])
        self.assertEqual(ds.sleep_night_rows(late)[0]["score_parts"]["consistency"], 30)   # nothing to compare with
        self.assertLess(ds.sleep_night_rows(late, [630.0] * 7)[0]["score_parts"]["consistency"], 30)

    def test_steps_become_records_and_daily_activity(self):
        b = batch(steps=[{"date": "2026-10-02", "steps": 900}, {"date": "2026-10-01", "steps": 12000.4}])
        self.assertEqual([(r["day"], r["steps"]) for r in ds.activity_rows(b)], [("2026-10-01", 12000), ("2026-10-02", 900)])
        rec = ds.source_records(b)[0]
        self.assertEqual((rec["source_record_id"], rec["start_at"], rec["value"]), ("steps:2026-10-01", "2026-09-30T22:00:00.000Z", 12000))

    def test_heart_rate_becomes_a_minute_day(self):
        d = "2026-10-10"
        b = batch(heartRate=[heart(d, 8, 3, bpm=70, step_s=20), heart(d, 23.98, 3, bpm=80)])   # crosses midnight
        rows = {r["day"]: r for r in ds.heart_rate_day_rows(b)}
        self.assertEqual(sorted(rows), ["2026-10-10", "2026-10-11"])
        day = rows[d]["bpm"]
        self.assertEqual((len(day), day[480:483], day[479], rows[d]["data_origin"]), (1440, [70, 70, 70], None, "com.watch"))
        self.assertEqual(rows[d]["worn_minutes"], 3 + 2)    # 23:58 and 23:59
        recs = [r for r in ds.source_records(b) if r["data_type"] == "heart_rate"]
        self.assertEqual((len(recs), recs[0]["value"], recs[0]["unit"], len(recs[0]["payload"]["samples"])), (2, 70.0, "bpm", 9))

    def test_heart_rate_merges_with_the_stored_day(self):
        d = "2026-10-10"
        stored = [None] * 1440
        stored[100] = 55
        stored[480] = 99
        row = ds.heart_rate_day_rows(batch(heartRate=[heart(d, 8, 2, bpm=70)]), {d: stored})[0]
        self.assertEqual((row["bpm"][100], row["bpm"][480], row["bpm"][481], row["worn_minutes"]), (55, 70, 70, 3))

    def test_glitchy_readings_are_dropped(self):
        b = batch(heartRate=[{"id": "x", "start": 1, "end": 2, "samples": [{"t": 1, "bpm": 0}, {"t": 2, "bpm": 300}]}],
                  hrv=[hrv("2026-10-10", 3, 0.2, "h1"), hrv("2026-10-10", 3, 900, "h2")])
        self.assertEqual((b["heart_rate"][0]["samples"], b["hrv"]), ([], []))

    def test_night_hrv_is_the_mean_of_readings_while_asleep_or_just_after(self):
        d = "2026-10-10"   # in bed 22:30, up 06:45
        readings = [hrv(d, 20, 99, "before"), hrv(d, 26, 40, "a"), hrv(d, 30, 50, "b"), hrv(d, 32, 60, "after-wake"),
                    hrv(d, 34, 99, "too-late")]
        b = batch(sleep=[night(d)], hrv=readings)
        self.assertEqual(ds.sleep_night_rows(b)[0]["hrv_rmssd_ms"], 50.0)
        self.assertIsNone(ds.sleep_night_rows(batch(sleep=[night(d)]))[0]["hrv_rmssd_ms"])
        recs = [r for r in ds.source_records(b) if r["data_type"] == "hrv_rmssd"]
        self.assertEqual((len(recs), recs[1]["value"], recs[1]["unit"], recs[1]["end_at"]), (5, 40.0, "ms", None))

    def test_workouts_keep_start_end_and_details(self):
        d = "2026-10-10"
        b = batch(workouts=workouts([session(d, 20.5, 45, calories=410.4, distanceM=7012.6, avgHr=152, maxHr=181)]))
        row = ds.workout_day_rows(b)[0]
        w = row["workouts"][0]
        self.assertEqual((w["kind"], w["type"], w["start"], w["end"]), ("run", "RUNNING", "2026-10-10T18:30:00.000Z", "2026-10-10T19:15:00.000Z"))
        self.assertEqual((w["avg_hr"], w["max_hr"], w["calories"], w["distance_m"], w["counts_as_workout"]), (152, 181, 410, 7013, True))
        self.assertEqual(row["active_min"], 45)
        rec = [r for r in ds.source_records(b) if r["data_type"] == "exercise"][0]
        self.assertEqual((rec["value"], rec["payload"]["kind"]), (45.0, "run"))

    def test_a_walk_counts_only_when_it_raises_the_heart_rate(self):
        d = "2026-10-10"
        walks = [session(d, 8, 20, "WALKING", "stroll"), session(d, 12, 30, "WALKING", "brisk"), session(d, 16, 15, "WALKING", "no-hr")]
        hr = day_hr(d, 72, m480_500=85, m720_750=108)        # 16:00 has heart rate, but only 2 of 15 minutes
        hr["bpm"][960:962] = [None, None]
        hr["bpm"][962:975] = [None] * 13
        row = ds.workout_day_rows(batch(workouts=workouts(walks)), [hr])[0]
        got = {w["id"]: (w["avg_hr"], w["hr_rise"], w["counts_as_workout"]) for w in row["workouts"]}
        self.assertEqual(got, {"stroll": (85, 13.0, False), "brisk": (108, 36.0, True), "no-hr": (None, None, False)})
        self.assertEqual({w["id"]: w["certain"] for w in row["workouts"]}, {"stroll": False, "brisk": True, "no-hr": False})
        self.assertEqual(row["active_min"], 65)              # every walk is active time

    def test_only_a_long_session_with_a_clear_heart_rate_rise_is_certain(self):
        d = "2026-10-10"
        hr = day_hr(d, 70, m600_640=150, m720_728=150, m900_940=88)
        sessions = [session(d, 10, 40, rid="run"), session(d, 12, 8, rid="short"), session(d, 15, 40, "STRENGTH_TRAINING", "easy"),
                    session(d, 17, 40, rid="no-hr")]
        row = ds.workout_day_rows(batch(workouts=workouts(sessions)), [hr])[0]
        got = {w["id"]: (w["counts_as_workout"], w["certain"]) for w in row["workouts"]}
        self.assertEqual(got, {"run": (True, True), "short": (True, False), "easy": (True, False), "no-hr": (True, False)})

    def test_overlapping_sessions_count_their_minutes_once(self):
        d = "2026-10-10"
        row = ds.workout_day_rows(batch(workouts=workouts([session(d, 10, 60, rid="a"), session(d, 10.5, 60, rid="b")])))[0]
        self.assertEqual(row["active_min"], 90)

    def test_workout_window_clears_empty_days_but_not_a_partial_first_day(self):
        b = batch(workouts=workouts([], frm=("2026-10-08", 14), to=("2026-10-10", 9)),
                  steps=[{"date": "2026-10-01", "steps": 5000}, {"date": "2026-10-10", "steps": 800}])
        rows = {r["day"]: r for r in ds.activity_rows(b)}
        self.assertEqual(sorted(rows), ["2026-10-01", "2026-10-09", "2026-10-10"])
        self.assertNotIn("workouts", rows["2026-10-01"])     # outside the window: stored workouts stay
        self.assertEqual((rows["2026-10-09"]["workouts"], rows["2026-10-09"]["active_min"]), ([], 0))
        self.assertNotIn("steps", rows["2026-10-09"])
        self.assertEqual((rows["2026-10-10"]["steps"], rows["2026-10-10"]["workouts"]), (800, []))
        self.assertEqual(ds.activity_rows(batch(steps=[{"date": "2026-10-01", "steps": 1}]))[0].keys(),
                         {"day", "source", "utc_offset_min", "steps"})

    def test_resting_hr_from_the_watch_wins_over_the_computed_one(self):
        d = "2026-10-10"   # in bed 22:30, asleep until 06:45
        hr = [heart(d, 22.5, 120, bpm=60), heart(d, 24.5, 30, bpm=48, rid="low"), heart(d, 25, 330, bpm=58, rid="rest")]
        b = batch(sleep=[night(d)], heartRate=hr,
                  restingHeartRate=[{"id": "r1", "time": local_ms("2026-10-11", 8), "tzOffsetMin": 120, "bpm": 51},
                                    {"id": "old", "time": local_ms("2026-10-09", 8), "tzOffsetMin": 120, "bpm": 70},
                                    {"id": "glitch", "time": local_ms(d, 23), "tzOffsetMin": 120, "bpm": 5}])
        rows = ds.heart_rate_day_rows(b)
        self.assertEqual(ds.sleep_night_rows(b, hr_days=rows)[0]["resting_hr"], 51)   # dated the morning the night ends
        self.assertEqual(len([r for r in ds.source_records(b) if r["data_type"] == "resting_heart_rate"]), 2)

        b = batch(sleep=[night(d)], heartRate=hr)
        self.assertEqual(ds.sleep_night_rows(b, hr_days=ds.heart_rate_day_rows(b))[0]["resting_hr"], 48)  # the half hour at 48 from 00:30
        self.assertIsNone(ds.sleep_night_rows(batch(sleep=[night(d)]))[0]["resting_hr"])

    def test_computed_resting_hr_needs_enough_minutes(self):
        d = "2026-10-10"
        b = batch(sleep=[night(d)], heartRate=[heart(d, 23, 15, bpm=50)])
        self.assertIsNone(ds.sleep_night_rows(b, hr_days=ds.heart_rate_day_rows(b))[0]["resting_hr"])

    def test_screen_time(self):
        d = "2026-10-10"
        b = batch(screenTime={
            "from": local_ms(d, 0), "to": local_ms(d, 36), "launcherPackage": "com.launcher",
            "sessions": [
                {"pkg": "com.chat", "start": local_ms(d, 9), "end": local_ms(d, 9.5)},
                {"pkg": "com.chat", "start": local_ms(d, 9), "end": local_ms(d, 9.25)},      # same session, from an earlier read
                {"pkg": "com.video", "start": local_ms(d, 23.5), "end": local_ms(d, 24.5)},  # crosses midnight
                {"pkg": "com.launcher", "start": local_ms(d, 12), "end": local_ms(d, 13)},   # home screen: raw only
            ],
            "screenEvents": [{"type": "unlock", "ts": local_ms(d, 8.9)}, {"type": "screen_off", "ts": local_ms(d, 9.6)},
                             {"type": "unlock", "ts": local_ms(d, 23.4)}]})
        recs = [r for r in ds.source_records(b) if r["data_type"] == "app_usage"]
        self.assertEqual(len(recs), 3)
        chat = [r for r in recs if r["data_origin"] == "com.chat"][0]
        self.assertEqual((chat["source_record_id"], chat["value"]), ("com.chat:%d" % local_ms(d, 9), 30.0))
        self.assertEqual([r["payload"] for r in recs if r["data_origin"] == "com.launcher"], [{"not_screen_time": True}])
        self.assertEqual(len([r for r in ds.source_records(b) if r["data_type"] == "screen_event"]), 3)
        m = {(r["day"], r["metric_key"]): r["value"] for r in ds.metric_rows(b)}
        self.assertEqual(m[(d, "screen.minutes")], 60.0)          # 30 chat + 30 video before midnight
        self.assertEqual(m[(d, "screen.late_minutes")], 60.0)     # the whole video session, after midnight too
        self.assertEqual(m[(d, "screen.pickups")], 2)
        self.assertEqual(m[("2026-10-11", "screen.minutes")], 30.0)
        self.assertEqual(m[("2026-10-11", "screen.late_minutes")], 0.0)

    def test_partial_first_day_is_not_summarised(self):
        d = "2026-10-10"
        b = batch(screenTime={"from": local_ms(d, 23), "to": local_ms(d, 26), "sessions": [{"pkg": "a", "start": local_ms(d, 23.5), "end": local_ms(d, 25)}]})
        self.assertEqual({r["day"] for r in ds.metric_rows(b)}, {"2026-10-11"})

    def test_rejects_malformed_input(self):
        for bad in ({"steps": []}, {"device": {"installId": "short"}},
                    {"device": DEVICE, "steps": [{"date": "10/01", "steps": 1}]},
                    {"device": DEVICE, "steps": [{"date": "2026-10-01", "steps": -5}]},
                    {"device": DEVICE, "sleep": [{"start": "2026-10-01T23:00:00Z", "end": "2026-10-01T22:00:00Z"}]},
                    {"device": DEVICE, "screenTime": "nope"},
                    {"device": DEVICE, "screenTime": {"from": 1, "to": 2, "screenEvents": [{"type": "boom", "ts": 1}]}},
                    {"device": dict(DEVICE, tzOffsetMin=9999)},
                    {"device": DEVICE, "steps": [{}] * (ds.MAX_DAYS + 1)},
                    {"device": DEVICE, "heartRate": [{"start": 2, "end": 1}]},
                    {"device": DEVICE, "heartRate": [{"start": 1, "end": 2, "samples": [{"t": 1, "bpm": "fast"}]}]},
                    {"device": DEVICE, "hrv": [{"time": 1}]},
                    {"device": DEVICE, "workouts": {"from": 2, "to": 1}},
                    {"device": DEVICE, "workouts": {"from": 1, "to": 2, "sessions": ["run"]}}, []):
            with self.assertRaises(ValueError, msg=repr(bad)[:80]):
                ds.parse(bad)


ENV = {"NEXT_PUBLIC_SUPABASE_URL": "https://db.test", "SUPABASE_SERVICE_ROLE_KEY": "service-key"}
TABLES = ("profiles", "provider_connections", "connection_streams", "source_records", "sleep_nights", "heart_rate_days", "daily_activity",
          "daily_metrics")


class SyncApiTests(unittest.TestCase):
    user = "user-a"

    def setUp(self):
        self._old = {k: os.environ.get(k) for k in ENV}
        os.environ.update(ENV)
        self.fake = Fake()
        self.fake.tables = {t: [] for t in TABLES}
        self.fake.tables["profiles"] = [{"user_id": "user-a", "consented_at": "2026-10-01T00:00:00Z"},
                                        {"user_id": "user-b", "consented_at": None}]
        phone_sync._client = httpx.Client(transport=httpx.MockTransport(self.fake))
        type(self).user = "user-a"
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=type(self).user, store=MemoryStore())
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        phone_sync._client = None
        for k, v in self._old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def rows(self, table, **match):
        return [r for r in self.fake.tables[table] if all(r.get(k) == v for k, v in match.items())]

    def payload(self, steps=8000, video_end=24.5):
        d = "2026-10-10"
        return {"device": DEVICE, "permissions": {"sleep_session": True, "steps": True, "app_usage": True},
                "sleep": [night(d)], "steps": [{"date": d, "steps": steps}],
                "screenTime": {"from": local_ms(d, 0), "to": local_ms(d, 25),
                               "sessions": [{"pkg": "com.video", "start": local_ms(d, 23.5), "end": local_ms(d, video_end)}],
                               "screenEvents": [{"type": "unlock", "ts": local_ms(d, 23.4)}]}}

    def test_sync_writes_every_layer(self):
        r = self.client.post("/api/sync", json=self.payload())
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["stored"], {"records": 4, "nights": 1, "step_days": 1, "heart_rate_days": 0, "heart_rate_samples": 0,
                                          "hrv_readings": 0, "nights_with_hrv": 0, "resting_hr_readings": 0,
                                          "nights_with_resting_hr": 0, "workout_sessions": 0, "workouts": 0,
                                          "screen_sessions": 1, "screen_days": 2})
        self.assertEqual(body["nights"][0]["night"], "2026-10-10")

        conns = self.rows("provider_connections", user_id="user-a")
        self.assertEqual(sorted(c["provider"] for c in conns), ["health_connect", "screen_time"])
        self.assertTrue(all(c["provider_account_id"] == "install-1234" and c["connected_at"] and c["last_synced_at"] for c in conns))
        by_provider = {c["provider"]: c["id"] for c in conns}
        recs = self.rows("source_records", user_id="user-a")
        self.assertEqual(sorted((r["source"], r["data_type"]) for r in recs),
                         [("health_connect", "sleep_session"), ("health_connect", "steps"), ("screen_time", "app_usage"), ("screen_time", "screen_event")])
        self.assertTrue(all(r["connection_id"] == by_provider[r["source"]] for r in recs))
        self.assertEqual(self.rows("sleep_nights", user_id="user-a")[0]["night_date"], "2026-10-10")
        self.assertEqual(self.rows("daily_activity", user_id="user-a")[0]["steps"], 8000)
        late = self.rows("daily_metrics", user_id="user-a", day="2026-10-10", metric_key="screen.late_minutes")[0]
        self.assertEqual((late["value"], late["source"]), (60.0, "screen_time"))
        streams = {(s["connection_id"], s["data_type"]): s for s in self.rows("connection_streams", user_id="user-a")}
        self.assertEqual(len(streams), 4)
        self.assertEqual(streams[(by_provider["health_connect"], "steps")]["data_until"], "2026-10-10T22:00:00.000Z")

    def test_sync_stores_heart_rate_and_hrv(self):
        d = "2026-10-10"
        p = self.payload()
        p["permissions"].update(heart_rate=True, hrv_rmssd=True)
        p["heartRate"] = [heart(d, 8, 30, bpm=65)]
        p["hrv"] = [hrv(d, 27, 42, "hv1")]
        p["restingHeartRate"] = [{"id": "rh1", "time": local_ms("2026-10-11", 7), "tzOffsetMin": 120, "bpm": 54}]
        r = self.client.post("/api/sync", json=p)
        self.assertEqual(r.status_code, 200, r.text)
        stored = r.json()["stored"]
        self.assertEqual((stored["heart_rate_days"], stored["heart_rate_samples"], stored["hrv_readings"], stored["nights_with_hrv"]),
                         (1, 30, 1, 1))
        hr = self.rows("heart_rate_days", user_id="user-a")[0]
        self.assertEqual((hr["day"], hr["worn_minutes"], hr["bpm"][480], hr["source"]), (d, 30, 65, "health_connect"))
        self.assertEqual(self.rows("sleep_nights", user_id="user-a")[0]["hrv_rmssd_ms"], 42.0)
        self.assertEqual(self.rows("sleep_nights", user_id="user-a")[0]["resting_hr"], 54)
        types = {s["data_type"] for s in self.rows("connection_streams", user_id="user-a")}
        self.assertTrue({"heart_rate", "hrv_rmssd"} <= types)

        # a later sync with the afternoon keeps the morning
        p["heartRate"] = [heart(d, 15, 10, bpm=90)]
        self.client.post("/api/sync", json=p)
        hr = self.rows("heart_rate_days", user_id="user-a")
        self.assertEqual((len(hr), hr[0]["worn_minutes"], hr[0]["bpm"][480], hr[0]["bpm"][900]), (1, 40, 65, 90))

    def test_sync_stores_workouts_without_losing_steps(self):
        d = "2026-10-10"
        self.client.post("/api/sync", json=self.payload(steps=8000))
        p = self.payload()
        del p["steps"]
        p["heartRate"] = [heart(d, 7, 600, bpm=70), heart(d, 19, 40, bpm=150, rid="run-hr")]
        p["workouts"] = workouts([session(d, 19, 40), session(d, 12, 20, "WALKING", "walk")])
        r = self.client.post("/api/sync", json=p)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["stored"]["workout_sessions"], r.json()["stored"]["workouts"]), (2, 1))
        row = self.rows("daily_activity", user_id="user-a", day=d)[0]
        self.assertEqual((row["steps"], row["active_min"]), (8000, 60))     # the steps of the first sync are kept
        run = next(w for w in row["workouts"] if w["kind"] == "run")
        self.assertEqual((run["avg_hr"], run["counts_as_workout"]), (150, True))   # from the synced heart rate
        self.assertFalse(next(w for w in row["workouts"] if w["kind"] == "walk")["counts_as_workout"])

    def test_resync_overwrites_instead_of_duplicating(self):
        self.client.post("/api/sync", json=self.payload())
        r = self.client.post("/api/sync", json=self.payload(steps=9000, video_end=25))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.rows("provider_connections")), 2)
        self.assertEqual(len(self.rows("source_records")), 4)
        self.assertEqual(self.rows("daily_activity")[0]["steps"], 9000)
        video = self.rows("source_records", data_type="app_usage")[0]
        self.assertEqual(video["value"], 90.0)   # the session that was still open grew

    def test_consistency_reads_stored_nights(self):
        for d in range(3, 10):
            self.fake.tables["sleep_nights"].append({"user_id": "user-a", "night_date": "2026-10-%02d" % d,
                                                     "in_bed_at": "2026-10-%02dT20:30:00.000Z" % d, "utc_offset_min": 120})
        p = self.payload()
        p["sleep"] = [night("2026-10-10", bed=24, wake=32.25)]
        r = self.client.post("/api/sync", json=p)
        self.assertLess(r.json()["nights"][0]["parts"]["consistency"], 30)

    def test_needs_consent(self):
        type(self).user = "user-b"
        r = self.client.post("/api/sync", json=self.payload())
        self.assertEqual(r.status_code, 403)
        self.assertIn("consent_required", r.json()["error"])
        self.assertEqual(self.fake.tables["source_records"], [])

    def test_bad_payload_is_400_before_touching_the_database(self):
        r = self.client.post("/api/sync", json={"device": DEVICE, "steps": [{"date": "x", "steps": 1}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("steps[0].date", r.json()["error"])
        self.assertEqual(self.rows("provider_connections"), [])

    def test_not_configured(self):
        os.environ.pop("SUPABASE_SERVICE_ROLE_KEY")
        self.assertEqual(self.client.post("/api/sync", json=self.payload()).status_code, 503)

    def test_requires_sign_in(self):
        app.dependency_overrides.clear()
        self.assertEqual(self.client.post("/api/sync", json=self.payload()).status_code, 401)

    def test_cors_preflight_from_app_webview(self):
        r = self.client.options("/api/sync", headers={"Origin": "https://localhost", "Access-Control-Request-Method": "POST",
                                                      "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["access-control-allow-origin"], "https://localhost")


if __name__ == "__main__":
    unittest.main()
