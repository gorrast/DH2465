"""Apple derive: raw Apple Health / Screen Time records -> derived rows, and POST /api/apple/derive on a fake PostgREST."""
import os
import unittest
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from stressless.connectors import apple_derive as ad
from stressless.server import phone_sync
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore
from tests.test_calendar import Fake

OFF = 120                       # Stockholm summer time
WATCH, PHONE = "Hugo's Apple Watch", "Hugo's iPhone"
_n = [0]


def at(day: str, hour: float) -> datetime:
    """UTC instant of local wall-clock ``hour`` on ``day`` (hours > 24 roll into the next morning)."""
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, tzinfo=timezone.utc) + timedelta(hours=hour, minutes=-OFF)


def rec(kind, start, end=None, value=None, origin=WATCH, stage=None, data_type=None, payload=None):
    _n[0] += 1
    iso = lambda t: t.isoformat().replace("+00:00", "Z")
    return {"id": "r%06d" % _n[0], "user_id": "user-a", "source": ad.HEALTH, "data_type": data_type or "ah_x", "kind": kind,
            "data_origin": origin, "start_at": iso(start), "end_at": iso(end or start), "start_offset_min": OFF,
            "value": value, "stage": stage, "payload": payload}


def seg(day, a, b, stage, origin=WATCH):
    return rec(ad.SLEEP, at(day, a), at(day, b), origin=origin, stage="HKCategoryValueSleepAnalysis" + stage,
               data_type="ah_sleep_analysis")


def night(day="2026-10-05"):
    """A watch night 23:00-07:00 with a wake-up at 03:00, the phone's in-bed record and some vitals."""
    return [seg(day, 23.0, 23.25, "Awake"), seg(day, 23.25, 26.0, "AsleepCore"), seg(day, 26.0, 26.25, "Awake"),
            seg(day, 26.25, 28.0, "AsleepDeep"), seg(day, 28.0, 30.0, "AsleepREM"), seg(day, 30.0, 31.0, "AsleepCore"),
            seg(day, 22.5, 31.25, "InBed", origin=PHONE),
            rec(ad.HRV, at(day, 25), value=40, data_type="hrv_sdnn"), rec(ad.HRV, at(day, 27), value=50, data_type="hrv_sdnn"),
            rec(ad.HRV, at(day, 15), value=90, data_type="hrv_sdnn"),            # daytime: not the night's HRV
            rec(ad.RESP, at(day, 26), value=14.5), rec(ad.SPO2, at(day, 26), value=0.96),
            rec(ad.RHR, at("2026-10-06", 0.5), value=52, data_type="resting_heart_rate")]


