"""Automatic Steam artwork and bounded, authenticated Netflix poster enrichment."""
import json
import unittest
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from stressless.connectors.media import parse_steam_file
from stressless.connectors.media_artwork import _poster, netflix_query
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore


def catalogue(name="The Mentalist", media_type="tv", tmdb_id=5920):
    return {"id": tmdb_id, "media_type": media_type, "name": name, "original_name": name,
            "poster_path": "/poster.jpg", "adult": False}


class MediaArtworkTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.user = "owner"
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=self.user, store=self.store)
        self.client = TestClient(app)
        self.config = patch.dict("os.environ", {"TMDB_READ_ACCESS_TOKEN": "private-tmdb-token", "TMDB_LANGUAGE": "en-US"})
        self.config.start()
        _poster.cache_clear()
        self.outbound = MagicMock()
        self.outbound.get.return_value = httpx.Response(200, json={"results": [catalogue()]})
        self.http = patch("stressless.connectors.media_artwork.httpx.Client")
        self.http.start().return_value.__enter__.return_value = self.outbound

    def tearDown(self):
        self.http.stop()
        self.config.stop()
        app.dependency_overrides.clear()

    def import_history(self, text=None):
        text = text or 'Title,Date\n"The Mentalist: Season 1: Pilot",10/17/26\n"The Mentalist: Season 1: Red Tide",10/17/26\n'
        result = self.client.post("/api/media/import?provider=netflix", files={"files": ("profile.csv", text, "text/csv")})
        self.assertEqual(result.status_code, 200, result.text)
        return result

    def test_queries_keep_show_names_and_preserve_colon_movie_candidates(self):
        self.assertEqual(json.loads(netflix_query("The Mentalist: Season 1: Pilot")), ["tv", "The Mentalist"])
        self.assertEqual(json.loads(netflix_query("Show: Säsong 2: Avsnitt 1")), ["tv", "Show"])
        self.assertEqual(json.loads(netflix_query("Movie: Subtitle")), [None, "Movie: Subtitle", "Movie"])
        self.assertIsNone(netflix_query("Title unavailable"))

    def test_steam_import_attaches_artwork_without_extra_api_calls(self):
        document = parse_steam_file(json.dumps({"games": [{"appid": 620, "name": "Portal 2", "playtime_forever": 30}]}).encode())
        self.assertEqual(document["games"][0]["artwork_url"], "https://cdn.akamai.steamstatic.com/steam/apps/620/header.jpg")
        self.outbound.get.assert_not_called()

    def test_enrichment_updates_all_show_episodes_and_preserves_history(self):
        original = self.import_history().json()["recent_by_provider"]["netflix"]
        self.outbound.get.assert_not_called()  # External lookup starts with the post-import artwork action.
        with patch("stressless.server.app.session.engine_session", side_effect=AssertionError("No analysis")):
            response = self.client.post("/api/media/netflix/artwork")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["has_more"])
        self.assertEqual(len(response.json()["updates"]), 1)
        self.assertEqual(self.outbound.get.call_count, 1)
        events = self.client.get("/api/media").json()["recent_by_provider"]["netflix"]
        for before, after in zip(original, events):
            for field in ("id", "title", "occurred_at", "minutes"):
                self.assertEqual(before[field], after[field])
            self.assertEqual(after["source"]["profile"], "profile.csv")
            self.assertEqual(after["source"]["artwork_url"], "https://image.tmdb.org/t/p/w342/poster.jpg")
        args, kwargs = self.outbound.get.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer private-tmdb-token")
        self.assertNotIn("private-tmdb-token", response.text)
        self.assertNotIn("private-tmdb-token", json.dumps(kwargs["params"]))
        self.client.get("/api/media")
        self.assertEqual(self.outbound.get.call_count, 1)  # Page reads do not query TMDB.

    def test_ambiguous_matches_and_missing_posters_stay_unmatched(self):
        for results in ([catalogue(), catalogue(tmdb_id=999)], [{**catalogue(), "poster_path": None}], [catalogue("Different show")], [catalogue(media_type="movie")]):
            with self.subTest(results=results):
                _poster.cache_clear()
                self.import_history()
                self.outbound.get.return_value = httpx.Response(200, json={"results": results})
                response = self.client.post("/api/media/netflix/artwork")
                self.assertFalse(response.json()["has_more"])
                source = self.store.media_events()[0]["source"]
                self.assertEqual(source["artwork_status"], "unmatched")
                self.assertNotIn("artwork_url", source)

    def test_failures_leave_imported_history_pending_and_retryable(self):
        self.import_history()
        before = self.store.media_events()
        self.outbound.get.return_value = httpx.Response(401, text="private-tmdb-token")
        response = self.client.post("/api/media/netflix/artwork")
        self.assertTrue(response.json()["has_more"])
        self.assertTrue(response.json()["error"])
        self.assertNotIn("private-tmdb-token", response.text)
        self.assertEqual(self.store.media_events(), before)
        self.outbound.get.return_value = httpx.Response(200, json={"results": [catalogue()]})
        self.assertFalse(self.client.post("/api/media/netflix/artwork").json()["has_more"])

    def test_batches_are_bounded_and_cannot_change_another_user(self):
        self.import_history('Title,Date\n' + ''.join('Show %s: Season 1: Pilot,10/17/26\n' % i for i in range(8)))
        self.outbound.get.return_value = httpx.Response(200, json={"results": []})
        response = self.client.post("/api/media/netflix/artwork")
        self.assertEqual(len(response.json()["updates"]), 4)
        self.assertTrue(response.json()["has_more"])
        self.assertEqual(self.outbound.get.call_count, 4)
        other_store = MemoryStore()
        self.user = "other"
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=self.user, store=other_store)
        self.client.post("/api/media/netflix/artwork")
        self.assertEqual(len(self.store.pending_netflix_artwork()), 4)
        self.assertEqual(other_store.media_events(), [])

    def test_missing_token_and_missing_auth_do_not_fetch(self):
        self.import_history()
        with patch.dict("os.environ", {"TMDB_READ_ACCESS_TOKEN": ""}):
            self.assertFalse(self.client.get("/api/media/netflix/artwork").json()["configured"])
            self.assertEqual(self.client.post("/api/media/netflix/artwork").status_code, 503)
        app.dependency_overrides.clear()
        self.assertEqual(self.client.post("/api/media/netflix/artwork").status_code, 401)
        self.outbound.get.assert_not_called()
