"""Import small, normalized media listening and viewing histories."""
from __future__ import annotations

import csv
import io
import json
import math
import re
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from .media_artwork import netflix_query


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


def _netflix(text: str, filename: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    headers = {str(header or "").strip().lower() for header in (reader.fieldnames or [])}
    if not {"title", "date"}.issubset(headers):
        raise ValueError("Netflix CSV must include Title and Date columns")
    rows = []
    occurrences: Dict[tuple[str, str], int] = {}
    for number, raw in enumerate(reader, start=2):
        item = {str(key or "").strip().lower(): value for key, value in raw.items()}
        title = str(item.get("title") or "").strip()
        when = str(item.get("date") or "").strip()
        if not when:
            raise ValueError("Netflix row %s needs a Date" % number)
        # Netflix sometimes exports a blank title for removed/unavailable content.
        title_unavailable = not title
        title = title or "Title unavailable"
        parsed = None
        for pattern in ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y"):
            try:
                parsed = datetime.strptime(when, pattern).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                pass
        if parsed is None:
            raise ValueError("Netflix row %s has an unsupported date; use M/D/YY or YYYY-MM-DD" % number)
        occurred = parsed.isoformat(timespec="seconds")
        identity = (title, occurred)
        occurrences[identity] = occurrences.get(identity, 0) + 1
        duration = str(item.get("duration") or "")
        try:
            h, m, s = [int(part) for part in duration.split(":")]
            if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
                raise ValueError()
            minutes = h * 60 + m + s / 60
        except ValueError:
            if duration:
                raise ValueError("Netflix row %s has an invalid Duration; use HH:MM:SS" % number)
            minutes = 0
        rows.append(_row("netflix", occurred, title, "", minutes,
                         {"date_only": True, "duration_known": bool(duration), "title_unavailable": title_unavailable,
                          "profile": filename, "occurrence": occurrences[identity], "artwork_query": netflix_query(title)}))
    return rows


def _youtube(content: bytes, filename: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(content.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('YouTube export must be valid UTF-8 JSON') from exc
    if not isinstance(data, list):
        raise ValueError('Choose the watch-history.json array from Google Takeout')
    rows = []
    for number, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        details = item.get('details')
        ad_markers = {'from google ads', 'from a google ad', 'från en annons på google'}
        if isinstance(details, list) and any(
            isinstance(detail, dict) and str(detail.get('name') or '').strip().casefold() in ad_markers
            for detail in details
        ):
            continue
        raw_url = str(item.get('titleUrl') or '')
        url = urlparse(raw_url)
        video_id = None
        if url.scheme == 'https' and url.hostname in ('www.youtube.com', 'youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'):
            if url.hostname == 'youtu.be':
                video_id = url.path.strip('/')
            elif url.path == '/watch':
                video_id = parse_qs(url.query).get('v', [None])[0]
            elif url.path.startswith('/shorts/'):
                video_id = url.path.split('/')[2]
        if video_id and not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            video_id = None
        title = str(item.get('title') or '').strip()
        # Search, subscription and channel activity must not become watched videos.
        unavailable = not raw_url and title.startswith(('Watched ', 'Tittade på '))
        if not video_id and not unavailable:
            continue
        if not item.get('time'):
            raise ValueError('YouTube viewing row %s has no timestamp' % number)
        try:
            occurred = _iso(item['time'])
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError('YouTube viewing row %s has an invalid timestamp' % number) from exc
        subtitles = item.get('subtitles')
        channel = next((str(part.get('name') or '') for part in subtitles if isinstance(part, dict)), '') if isinstance(subtitles, list) else ''
        title = re.sub(r'^(?:Watched|Tittade på)\s+', '', title).strip() or 'Video unavailable'
        source = {'duration_known': False, 'media_kind': 'video', 'video_id': video_id}
        if video_id:
            source.update(url='https://www.youtube.com/watch?v=' + video_id,
                          artwork_url='https://i.ytimg.com/vi/' + video_id + '/hqdefault.jpg')
        rows.append(_row('youtube', occurred, title, channel, 0, source))
    return rows


def parse_media(provider: str, filename: str, content: bytes) -> List[Dict[str, Any]]:
    provider = provider.lower().strip()
    if provider == 'youtube':
        return _youtube(content, filename)
    if provider == "spotify":
        try:
            data = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Spotify export must be valid JSON") from exc
        return _spotify(data)
    if provider == "netflix":
        try:
            return _netflix(content.decode("utf-8-sig"), filename)
        except UnicodeDecodeError as exc:
            raise ValueError("Netflix export must be UTF-8 CSV") from exc
    raise ValueError("unsupported media provider %r" % provider)


def parse_steam_file(content: bytes) -> Dict[str, Any]:
    """Steam Web API exports are library snapshots, never dated play sessions."""
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Steam export must be valid JSON") from exc
    body = data.get("response", data) if isinstance(data, dict) else None
    games = body.get("games") if isinstance(body, dict) else None
    if not isinstance(games, list) or not games:
        raise ValueError("Steam JSON needs a non-empty games array from GetOwnedGames or GetRecentlyPlayedGames")
    normalized = {}
    for item in games:
        try:
            appid = int(item["appid"])
            if isinstance(item["appid"], bool) or appid <= 0 or str(appid) != str(item["appid"]):
                raise ValueError()
            minutes = float(item.get("playtime_forever", 0))
            recent = float(item.get("playtime_2weeks", 0))
            last = int(item.get("rtime_last_played") or 0)
            if not all(math.isfinite(value) and value >= 0 for value in (minutes, recent, last)):
                raise ValueError()
            last_played = datetime.fromtimestamp(last, timezone.utc).isoformat(timespec="seconds") if last else None
        except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
            raise ValueError("Steam games need a positive appid and valid, non-negative playtime values") from exc
        normalized[appid] = {"appid": appid, "name": str(item.get("name") or "Game %s" % appid),
                             "minutes": round(minutes, 2), "recent_minutes": round(recent, 2), "last_played": last_played,
                             "artwork_url": "https://cdn.akamai.steamstatic.com/steam/apps/%s/header.jpg" % appid}
    return {"kind": "steam_library", "games": sorted(normalized.values(), key=lambda game: game["minutes"], reverse=True),
            "snapshot_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


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