class DeriveTests(unittest.TestCase):
    def test_night_uses_the_watch_stages_and_its_vitals(self):
        raw = ad.parse(night())
        rows = ad.sleep_night_rows(raw)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["night_date"], r["source"], r["data_origin"]), ("2026-10-05", "apple_health", WATCH))
        self.assertEqual((r["asleep_min"], r["deep_min"], r["rem_min"], r["core_min"]), (450, 105, 120, 225))
        self.assertEqual((r["interruptions"], r["has_stages"]), (1, True))
        self.assertEqual((r["hrv_sdnn_ms"], r["resting_hr"], r["resp_rate"], r["spo2"]), (45.0, 52, 14.5, 96.0))
        self.assertIsNone(r["skin_temp_dev"])
        self.assertTrue(0 <= r["score"] <= 100)

    def test_phone_only_night_still_counts(self):
        rows = ad.sleep_night_rows(ad.parse([seg("2026-10-05", 23, 30.5, "InBed", origin=PHONE)]))
        self.assertEqual((rows[0]["asleep_min"], rows[0]["has_stages"], rows[0]["data_origin"]), (450, False, PHONE))

    def test_nap_is_not_merged_into_the_night(self):
        rows = ad.sleep_night_rows(ad.parse(night() + [seg("2026-10-05", 14, 14.75, "AsleepCore")]))
        self.assertEqual(rows[0]["in_bed_at"][:16], "2026-10-05T21:00")   # 23:00 local, not the 14:00 nap

    def test_wrist_temperature_becomes_a_deviation(self):
        rows = []
        for i, t in enumerate((36.0, 36.2, 36.4)):
            d = "2026-10-0%d" % (i + 1)
            rows += [seg(d, 23, 30, "AsleepCore"), rec(ad.TEMP, at(d, 23.5), at(d, 30), value=t)]
        self.assertEqual([r["skin_temp_dev"] for r in ad.sleep_night_rows(ad.parse(rows))], [-0.2, 0.0, 0.2])

    def test_heart_rate_minutes(self):
        raw = ad.parse([rec(ad.HR, at("2026-10-05", 8), value=60), rec(ad.HR, at("2026-10-05", 8), value=70),
                        rec(ad.HR, at("2026-10-05", 23.99), value=55), rec(ad.HR, at("2026-10-05", 9), value=999)])
        (row,) = ad.heart_rate_day_rows(raw, date(2026, 10, 5), date(2026, 10, 5))
        self.assertEqual((len(row["bpm"]), row["bpm"][480], row["bpm"][1439], row["worn_minutes"]), (1440, 65, 55, 2))

    def test_steps_from_one_device_and_workouts_with_heart_rate(self):
        d = "2026-10-05"
        raw = ad.parse([rec(ad.STEPS, at(d, 9), value=1000, origin=PHONE), rec(ad.STEPS, at(d, 9.5), value=1200),
                        rec(ad.STEPS, at(d, 18), value=3000), rec(ad.STEPS, at(d, 18), value=2500, origin=PHONE),
                        rec(ad.HR, at(d, 18.2), value=140), rec(ad.HR, at(d, 18.4), value=160),
                        rec(ad.WORKOUT, at(d, 18), at(d, 18.5), payload={"attributes": {
                            "workoutActivityType": "HKWorkoutActivityTypeRunning"}, "children": [
                            {"tag": "WorkoutStatistics", "attributes": {"type": ad.ENERGY, "sum": "310.5"}}]})])
        (row,) = ad.activity_rows(raw, date(2026, 10, 5), date(2026, 10, 5))
        self.assertEqual((row["steps"], row["hourly_steps"][9], row["hourly_steps"][18], row["active_min"]), (4200, 1200, 3000, 30))
        self.assertEqual({k: row["workouts"][0][k] for k in ("kind", "avg_hr", "max_hr", "calories")},
                         {"kind": "run", "avg_hr": 150, "max_hr": 160, "calories": 310})

    def test_apple_only_daily_metrics(self):
        d = "2026-10-05"
        raw = ad.parse([rec(ad.ENERGY, at(d, 9), value=200), rec(ad.ENERGY, at(d, 12), value=150, origin=PHONE),
                        rec(ad.EXERCISE, at(d, 18), value=25), rec(ad.EXERCISE, at(d, 19), value=10),
                        rec(ad.STAND, at(d, 9), at(d, 10), stage="HKCategoryValueAppleStandHourStood"),
                        rec(ad.STAND, at(d, 10), at(d, 11), stage="HKCategoryValueAppleStandHourIdle"),
                        rec(ad.VO2MAX, at(d, 18), value=44.2), rec(ad.WALKING_HR, at(d, 20), value=98),
                        rec(ad.HRV, at(d, 10), value=60), rec(ad.HRV, at(d, 15), value=80),
                        rec(ad.MINDFUL, at(d, 7), at(d, 7.25))])
        got = {m["metric_key"]: m["value"] for m in ad.health_metric_rows(raw, date(2026, 10, 5), date(2026, 10, 5))}
        self.assertEqual(got, {"health.active_energy": 200, "health.exercise_min": 35, "health.stand_hours": 1,
                               "health.vo2max": 44.2, "health.walking_hr": 98, "health.hrv_sdnn_day": 70,
                               "health.mindful_min": 15})
        self.assertEqual(ad.activity_rows(raw, date(2026, 10, 5), date(2026, 10, 5))[0]["active_min"], 35)

    def test_screen_time_counts_overlapping_devices_once(self):
        d = "2026-10-05"
        rows = [dict(rec("", at(d, 10), at(d, 11)), source=ad.SCREEN), dict(rec("", at(d, 10.5), at(d, 11.5)), source=ad.SCREEN),
                dict(rec("", at(d, 23), at(d, 23.5)), source=ad.SCREEN)]
        got = {m["metric_key"]: m["value"] for m in ad.screen_metric_rows(rows, date(2026, 10, 5), date(2026, 10, 5))}
        self.assertEqual(got, {"screen.minutes": 120.0, "screen.late_minutes": 30.0})


