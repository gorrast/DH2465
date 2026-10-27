"""Steam sync: account binding, upstream failures, safe persistence and key handling."""
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from stressless.connectors.steam import LIBRARY_URL
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore

CONFIG = {"STEAM_WEB_API_KEY": "secret-test-key", "STEAM_ID": "76561198000000000", "STEAM_SYNC_USER_ID": "owner"}
LIBRARY = {"response": {"game_count": 1, "games": [{"appid": 10, "name": "A game", "playtime_forever": 120, "playtime_2weeks": 30}]}}


class SteamSyncTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.user = "owner"
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=self.user, store=self.store)
        self.client = TestClient(app)
        self.config = patch.dict("os.environ", CONFIG)
        self.config.start()

    def tearDown(self):
        self.config.stop()
        app.dependency_overrides.clear()

    def test_setup_and_account_binding(self):
        with patch("stressless.connectors.steam.httpx.get") as fetch:
            setup = self.client.get("/api/media/steam").json()
            self.assertTrue(setup["configured"])
            self.assertNotIn(CONFIG["STEAM_WEB_API_KEY"], json.dumps(setup))
            self.user = "someone-else"
            setup = self.client.get("/api/media/steam").json()
            self.assertFalse(setup["configured"])
            self.assertIsNone(setup["steam_id"])
            self.assertEqual(self.client.post("/api/media/steam/sync").status_code, 403)
            fetch.assert_not_called()

    def test_missing_config_and_invalid_steam_id(self):
        for changes in ({"STEAM_WEB_API_KEY": ""}, {"STEAM_ID": "my-profile"}, {"STEAM_SYNC_USER_ID": ""}):
            with self.subTest(changes=changes), patch.dict("os.environ", changes), patch("stressless.connectors.steam.httpx.get") as fetch:
                self.assertFalse(self.client.get("/api/media/steam").json()["configured"])
                self.assertEqual(self.client.post("/api/media/steam/sync").status_code, 503)
                fetch.assert_not_called()

    def test_sync_replaces_just_steam_without_engine_or_url_secrets(self):
        self.store.replace_media("spotify", [{"id": "song", "provider": "spotify", "occurred_at": "2026-10-01T00:00:00Z", "title": "Song", "minutes": 2}],
                                 [{"id": "taste", "filename": "TasteProfile.json", "kind": "taste_profile", "payload": {}}])
        with patch("stressless.connectors.steam.httpx.get", return_value=httpx.Response(200, json=LIBRARY)) as fetch, patch("stressless.server.app.session.engine_session", side_effect=AssertionError("No media analysis")):
            for _ in range(2):
                response = self.client.post("/api/media/steam/sync")
                self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["totals"]["spotify"]["items"], 1)
        self.assertEqual(len(response.json()["documents"]), 2)
        document = next(doc for doc in response.json()["documents"] if doc["kind"] == "steam_library")
        self.assertEqual(document["payload"]["origin"], "steam_api")
        self.assertEqual(document["payload"]["games"][0]["minutes"], 120)
        self.assertNotIn(CONFIG["STEAM_WEB_API_KEY"], response.text)
        args, kwargs = fetch.call_args
        self.assertEqual(args, (LIBRARY_URL,))
        self.assertEqual(kwargs["headers"]["x-webapi-key"], CONFIG["STEAM_WEB_API_KEY"])
        self.assertNotIn(CONFIG["STEAM_WEB_API_KEY"], json.dumps(kwargs["params"]))
        self.assertTrue(json.loads(kwargs["params"]["input_json"])["include_appinfo"])

    def test_failed_sync_preserves_previous_snapshot(self):
        self.store.replace_media("steam", [], [{"id": "saved", "kind": "steam_library", "payload": {"games": [{"name": "Saved game"}]}}])
        before = self.store.media_documents()
        responses = [(httpx.Response(200, json={"response": {}}), 502),
                     (httpx.Response(200, json={"response": {"games": [{"appid": 10, "playtime_forever": -1}]}}), 502),
                     (httpx.Response(200, text="not json"), 502),
                     (httpx.Response(403, text="secret-test-key"), 502),
                     (httpx.Response(429), 503), (httpx.Response(500), 502)]
        for upstream, expected in responses:
            with self.subTest(status=upstream.status_code), patch("stressless.connectors.steam.httpx.get", return_value=upstream):
                response = self.client.post("/api/media/steam/sync")
                self.assertEqual(response.status_code, expected, response.text)
                self.assertNotIn(CONFIG["STEAM_WEB_API_KEY"], response.text)
                self.assertEqual(self.store.media_documents(), before)
        for error, expected in ((httpx.TimeoutException("secret-test-key"), 504), (httpx.ConnectError("secret-test-key"), 502)):
            with patch("stressless.connectors.steam.httpx.get", side_effect=error):
                response = self.client.post("/api/media/steam/sync")
                self.assertEqual(response.status_code, expected)
                self.assertNotIn(CONFIG["STEAM_WEB_API_KEY"], response.text)
                self.assertEqual(self.store.media_documents(), before)

    def test_explicit_empty_library_and_missing_auth(self):
        with patch("stressless.connectors.steam.httpx.get", return_value=httpx.Response(200, json={"response": {"game_count": 0}})):
            response = self.client.post("/api/media/steam/sync")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["documents"][0]["payload"]["games"], [])
        app.dependency_overrides.clear()
        with patch("stressless.connectors.steam.httpx.get") as fetch:
            self.assertEqual(self.client.post("/api/media/steam/sync").status_code, 401)
            self.assertEqual(self.client.get("/api/media/steam").status_code, 401)
            fetch.assert_not_called()
