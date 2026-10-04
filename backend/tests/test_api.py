"""HTTP API tests against the FastAPI app, with an in-memory store standing in for Supabase."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from stressless.server import session
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore
from tests.helpers import ANCHOR


def _fail(s):
    raise ValueError("non-finite constant %s" % s)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_anchor = os.environ.get("STRESSLESS_ANCHOR")
        os.environ["STRESSLESS_ANCHOR"] = ANCHOR.isoformat()
        cls.stores = {}
        app.dependency_overrides[current_principal] = cls._principal
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        if cls._old_anchor is None:
            os.environ.pop("STRESSLESS_ANCHOR", None)
        else:
            os.environ["STRESSLESS_ANCHOR"] = cls._old_anchor

    user = "user-a"

    @classmethod
    def _principal(cls):
        store = cls.stores.setdefault(cls.user, MemoryStore())
        return Principal(user_id=cls.user, store=store)

    def setUp(self):
        type(self).user = "user-" + self._testMethodName

    def get(self, path, expect=200):
        r = self.client.get(path)
        self.assertEqual(r.status_code, expect, "%s -> %s %s" % (path, r.status_code, r.text[:200]))
        return r

    def post(self, path, payload, expect=200):
        r = self.client.post(path, json=payload)
        self.assertEqual(r.status_code, expect, "%s -> %s %s" % (path, r.status_code, r.text[:200]))
        return json.loads(r.text, parse_constant=_fail)

    def jget(self, path, expect=200):
        r = self.get(path, expect)
        self.assertIn("application/json", r.headers["content-type"])
        return json.loads(r.text, parse_constant=_fail)

    def test_routes_parse_and_shapes(self):
        meta = self.jget("/api/meta"); self.assertEqual(meta["today"], ANCHOR.isoformat()); self.assertEqual(len(meta["personas"]), 3)
        self.assertTrue(meta["anchor_mode"])
        self.assertTrue(self.jget("/api/health")["ok"])
        rep = self.jget("/api/report/%s" % ANCHOR); self.assertGreaterEqual(len(rep["causes"]), 3); self.assertIn("out of sample", rep["confidence_note"])
        r = self.get("/api/report/%s.md" % ANCHOR); self.assertIn("text/markdown", r.headers["content-type"]); self.assertIn("likely cause", r.text.lower())
        day = self.jget("/api/day/%s" % (ANCHOR.fromordinal(ANCHOR.toordinal() - 1))); self.assertEqual(len(day["hr"]), 1440); self.assertEqual(len(day["norm"]), 1440)
        self.assertIn("buckets", self.jget("/api/week")); self.assertIn("habits", self.jget("/api/habits"))
        self.assertTrue(self.jget("/api/model?history_days=7")["insufficient"])
        rc = self.jget("/api/reality"); self.assertTrue({"open", "older", "resolved"} <= set(rc))
        val = self.jget("/api/validation"); self.assertGreaterEqual(val["spearman_total"], 0.6)

    def test_errors(self):
        self.assertIn("No report yet", self.jget("/api/report/2026-12-01", 404)["error"])
        self.assertIn("Bad date", self.jget("/api/report/not-a-date", 400)["error"])
        self.assertIn("no such route", self.jget("/api/nope", 404)["error"])
        self.post("/api/whatif", {"mods": []}, 400)
        self.post("/api/reality/rc-nope/answer", {"answer": "yes"}, 404)

    def test_requires_sign_in(self):
        saved = app.dependency_overrides.pop(current_principal)
        try:
            r = self.client.get("/api/meta"); self.assertEqual(r.status_code, 401); self.assertIn("error", r.json())
            r = self.client.get("/api/meta", headers={"Authorization": "Bearer not-a-jwt"}); self.assertEqual(r.status_code, 401)
            self.assertEqual(self.client.get("/api/health").status_code, 200)
        finally:
            app.dependency_overrides[current_principal] = saved

    def test_demo_path(self):
        rep = self.jget("/api/report/%s" % ANCHOR)
        sid = rep["suggestions"][0]["id"]
        acc = self.post("/api/suggestions/%s/%s/accept" % (ANCHOR, sid), {}); self.assertEqual(acc["event"]["type"], "protected")
        acc2 = self.post("/api/suggestions/%s/%s/accept" % (ANCHOR, sid), {}); self.assertEqual(acc2["event"]["id"], acc["event"]["id"])
        r = self.get("/api/suggestions/%s/%s.ics" % (ANCHOR, sid)); self.assertIn("text/calendar", r.headers["content-type"]); self.assertTrue(r.text.startswith("BEGIN:VCALENDAR"))
        today = self.jget("/api/day/%s" % ANCHOR)
        self.assertTrue(any(e["id"] == acc["event"]["id"] for e in today["events"]))
        self.assertTrue(self.jget("/api/report/%s" % ANCHOR)["suggestions"][0]["accepted"])
        rc = self.jget("/api/reality")
        sb = next(c for c in rc["open"] + rc["older"] if c["kind"] == "seen_not_booked")
        ans = self.post("/api/reality/%s/answer" % sb["id"], {"answer": "yes"})
        self.assertEqual(ans["check"]["status"], "yes"); self.assertIn("habit_after", ans)
        day = self.jget("/api/day/%s" % ans["replay_date"]); self.assertTrue(any(e["source"] == "user" for e in day["events"]))
        late = next(e for e in today["events"] if e["type"] == "meeting" and e["end"][11:13] >= "19")
        w = self.post("/api/whatif", {"date": ANCHOR.isoformat(), "mods": [{"op": "end_at", "event_id": late["id"], "hour": 18}]})
        self.assertGreater(w["delta"], 0); self.assertLessEqual(w["delta_low"], w["delta_high"])

    def test_state_survives_a_cold_engine_cache(self):
        rc = self.jget("/api/reality")
        sb = next(c for c in rc["open"] + rc["older"] if c["kind"] == "seen_not_booked")
        self.post("/api/reality/%s/answer" % sb["id"], {"answer": "yes"})
        session._engines.drop(lambda k: True)          # a fresh function instance
        resolved = self.jget("/api/reality")["resolved"]
        self.assertTrue(any(c["id"] == sb["id"] and c["status"] == "yes" for c in resolved))

    def test_users_are_isolated(self):
        rc = self.jget("/api/reality")
        sb = next(c for c in rc["open"] + rc["older"] if c["kind"] == "seen_not_booked")
        self.post("/api/reality/%s/answer" % sb["id"], {"answer": "yes"})
        type(self).user = "someone-else"
        self.assertEqual(self.jget("/api/reality")["resolved"], [])
        self.assertEqual(self.jget("/api/meta")["persona"]["key"], "alex")

    def test_concurrent_reads_during_write(self):
        def read(_):
            return self.client.get("/api/report/%s" % ANCHOR).json()["score"]
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(read, i) for i in range(20)]
            rc = self.jget("/api/reality")
            booked = [c for c in rc["open"] + rc["older"] if c["kind"] != "seen_not_booked"]
            if booked:
                self.post("/api/reality/%s/answer" % booked[-1]["id"], {"answer": "yes"})
            scores = [f.result() for f in futs]
        self.assertEqual(len(scores), 20)

    def test_persona_switch_and_reset(self):
        rc = self.jget("/api/reality")
        sb = next(c for c in rc["open"] + rc["older"] if c["kind"] == "seen_not_booked")
        self.post("/api/reality/%s/answer" % sb["id"], {"answer": "yes"})
        m = self.post("/api/persona", {"persona": "sam"}); self.assertEqual(m["persona"]["key"], "sam")
        self.assertEqual(self.jget("/api/reality")["resolved"], [])  # switching identity clears answers
        rep = self.jget("/api/report/%s" % ANCHOR); self.assertGreaterEqual(len(rep["causes"]), 3)
        self.post("/api/persona", {"persona": "nobody"}, 400)
        m2 = self.post("/api/reset", {}); self.assertEqual(m2["persona"]["key"], "alex"); self.assertEqual(m2["seed"], 7)


if __name__ == "__main__":
    unittest.main()