ENV = {"NEXT_PUBLIC_SUPABASE_URL": "https://db.test", "SUPABASE_SERVICE_ROLE_KEY": "service-key"}
TABLES = ("profiles", "provider_connections", "connection_streams", "source_records", "sleep_nights", "heart_rate_days",
          "daily_activity", "daily_metrics")


class DeriveApiTests(unittest.TestCase):
    def setUp(self):
        self._old = {k: os.environ.get(k) for k in ENV}
        os.environ.update(ENV)
        self.fake = Fake()
        self.fake.tables = {t: [] for t in TABLES}
        self.fake.tables["profiles"] = [{"user_id": "user-a", "consented_at": "2026-10-01T00:00:00Z"}]
        phone_sync._client = httpx.Client(transport=httpx.MockTransport(self.fake))
        app.dependency_overrides[current_principal] = lambda: Principal(user_id="user-a", store=MemoryStore())
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        phone_sync._client = None
        for k, v in self._old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_derive_fills_the_derived_tables(self):
        d = "2026-10-05"
        self.fake.tables["source_records"] = night() + [
            rec(ad.HR, at(d, 8), value=61, data_type="heart_rate"), rec(ad.STEPS, at(d, 9), value=500, data_type="steps"),
            rec(ad.ENERGY, at(d, 9), value=120, data_type="ah_active_energy_burned"),
            dict(rec("", at(d, 10), at(d, 10.5), data_type="app_usage"), source=ad.SCREEN)]
        r = self.client.post("/api/apple/derive", json={"since": "2026-10-01", "until": "2026-10-06", "timeZone": "Europe/Stockholm"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["stored"], {"nights": 1, "heart_rate_days": 1, "activity_days": 1, "screen_days": 1,
                                              "health_metric_rows": 3})
        t = self.fake.tables
        self.assertEqual(t["sleep_nights"][0]["hrv_sdnn_ms"], 45.0)
        self.assertEqual(t["daily_activity"][0]["steps"], 500)
        self.assertEqual(sorted(m["metric_key"] for m in t["daily_metrics"]),
                         ["health.active_energy", "health.hrv_sdnn_day", "health.hrv_sdnn_day", "screen.late_minutes", "screen.minutes"])
        self.assertEqual(sorted(c["provider"] for c in t["provider_connections"]), ["apple_health", "apple_screen_time"])
        self.assertEqual({s["data_type"] for s in t["connection_streams"]}, {"sleep_session", "heart_rate", "steps", "app_usage"})
        # Running it again replaces the rows instead of adding to them
        self.assertEqual(self.client.post("/api/apple/derive", json={"since": "2026-10-01", "until": "2026-10-06"}).status_code, 200)
        self.assertEqual((len(t["sleep_nights"]), len(t["provider_connections"])), (1, 2))

    def test_needs_consent_and_valid_dates(self):
        self.fake.tables["profiles"][0]["consented_at"] = None
        self.assertEqual(self.client.post("/api/apple/derive", json={}).status_code, 403)
        self.assertEqual(self.client.post("/api/apple/derive", json={"since": "2026-10-05", "until": "2026-10-01"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
