"""Media export edge cases and full-history database retrieval."""
import json
import unittest
import httpx
from unittest.mock import patch

from stressless.connectors.media import parse_media, parse_steam_file
from stressless.store.supabase import SupabaseStore, SupabaseError


class MediaTests(unittest.TestCase):
    def test_bulk_import_has_scoped_timeout_and_never_retries_uncertain_write(self):
        store = SupabaseStore("https://example.invalid", "test", "test", "test")
        with patch("stressless.store.supabase._http") as client:
            client.return_value.request.return_value = httpx.Response(200, json=None)
            store.replace_media("youtube", [{"id": "test"}], [])
            self.assertEqual(client.return_value.request.call_args.kwargs["timeout"], 120.0)
            store.media_documents()
            self.assertNotIn("timeout", client.return_value.request.call_args.kwargs)
        with patch("stressless.store.supabase._http") as client:
            client.return_value.request.side_effect = httpx.ReadTimeout("timed out")
            with self.assertRaisesRegex(SupabaseError, "may still finish"):
                store.replace_media("youtube", [], [])
            self.assertEqual(client.return_value.request.call_count, 1)

    def test_netflix_preserves_missing_titles_and_same_day_rewatches(self):
        rows = parse_media("netflix", "profile.csv", b' TITLE , DATE \n" ",10/17/26\nShow,10/17/26\nShow,10/17/26\n')
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["title"], "Title unavailable")
        self.assertTrue(rows[0]["source"]["title_unavailable"])
        self.assertEqual([row["source"]["occurrence"] for row in rows[1:]], [1, 2])

    def test_youtube_takeout_filters_activity_and_preserves_timestamps(self):
        data = [
            {"title": "Watched Test video", "titleUrl": "https://www.youtube.com/watch?v=abcdefghijk", "time": "2026-10-21T21:30:00+02:00", "subtitles": [{"name": "A creator"}]},
            {"title": "Searched for cats", "titleUrl": "https://www.youtube.com/results?search_query=cats", "time": "2026-10-21T19:00:00Z"},
            {"title": "Visited a channel", "titleUrl": "https://www.youtube.com/@creator", "time": "2026-10-21T19:00:00Z"},
            {"title": "Watched unavailable video", "time": "2026-10-21T19:00:00Z"},
            {"title": "Watched evil", "titleUrl": "javascript:alert(1)", "time": "2026-10-21T19:00:00Z"},
        ]
        rows = parse_media("youtube", "watch-history.json", json.dumps(data).encode())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "Test video")
        self.assertEqual(rows[0]["creator"], "A creator")
        self.assertEqual(rows[0]["occurred_at"], "2026-10-21T19:30:00+00:00")
        self.assertEqual(rows[0]["minutes"], 0)
        self.assertFalse(rows[0]["source"]["duration_known"])
        self.assertIn("i.ytimg.com/vi/abcdefghijk", rows[0]["source"]["artwork_url"])
        self.assertNotIn("url", rows[1]["source"])

    def test_youtube_swedish_and_english_ads_and_prefixes(self):
        base = {"titleUrl": "https://www.youtube.com/watch?v=abcdefghijk", "time": "2026-10-21T19:00:00Z"}
        data = [{**base, "title": "Tittade på Normal video"},
                {**base, "title": "Watched Another video"},
                {**base, "title": "Tittade på Annons", "details": [{"name": "Från en annons på Google"}]},
                {**base, "title": "Watched Ad", "details": [{"name": "From Google Ads"}]},
                {**base, "title": "A video about ads", "details": [{"name": "Something else"}]}]
        rows = parse_media("youtube", "watch-history.json", json.dumps(data).encode())
        self.assertEqual([row["title"] for row in rows], ["Normal video", "Another video", "A video about ads"])

    def test_youtube_invalid_export_does_not_silently_drop_bad_timestamps(self):
        for data in (b'not json', b'{}', json.dumps([{"title": "Watched Video", "time": "bad"}]).encode()):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_media("youtube", "watch-history.json", data)

    def test_steam_last_played_and_invalid_values(self):
        game = {"appid": 10, "name": "Game", "playtime_forever": 60, "rtime_last_played": 1792152000}
        result = parse_steam_file(json.dumps({"games": [game]}).encode())
        self.assertTrue(result["games"][0]["last_played"].startswith("2026-10-16"))
        for value in (-1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_steam_file(json.dumps({"games": [{**game, "playtime_forever": value}]}).encode())

    def test_supabase_reads_past_default_response_cap(self):
        store = SupabaseStore("https://example.invalid", "test", "test", "test")
        with patch.object(store, "_call", side_effect=[[{"id": str(i)} for i in range(1000)], [{"id": "1000"}]]) as call:
            self.assertEqual(len(store.media_events()), 1001)
        self.assertEqual(call.call_args_list[1].kwargs["params"]["offset"], "1000")
        self.assertEqual(call.call_args_list[0].kwargs["params"]["order"], "occurred_at.desc,id.desc")
