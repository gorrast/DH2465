"""Import small, normalized media listening and viewing histories."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


def _iso(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("media row has no timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _row(provider: str, occurred_at: str, title: str, creator: str, minutes: float, source: Dict[str, Any]) -> Dict[str, Any]:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("media row has no title")
    return {"provider": provider, "occurred_at": occurred_at, "title": clean_title,
            "creator": creator.strip() or None, "minutes": max(0, round(minutes, 2)), "source": source}


def _spotify_time(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 16 and " " in text:
        text += ":00"
    return _iso(text.replace(" ", "T") + "+00:00" if "+" not in text and not text.endswith("Z") else text)


def _spotify(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("Spotify export must be a JSON array")
    rows = []
    for item in data:
        if not isinstance(item, dict) or not item.get("ts") or not item.get("master_metadata_track_name"):
            continue
        rows.append(_row("spotify", _iso(item["ts"]), str(item["master_metadata_track_name"]),
                         str(item.get("master_metadata_artist_name") or ""), float(item.get("ms_played") or 0) / 60000,
                         {"track_uri": item.get("spotify_track_uri"), "reason_end": item.get("reason_end")}))
    return rows


def _spotify_extended(data: Any, podcast: bool) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("Spotify streaming history must be a JSON array")
    rows = []
    for item in data:
        if not isinstance(item, dict) or not item.get("endTime"):
            continue
        title = item.get("episodeName") if podcast else item.get("trackName")
        creator = item.get("podcastName") if podcast else item.get("artistName")
        if not title:
            continue
        rows.append(_row("spotify", _spotify_time(item["endTime"]), str(title), str(creator or ""),
                         float(item.get("msPlayed") or 0) / 60000, {"media_kind": "podcast" if podcast else "music"}))
    return rows


def _document(kind: str, data: Any) -> Dict[str, Any]:
    if kind == "taste_profile":
        taste = data.get("tasteProfile", data) if isinstance(data, dict) else {}
        return {"kind": kind, "taste": {key: taste.get(key) for key in ("musicalIdentity", "podcastTaste", "audiobookTaste", "contentRhythms") if taste.get(key)},
                "artist_count": len(taste.get("artistUris") or [])}
    if kind == "library":
        return {"kind": kind, "albums": data.get("albums") or [], "shows": data.get("shows") or [],
                "saved_track_count": len(data.get("tracks") or []), "followed_artist_count": len(data.get("artists") or [])}
    if kind == "wrapped":
        return {"kind": kind, "yearly_metrics": data.get("yearlyMetrics") or {}, "top_artists": data.get("topArtists") or {},
                "top_podcasts": data.get("topPodcasts") or {}, "top_tracks": data.get("topTracks") or {},
                "top_albums": data.get("topAlbums") or {}, "top_genres": data.get("topGenres") or {},
                "party": data.get("party") or {}, "listening_age": data.get("listeningAge") or {}, "clubs": data.get("clubs") or {}}
    return {"kind": kind}


def _netflix(text: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    headers = {str(header or "").strip().lower() for header in (reader.fieldnames or [])}
    if not {"title", "date"}.issubset(headers):
        raise ValueError("Netflix CSV must include Title and Date columns")
    rows = []
    for item in reader:
        title = str(item.get("Title") or item.get("title") or "").strip()
        when = str(item.get("Date") or item.get("date") or "").strip()
        if not title or not when:
            continue
        try:
            occurred = _iso(when + "T00:00:00+00:00")
        except ValueError:
            continue
        duration = str(item.get("Duration") or item.get("duration") or "0")
        try:
            h, m, s = [int(part) for part in duration.split(":")]
            minutes = h * 60 + m + s / 60
        except ValueError:
            minutes = 0
        rows.append(_row("netflix", occurred, title, "", minutes, {}))
    return rows


def parse_media(provider: str, filename: str, content: bytes) -> List[Dict[str, Any]]:
    provider = provider.lower().strip()
    if provider == "spotify":
        try:
            data = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Spotify export must be valid JSON") from exc
        return _spotify(data)
    if provider == "netflix":
        try:
            return _netflix(content.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise ValueError("Netflix export must be UTF-8 CSV") from exc
    raise ValueError("unsupported media provider %r" % provider)


def parse_spotify_file(filename: str, content: bytes) -> Tuple[List[Dict[str, Any]], Dict[str, Any] | None]:
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Spotify export must be valid JSON") from exc
    name = filename.lower()
    if "streaming_history_music" in name or (isinstance(data, list) and any(isinstance(item, dict) and item.get("trackName") for item in data)):
        return _spotify_extended(data, False), None
    if "streaming_history_podcast" in name or (isinstance(data, list) and any(isinstance(item, dict) and item.get("episodeName") for item in data)):
        return _spotify_extended(data, True), None
    if "tasteprofile" in name:
        return [], _document("taste_profile", data)
    if "yourlibrary" in name:
        return [], _document("library", data)
    if "wrapped" in name:
        return [], _document("wrapped", data)
    if isinstance(data, list) and any(isinstance(item, dict) and item.get("ts") for item in data):
        return _spotify(data), None
    raise ValueError("Unrecognized Spotify export file")
