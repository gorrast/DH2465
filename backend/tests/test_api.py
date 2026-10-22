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

    def test_media_imports_are_normalized_and_user_owned(self):
        spotify = [{"ts": "2026-10-01T12:00:00Z", "master_metadata_track_name": "Song", "master_metadata_artist_name": "Artist", "ms_played": 120000}]
        response = self.client.post("/api/media/import?provider=spotify", files={"files": ("history.json", json.dumps(spotify), "application/json")})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["imported"], 1)
        self.assertEqual(payload["totals"]["spotify"]["items"], 1)
        netflix = "Date,Title,Duration\n2026-10-02,Show,01:30:00\n"
        response = self.client.post("/api/media/import?provider=netflix", files={"files": ("ViewingActivity.csv", netflix, "text/csv")})
        self.assertEqual(response.status_code, 200, response.text)
        media = self.jget("/api/media")
        self.assertEqual(media["total"], 2)
        self.assertEqual(media["totals"]["netflix"]["minutes"], 90)

    def test_spotify_extended_files_and_documents(self):
        music = [{"endTime": "2025-10-10 10:24", "artistName": "Artist", "trackName": "Track", "msPlayed": 72545}]
        podcast = [{"endTime": "2026-01-07 18:32", "podcastName": "Language", "episodeName": "Lesson", "msPlayed": 824372}]
        files = [("files", ("streaming_history_music0.json", json.dumps(music), "application/json")),
                 ("files", ("streaming_history_podcast_0.json", json.dumps(podcast), "application/json"))]
        response = self.client.post("/api/media/import?provider=spotify", files=files)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["imported"], 2)
        self.assertEqual(self.jget("/api/media")["total"], 2)

    def test_spotify_history_is_detected_from_content(self):
        music = [{"endTime": "2025-10-10 10:24", "artistName": "Artist", "trackName": "Track", "msPlayed": 72545}]
        response = self.client.post("/api/media/import?provider=spotify", files={"files": ("export.json", json.dumps(music), "application/json")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["totals"]["spotify"]["items"], 1)

    def test_invalid_or_unrecognized_import_preserves_existing_media(self):
        spotify = [{"ts": "2026-10-01T12:00:00Z", "master_metadata_track_name": "Song", "master_metadata_artist_name": "Artist", "ms_played": 120000}]
        first = self.client.post("/api/media/import?provider=spotify", files={"files": ("history.json", json.dumps(spotify), "application/json")})
        self.assertEqual(first.status_code, 200, first.text)
        response = self.client.post("/api/media/import?provider=spotify", files={"files": ("account.json", "{}", "application/json")})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.jget("/api/media")["total"], 1)
        response = self.client.post("/api/media/import?provider=netflix", files={"files": ("wrong.csv", "Wrong,Headers\nA,B\n", "text/csv")})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.jget("/api/media")["total"], 1)

    def test_netflix_import_preserves_spotify_documents(self):
        spotify = [{"endTime": "2025-10-10 10:24", "artistName": "Artist", "trackName": "Track", "msPlayed": 72545}]
        files = [
            ("files", ("streaming_history_music0.json", json.dumps(spotify), "application/json")),
            ("files", ("TasteProfile.json", json.dumps({"tasteProfile": {"musicalIdentity": "Varied"}}), "application/json")),
        ]
        self.assertEqual(self.client.post("/api/media/import?provider=spotify", files=files).status_code, 200)
        netflix = "Date,Title,Duration\n2026-10-02,Show,01:30:00\n"
        self.assertEqual(self.client.post("/api/media/import?provider=netflix", files={"files": ("ViewingActivity.csv", netflix, "text/csv")}).status_code, 200)
        docs = self.jget("/api/media")["documents"]
        self.assertEqual([doc["kind"] for doc in docs], ["taste_profile"])

    def test_spotify_summary_import_preserves_streaming_history(self):
        music = [{"endTime": "2025-10-10 10:24", "artistName": "Artist", "trackName": "Track", "msPlayed": 72545}]
        history = self.client.post("/api/media/import?provider=spotify", files={"files": ("streaming_history_music0.json", json.dumps(music), "application/json")})
        self.assertEqual(history.status_code, 200, history.text)
        profile = {"tasteProfile": {"musicalIdentity": "Varied"}}
        summary = self.client.post("/api/media/import?provider=spotify", files={"files": ("TasteProfile.json", json.dumps(profile), "application/json")})
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["total"], 1)
        self.assertEqual([doc["kind"] for doc in summary.json()["documents"]], ["taste_profile"])

    def test_media_insights_use_overlapping_health_days(self):
        music = [
            {"endTime": "2026-09-20 21:10", "artistName": "Artist", "trackName": "Track A", "msPlayed": 600000},
            {"endTime": "2026-09-21 18:10", "artistName": "Artist", "trackName": "Track B", "msPlayed": 600000},
            {"endTime": "2026-09-22 21:10", "artistName": "Artist", "trackName": "Track C", "msPlayed": 600000},
            {"endTime": "2026-09-23 18:10", "artistName": "Artist", "trackName": "Track D", "msPlayed": 600000},
        ]
        response = self.client.post("/api/media/import?provider=spotify", files={"files": ("streaming_history_music0.json", json.dumps(music), "application/json")})
        self.assertEqual(response.status_code, 200, response.text)
        insights = self.jget("/api/media/insights")
        self.assertTrue(insights["available"])
        self.assertEqual(insights["overlap_days"], 4)
        self.assertTrue(insights["insights"])
        self.assertEqual(len(insights["chart"]), 4)
        self.assertIn("detail", insights["headline"])


if __name__ == "__main__":
    unittest.main()
