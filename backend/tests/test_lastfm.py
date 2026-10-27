"""Last.fm per-user connections, account isolation, resumable paging, artwork and incremental storage."""
import json
import unittest
from unittest.mock import patch, MagicMock

import httpx
from fastapi.testclient import TestClient

from stressless.connectors.lastfm import API_URL, _album_artwork
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore

CONFIG = {"LASTFM_API_KEY": "test-secret"}
ART = "https://lastfm.freetls.fastly.net/i/u/300x300/cover.jpg"


def track(title="Track", timestamp=1792152000, images=None):
    return {"name": title, "artist": {"#text": "Artist"}, "album": {"#text": "Album"},
            "date": {"uts": str(timestamp)}, "image": images if images is not None else [{"size": "extralarge", "#text": ART}]}


def response(tracks=None, pages=1, page=1):
    return httpx.Response(200, json={"recenttracks": {"@attr": {"totalPages": str(pages), "page": str(page)},
                                                   "track": [track()] if tracks is None else tracks}})


class LastfmTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.user = "owner"
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=self.user, store=self.store)
        self.client = TestClient(app)
        self.config = patch.dict("os.environ", CONFIG)
        self.config.start()
        _album_artwork.cache_clear()
        self.outbound = MagicMock()
        self.http = patch("stressless.connectors.lastfm.httpx.Client")
        self.http.start().return_value.__enter__.return_value = self.outbound
        self.assertEqual(self.connect().status_code, 200)
        self.outbound.reset_mock()

    def connect(self, username="listener", upstream=None):
        self.outbound.get.return_value = upstream or response()
        return self.client.post("/api/media/lastfm/connect", json={"username": username})

    def tearDown(self):
        self.http.stop()
        self.config.stop()
        app.dependency_overrides.clear()

    def sync(self, upstream=None, older=False):
        self.outbound.get.return_value = upstream or response()
        return self.client.post("/api/media/lastfm/sync" + ("?older=true" if older else ""))

    def state(self):
        return next(doc["payload"] for doc in self.store.media_documents() if doc["kind"] == "lastfm_sync")

    def test_each_user_connects_their_own_account(self):
        setup = self.client.get("/api/media/lastfm").json()
        self.assertTrue(setup["connected"])
        self.assertEqual(setup["username"], "listener")
        self.assertNotIn(CONFIG["LASTFM_API_KEY"], json.dumps(setup))
        # A second StressLess user has their own store: not connected until they enter their own username.
        owner_store, self.store = self.store, MemoryStore()
        self.assertFalse(self.client.get("/api/media/lastfm").json()["connected"])
        self.assertEqual(self.sync().status_code, 409)
        self.outbound.get.assert_not_called()
        self.assertEqual(self.connect("second_user").status_code, 200)
        self.assertEqual(self.sync().status_code, 200)
        self.assertEqual(self.outbound.get.call_args.kwargs["params"]["user"], "second_user")
        self.assertEqual(self.state()["username"], "second_user")
        self.store = owner_store
        self.assertEqual(self.client.get("/api/media/lastfm").json()["username"], "listener")
        with patch.dict("os.environ", {"LASTFM_API_KEY": ""}):
            self.assertFalse(self.client.get("/api/media/lastfm").json()["available"])
            self.assertEqual(self.sync().status_code, 503)
        app.dependency_overrides.clear()
        self.assertEqual(self.sync().status_code, 401)

    def test_connect_checks_the_username_with_lastfm(self):
        self.store = MemoryStore()
        self.assertEqual(self.connect("1bad name").status_code, 400)
        self.outbound.get.assert_not_called()
        missing = self.connect("nobody", httpx.Response(200, json={"error": 6, "message": "User not found"}))
        self.assertEqual(missing.status_code, 404)
        self.assertIn("nobody", missing.json()["error"])
        private = self.connect("hidden", httpx.Response(200, json={"error": 17, "message": "Login required"}))
        self.assertEqual(private.status_code, 403)
        self.assertIn("private", private.json()["error"])
        self.assertFalse(self.client.get("/api/media/lastfm").json()["connected"])
        spelled = httpx.Response(200, json={"recenttracks": {"@attr": {"user": "Listener", "totalPages": "1", "page": "1"}, "track": []}})
        self.assertEqual(self.connect("listener", spelled).json()["username"], "Listener")

    def test_dedup_artwork_and_no_engine_or_spotify_replacement(self):
        self.store.replace_media("spotify", [{"id": "song", "provider": "spotify", "occurred_at": "2026-10-01", "title": "Exported song", "minutes": 2}], [])
        playing = {"name": "Still playing", "@attr": {"nowplaying": "true"}}
        with patch("stressless.server.app.session.engine_session", side_effect=AssertionError("No analysis")):
            result = self.sync(response([playing, track(), track()]))
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(self.sync().status_code, 200)
        payload = self.client.get("/api/media").json()
        self.assertEqual(payload["totals"]["lastfm"]["items"], 1)
        self.assertEqual(payload["totals"]["spotify"]["items"], 1)
        event = payload["recent_by_provider"]["lastfm"][0]
        self.assertEqual(event["source"]["artwork_url"], ART)
        self.assertEqual(event["minutes"], 0)
        self.assertFalse(event["source"]["duration_known"])
        self.assertNotIn(CONFIG["LASTFM_API_KEY"], json.dumps(payload))
        args, kwargs = self.outbound.get.call_args
        self.assertEqual(args, (API_URL,))
        self.assertEqual(kwargs["params"]["limit"], 200)
        self.assertEqual(kwargs["params"]["from"], 1792151999)

    def test_history_backfill_uses_fixed_window(self):
        self.assertEqual(self.sync(response(pages=3)).status_code, 200)
        upper = self.state()["history_to"]
        self.assertTrue(self.state()["history_has_more"])
        result = self.sync(response([track("Older", 1700000000)], pages=3, page=2), older=True)
        self.assertEqual(result.status_code, 200, result.text)
        params = self.outbound.get.call_args.kwargs["params"]
        self.assertEqual(params["to"], upper)
        self.assertEqual(params["page"], 2)
        self.assertNotIn("from", params)
        self.assertEqual(self.state()["history_next_page"], 3)
        result = self.sync(response([track("Oldest", 1600000000)], pages=3, page=3), older=True)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(self.state()["history_has_more"])
        self.assertEqual(len(self.store.media_events()), 3)
        self.assertEqual(self.sync(older=True).status_code, 400)

    def test_large_new_backlog_is_resumable_without_skipping(self):
        self.sync()
        self.assertEqual(self.sync(response([track("Newest", 1792200000)], pages=2)).status_code, 200)
        pending = dict(self.state()["pending"])
        self.assertEqual(pending["from"], 1792151999)
        self.assertEqual(pending["page"], 2)
        result = self.sync(response([track("Between", 1792180000)], pages=2, page=2))
        self.assertEqual(result.status_code, 200, result.text)
        params = self.outbound.get.call_args.kwargs["params"]
        self.assertEqual((params["from"], params["to"], params["page"]), (pending["from"], pending["to"], 2))
        self.assertIsNone(self.state()["pending"])
        self.assertEqual(len(self.store.media_events()), 3)

    def test_failures_preserve_saved_rows_and_progress(self):
        self.sync()
        before = (self.store.media_events(), self.store.media_documents())
        cases = [(httpx.Response(200, json={"error": 10, "message": "test-secret"}), 502),
                 (httpx.Response(200, json={"error": 29}), 503), (httpx.Response(429), 503),
                 (httpx.Response(500, text="test-secret"), 502), (httpx.Response(200, text="bad"), 502),
                 (response([{"name": "Missing timestamp"}]), 502)]
        for upstream, expected in cases:
            with self.subTest(expected=expected):
                result = self.sync(upstream)
                self.assertEqual(result.status_code, expected, result.text)
                self.assertNotIn(CONFIG["LASTFM_API_KEY"], result.text)
                self.assertEqual((self.store.media_events(), self.store.media_documents()), before)
        self.outbound.get.side_effect = httpx.TimeoutException("test-secret")
        result = self.sync()
        self.assertEqual(result.status_code, 504)
        self.assertNotIn(CONFIG["LASTFM_API_KEY"], result.text)
        self.assertEqual((self.store.media_events(), self.store.media_documents()), before)

    def test_empty_first_sync_does_not_skip_existing_history(self):
        # e.g. the profile was still hidden: Last.fm answers with an empty list, later with the full history
        self.assertEqual(self.sync(response([], pages=0)).status_code, 200)
        result = self.sync(response([track("Old 1", 1792000000), track("Old 2", 1791000000)]))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotIn("from", self.outbound.get.call_args.kwargs["params"])     # the whole history, not only new
        self.assertEqual(result.json()["totals"]["lastfm"]["items"], 2)
        self.sync(response([track("New", 1792100000)]))
        self.assertEqual(self.outbound.get.call_args.kwargs["params"]["from"], 1791999999)   # incremental from here on

    def test_empty_history_and_unsafe_or_missing_artwork(self):
        self.assertEqual(self.sync(response([], pages=0)).status_code, 200)
        self.assertFalse(self.state()["history_has_more"])
        images = [{"#text": "https://evil.example/track.jpg", "size": "mega"},
                  {"#text": "https://[", "size": "extralarge"},
                  {"#text": "https://lastfm.freetls.fastly.net/i/u/2a96cbd8b46e442fc41c2b86b821562f.png"}]
        result = self.sync(response(track(images=images)))  # also supports singleton JSON track objects
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()["recent_by_provider"]["lastfm"][0]["source"]["artwork_url"])

    def test_switching_accounts_needs_a_disconnect_that_clears_history(self):
        self.sync()
        self.store.replace_media("spotify", [{"id": "song", "provider": "spotify", "occurred_at": "2026-10-01", "title": "Exported song", "minutes": 2}], [])
        self.assertEqual(self.connect("different").status_code, 409)
        self.assertEqual(self.connect("listener").status_code, 200)            # same account: nothing changes
        self.assertEqual(len([e for e in self.store.media_events() if e["provider"] == "lastfm"]), 1)
        result = self.client.post("/api/media/lastfm/disconnect")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()["status"]["connected"])
        self.assertEqual([e["provider"] for e in self.store.media_events()], ["spotify"])
        self.assertFalse([d for d in self.store.media_documents() if d["kind"] == "lastfm_sync"])
        self.assertEqual(self.connect("different").status_code, 200)
        self.assertIsNone(self.state().get("last_synced_at"))                 # a fresh first sync for the new account

    def test_album_cover_fallback_is_cached_and_needs_a_connection(self):
        art = "https://lastfm-img.freetls.fastly.net/i/u/300x300/real-cover.jpg"
        self.outbound.get.return_value = httpx.Response(200, json={"album": {"image": [{"size": "extralarge", "#text": art}]}})
        for _ in range(2):
            result = self.client.get("/api/media/lastfm/artwork?artist=Artist&album=Album")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["artwork_url"], art)
            self.assertNotIn(CONFIG["LASTFM_API_KEY"], result.text)
        self.assertEqual(self.outbound.get.call_count, 1)
        self.assertEqual(self.outbound.get.call_args.kwargs["params"]["method"], "album.getInfo")
        self.store = MemoryStore()
        self.assertEqual(self.client.get("/api/media/lastfm/artwork?artist=Artist&album=Album").status_code, 409)
        self.assertEqual(self.outbound.get.call_count, 1)

    def test_cover_lookup_failure_does_not_break_listening(self):
        self.outbound.get.side_effect = httpx.TimeoutException("test-secret")
        result = self.client.get("/api/media/lastfm/artwork?artist=Artist&album=Album")
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()["artwork_url"])
        self.assertNotIn(CONFIG["LASTFM_API_KEY"], result.text)

    def test_lastfm_is_excluded_from_legacy_media_analysis(self):
        self.sync()
        with patch("stressless.server.app.session.engine_session"), patch("stressless.server.app.analyze_media", return_value={}) as analyze:
            self.assertEqual(self.client.get("/api/media/insights").status_code, 200)
        self.assertEqual(analyze.call_args.args[1], [])
