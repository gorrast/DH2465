"""HTTP API tests against an in-process server."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from stressless.server.app import AppState, make_server
from tests.helpers import ANCHOR


def _fail(s):
    raise ValueError("non-finite constant %s" % s)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        cls.state = AppState(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), tempfile.mkdtemp(prefix="sl-test-"), anchor=ANCHOR)
        cls.server = make_server(cls.state, "127.0.0.1", 0)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def get(self, path, expect=200):
        try:
            r = urllib.request.urlopen(self.base + path, timeout=30)
            body, status, ct = r.read(), r.status, r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body, status, ct = e.read(), e.code, e.headers.get("Content-Type", "")
        self.assertEqual(status, expect, "%s -> %s %s" % (path, status, body[:200]))
        return body, ct

    def post(self, path, payload, expect=200):
        req = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            r = urllib.request.urlopen(req, timeout=30); body, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            body, status = e.read(), e.code
        self.assertEqual(status, expect, "%s -> %s %s" % (path, status, body[:200]))
        return json.loads(body.decode(), parse_constant=_fail)

    def jget(self, path, expect=200):
        body, ct = self.get(path, expect)
        self.assertIn("application/json", ct)
        return json.loads(body.decode(), parse_constant=_fail)

    def test_routes_parse_and_shapes(self):
        meta = self.jget("/api/meta"); self.assertEqual(meta["today"], ANCHOR.isoformat()); self.assertEqual(len(meta["personas"]), 3)
        self.assertTrue(self.jget("/api/health")["ok"])
        rep = self.jget("/api/report/%s" % ANCHOR); self.assertGreaterEqual(len(rep["causes"]), 3); self.assertIn("out of sample", rep["confidence_note"])
        body, ct = self.get("/api/report/%s.md" % ANCHOR); self.assertIn("text/markdown", ct); self.assertIn("likely cause", body.decode().lower())
        day = self.jget("/api/day/%s" % (ANCHOR.fromordinal(ANCHOR.toordinal() - 1))); self.assertEqual(len(day["hr"]), 1440); self.assertEqual(len(day["norm"]), 1440)
        self.assertIn("buckets", self.jget("/api/week")); self.assertIn("habits", self.jget("/api/habits"))
        self.assertTrue(self.jget("/api/model?history_days=7")["insufficient"])
        rc = self.jget("/api/reality"); self.assertTrue({"open", "older", "resolved"} <= set(rc))
        val = self.jget("/api/validation"); self.assertGreaterEqual(val["spearman_total"], 0.6)

    def test_errors_and_static(self):
        self.assertIn("No report yet", self.jget("/api/report/2026-12-01", 404)["error"])
        self.jget("/api/nope", 404)
        self.post("/api/whatif", {"mods": []}, 400)
        self.post("/api/reality/rc-nope/answer", {"answer": "yes"}, 404)
        self.get("/../etc/passwd", 403)
        body, ct = self.get("/"); self.assertIn("text/html", ct); self.assertIn(b"StressLess", body)
        body, ct = self.get("/js/core.js"); self.assertIn("javascript", ct)

    def test_demo_path(self):
        rep = self.jget("/api/report/%s" % ANCHOR)
        sid = rep["suggestions"][0]["id"]
        acc = self.post("/api/suggestions/%s/%s/accept" % (ANCHOR, sid), {}); self.assertEqual(acc["event"]["type"], "protected")
        acc2 = self.post("/api/suggestions/%s/%s/accept" % (ANCHOR, sid), {}); self.assertEqual(acc2["event"]["id"], acc["event"]["id"])
        body, ct = self.get("/api/suggestions/%s/%s.ics" % (ANCHOR, sid)); self.assertIn("text/calendar", ct); self.assertTrue(body.startswith(b"BEGIN:VCALENDAR"))
        today = self.jget("/api/day/%s" % ANCHOR)
        self.assertTrue(any(e["id"] == acc["event"]["id"] for e in today["events"]))
        rc = self.jget("/api/reality")
        sb = next(c for c in rc["open"] + rc["older"] if c["kind"] == "seen_not_booked")
        ans = self.post("/api/reality/%s/answer" % sb["id"], {"answer": "yes"})
        self.assertEqual(ans["check"]["status"], "yes"); self.assertIn("habit_after", ans)
        day = self.jget("/api/day/%s" % ans["replay_date"]); self.assertTrue(any(e["source"] == "user" for e in day["events"]))
        late = next(e for e in today["events"] if e["type"] == "meeting" and e["end"][11:13] >= "19")
        w = self.post("/api/whatif", {"date": ANCHOR.isoformat(), "mods": [{"op": "end_at", "event_id": late["id"], "hour": 18}]})
        self.assertGreater(w["delta"], 0); self.assertLessEqual(w["delta_low"], w["delta_high"])

    def test_concurrent_reads_during_write(self):
        def read(_):
            return self.jget("/api/report/%s" % ANCHOR)["score"]
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(read, i) for i in range(20)]
            rc = self.jget("/api/reality")
            booked = [c for c in rc["open"] + rc["older"] if c["kind"] != "seen_not_booked"]
            if booked:
                self.post("/api/reality/%s/answer" % booked[-1]["id"], {"answer": "yes"})
            scores = [f.result() for f in futs]
        self.assertEqual(len(scores), 20)

    def test_persona_switch_and_reset(self):
        m = self.post("/api/persona", {"persona": "sam"}); self.assertEqual(m["persona"]["key"], "sam")
        rep = self.jget("/api/report/%s" % ANCHOR); self.assertGreaterEqual(len(rep["causes"]), 3)
        m2 = self.post("/api/reset", {}); self.assertEqual(m2["persona"]["key"], "alex")


if __name__ == "__main__":
    unittest.main()
