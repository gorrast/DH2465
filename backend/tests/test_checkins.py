"""Check-ins: GET/POST /api/checkins against a fake PostgREST (daily_metrics, source manual)."""
import os
import unittest
from datetime import timedelta
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from stressless.server import phone_sync
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore
from tests.helpers import ANCHOR
from tests.test_calendar import Fake
from tests.test_device_sync import ENV

YESTERDAY = (ANCHOR - timedelta(days=1)).isoformat()


class CheckinApiTests(unittest.TestCase):
    user = "user-a"

    def setUp(self):
        self._env = mock.patch.dict(os.environ, dict(ENV, STRESSLESS_ANCHOR=ANCHOR.isoformat()))
        self._env.start()
        self.fake = Fake()
        self.fake.tables = {"profiles": [{"user_id": "user-a", "consented_at": "2026-09-01T00:00:00Z"},
                                         {"user_id": "user-b", "consented_at": None}],
                            "daily_metrics": [{"user_id": "user-a", "day": YESTERDAY, "metric_key": "screen.minutes",
                                               "value": 120.0, "source": "screen_time"}]}
        phone_sync._client = httpx.Client(transport=httpx.MockTransport(self.fake))
        type(self).user = "user-a"
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=type(self).user, store=MemoryStore())
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        phone_sync._client = None
        self._env.stop()

    def mine(self):
        return sorted((r["day"], r["metric_key"], r["value"]) for r in self.fake.tables["daily_metrics"]
                      if r["user_id"] == "user-a" and r["source"] == "manual")

    def test_save_read_change_and_clear(self):
        r = self.client.post("/api/checkins/" + YESTERDAY, json={"coffee_cups": 3, "alcohol_units": 2.5})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.mine(), [(YESTERDAY, "intake.alcohol_units", 2.5), (YESTERDAY, "intake.coffee_cups", 3.0)])
        days = {d["day"]: d for d in r.json()["days"]}
        self.assertEqual(len(days), 14)
        self.assertEqual((days[YESTERDAY]["coffee_cups"], days[YESTERDAY]["alcohol_units"]), (3.0, 2.5))
        self.assertIsNone(days[ANCHOR.isoformat()]["coffee_cups"])                # not logged is not zero

        self.client.post("/api/checkins/" + YESTERDAY, json={"coffee_cups": 1})   # alcohol left alone
        self.client.post("/api/checkins/" + YESTERDAY, json={"alcohol_units": None})
        self.assertEqual(self.mine(), [(YESTERDAY, "intake.coffee_cups", 1.0)])
        got = {d["day"]: d for d in self.client.get("/api/checkins").json()["days"]}[YESTERDAY]
        self.assertEqual((got["coffee_cups"], got["alcohol_units"]), (1.0, None))
        self.assertEqual(len(self.fake.tables["daily_metrics"]), 2)               # screen time untouched

    def test_validation(self):
        for day, body in ((YESTERDAY, {"coffee_cups": -1}), (YESTERDAY, {"alcohol_units": 99}), (YESTERDAY, {"coffee_cups": "2"}),
                          (YESTERDAY, {}), ((ANCHOR + timedelta(days=1)).isoformat(), {"coffee_cups": 1}),
                          ((ANCHOR - timedelta(days=30)).isoformat(), {"coffee_cups": 1}), ("nope", {"coffee_cups": 1})):
            self.assertEqual(self.client.post("/api/checkins/" + day, json=body).status_code, 400, (day, body))
        self.assertEqual(self.mine(), [])

    def test_needs_consent(self):
        type(self).user = "user-b"
        self.assertEqual(self.client.post("/api/checkins/" + YESTERDAY, json={"coffee_cups": 1}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
