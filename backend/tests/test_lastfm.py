"""Last.fm account isolation, resumable paging, artwork and incremental storage."""
import json
import unittest
from unittest.mock import patch, MagicMock

import httpx
from fastapi.testclient import TestClient

from stressless.connectors.lastfm import API_URL, _album_artwork
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore

CONFIG = {"LASTFM_API_KEY": "test-secret", "LASTFM_USERNAME": "listener", "LASTFM_SYNC_USER_ID": "owner"}
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

    def tearDown(self):
        self.http.stop()
        self.config.stop()
        app.dependency_overrides.clear()

    def sync(self, upstream=None, older=False):
        self.outbound.get.return_value = upstream or response()
        return self.client.post("/api/media/lastfm/sync" + ("?older=true" if older else ""))

    def state(self):
        return next(doc["payload"] for doc in self.store.media_documents() if doc["kind"] == "lastfm_sync")

    def test_config_account_binding_and_auth(self):
        setup = self.client.get("/api/media/lastfm").json()
        self.assertTrue(setup["configured"])
        self.assertNotIn(CONFIG["LASTFM_API_KEY"], json.dumps(setup))
        self.user = "other"
        self.assertFalse(self.client.get("/api/media/lastfm").json()["configured"])
        self.assertEqual(self.sync().status_code, 403)
        self.outbound.get.assert_not_called()
        self.user = "owner"
        with patch.dict("os.environ", {"LASTFM_API_KEY": ""}):
            self.assertEqual(self.sync().status_code, 503)
        app.dependency_overrides.clear()
        self.assertEqual(self.sync().status_code, 401)
        self.outbound.get.assert_not_called()

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

    def test_empty_history_and_unsafe_or_missing_artwork(self):
        self.assertEqual(self.sync(response([], pages=0)).status_code, 200)
        self.assertFalse(self.state()["history_has_more"])
        images = [{"#text": "https://evil.example/track.jpg", "size": "mega"},
                  {"#text": "https://[", "size": "extralarge"},
                  {"#text": "https://lastfm.freetls.fastly.net/i/u/2a96cbd8b46e442fc41c2b86b821562f.png"}]
        result = self.sync(response(track(images=images)))  # also supports singleton JSON track objects
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()["recent_by_provider"]["lastfm"][0]["source"]["artwork_url"])

    def test_switching_usernames_does_not_mix_accounts(self):
        self.sync()
        self.outbound.get.reset_mock()
        with patch.dict("os.environ", {"LASTFM_USERNAME": "different-profile"}):
            self.assertEqual(self.sync().status_code, 409)
        self.outbound.get.assert_not_called()

    def test_album_cover_fallback_is_cached_and_owner_only(self):
        art = "https://lastfm-img.freetls.fastly.net/i/u/300x300/real-cover.jpg"
        self.outbound.get.return_value = httpx.Response(200, json={"album": {"image": [{"size": "extralarge", "#text": art}]}})
        for _ in range(2):
            result = self.client.get("/api/media/lastfm/artwork?artist=Artist&album=Album")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["artwork_url"], art)
            self.assertNotIn(CONFIG["LASTFM_API_KEY"], result.text)
        self.assertEqual(self.outbound.get.call_count, 1)
        self.assertEqual(self.outbound.get.call_args.kwargs["params"]["method"], "album.getInfo")
        self.user = "other"
        self.assertEqual(self.client.get("/api/media/lastfm/artwork?artist=Artist&album=Album").status_code, 403)
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
