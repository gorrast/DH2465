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
                    {"device": DEVICE, "steps": [{}] * (ds.MAX_DAYS + 1)}, []):
            with self.assertRaises(ValueError, msg=repr(bad)[:80]):
                ds.parse(bad)


ENV = {"NEXT_PUBLIC_SUPABASE_URL": "https://db.test", "SUPABASE_SERVICE_ROLE_KEY": "service-key"}
TABLES = ("profiles", "provider_connections", "connection_streams", "source_records", "sleep_nights", "daily_activity", "daily_metrics")


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
        self.assertEqual(body["stored"], {"records": 4, "nights": 1, "step_days": 1, "screen_sessions": 1, "screen_days": 2})
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
