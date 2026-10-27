"""Bounded, resumable reads of Last.fm scrobbles. No playback duration is inferred."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

API_URL = "https://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = 200


class LastfmError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def lastfm_status(user_id: str) -> dict[str, Any]:
    key = os.environ.get("LASTFM_API_KEY", "").strip()
    username = os.environ.get("LASTFM_USERNAME", "").strip()
    owner = os.environ.get("LASTFM_SYNC_USER_ID", "").strip()
    configured = bool(key and username and owner and owner == user_id)
    message = "Ready to sync your Last.fm listening history." if configured else (
        "Last.fm sync is not enabled for this signed-in account." if owner and owner != user_id else
        "Set LASTFM_API_KEY, LASTFM_USERNAME and LASTFM_SYNC_USER_ID in .env.local, then restart the backend.")
    return {"configured": configured, "message": message, "user_id": user_id,
            "username": username if configured else None,
            "profile_url": "https://www.last.fm/user/" + quote(username, safe="") if configured else None}


def _artwork(images: Any) -> str | None:
    sizes = {"small": 1, "medium": 2, "large": 3, "extralarge": 4, "mega": 5}
    candidates = []
    for image in images if isinstance(images, list) else []:
        if not isinstance(image, dict):
            continue
        url = str(image.get("#text") or "").strip()
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        if (parts.scheme == "https" and parts.hostname in {"lastfm.freetls.fastly.net", "lastfm-img.freetls.fastly.net", "lastfm-img2.akamaized.net", "userserve-ak.last.fm"}
                and not parts.username and not parts.password and not parts.query
                and "2a96cbd8b46e442fc41c2b86b821562f" not in parts.path):
            candidates.append((sizes.get(image.get("size"), 0), url))
    return max(candidates, default=(0, None), key=lambda candidate: candidate[0])[1]


def _text(value: Any) -> str:
    return str(value.get("#text") or "").strip() if isinstance(value, dict) else str(value or "").strip()


@lru_cache(maxsize=512)
def _album_artwork(api_key: str, artist: str, album: str, day: int) -> str | None:
    """Metadata-only lookup. Cache missing covers too; retry on a later day."""
    try:
        with httpx.Client(timeout=6.0, follow_redirects=False) as client:
            response = client.get(API_URL, params={"method": "album.getInfo", "api_key": api_key,
                                                  "artist": artist, "album": album, "format": "json", "autocorrect": 1})
        if response.status_code != 200:
            return None
        return _artwork(response.json().get("album", {}).get("image"))
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None


def lastfm_artwork(user_id: str, artist: str, album: str) -> str | None:
    status = lastfm_status(user_id)
    if not status["configured"]:
        owner = os.environ.get("LASTFM_SYNC_USER_ID", "").strip()
        raise LastfmError(status["message"], 403 if owner and owner != user_id else 503)
    if not artist.strip() or not album.strip() or len(artist) > 300 or len(album) > 300:
        raise LastfmError("Artwork lookup needs an artist and album of at most 300 characters each.", 400)
    return _album_artwork(os.environ["LASTFM_API_KEY"].strip(), artist.strip(), album.strip(),
                          int(datetime.now(timezone.utc).timestamp()) // 86400)


def fetch_lastfm(user_id: str, previous: dict[str, Any] | None = None, *, older: bool = False) -> tuple[list[dict], dict]:
    status = lastfm_status(user_id)
    if not status["configured"]:
        owner = os.environ.get("LASTFM_SYNC_USER_ID", "").strip()
        raise LastfmError(status["message"], 403 if owner and owner != user_id else 503)
    username = status["username"]
    previous = previous or {}
    if previous and str(previous.get("username", "")).casefold() != username.casefold():
        raise LastfmError("The configured Last.fm username differs from your saved history. Restore the previous username before syncing.", 409)
    now = int(datetime.now(timezone.utc).timestamp())
    initial = not previous
    if older:
        if not previous.get("history_has_more"):
            raise LastfmError("There is no older Last.fm history waiting to load.", 400)
        lower, upper, page = None, int(previous["history_to"]), int(previous["history_next_page"])
    elif previous.get("pending"):
        pending = previous["pending"]
        lower, upper, page = int(pending["from"]), int(pending["to"]), int(pending["page"])
    else:
        lower = None if initial else max(0, int(previous.get("latest_uts") or previous.get("checked_at") or now) - 1)
        upper, page = now, 1
    params = {"method": "user.getRecentTracks", "api_key": os.environ["LASTFM_API_KEY"].strip(),
              "user": username, "format": "json", "limit": PAGE_SIZE, "page": page, "to": upper}
    if lower is not None:
        params["from"] = lower
    # The documented API takes its key as a parameter. Do not log request URLs or raw exceptions.
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            response = client.get(API_URL, params=params)
    except httpx.TimeoutException:
        raise LastfmError("Last.fm took too long to respond. Your saved history is unchanged; try again.", 504) from None
    except httpx.HTTPError:
        raise LastfmError("Could not reach Last.fm. Your saved history is unchanged; try again.") from None
    if response.status_code == 429:
        raise LastfmError("Last.fm is limiting requests. Wait a little before syncing again.", 503)
    if response.status_code != 200:
        raise LastfmError("Last.fm could not provide your history. Check your account settings or try again later.")
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            code = int(data["error"])
            messages = {10: "Last.fm rejected the API key. Check LASTFM_API_KEY and restart the backend.",
                        26: "Last.fm has suspended this API key.", 6: "Last.fm could not find the user. Check LASTFM_USERNAME and your history privacy settings.",
                        17: "Last.fm history is private. Make your recent listening history visible.",
                        29: "Last.fm is limiting requests. Wait a little before syncing again."}
            raise LastfmError(messages.get(code, "Last.fm could not provide your history. Check your account settings or try again later."), 503 if code in (11, 16, 29) else 502)
        recent = data["recenttracks"]
        attrs = recent["@attr"]
        total_pages = int(attrs["totalPages"])
        if total_pages < 0 or int(attrs.get("page", page)) != page:
            raise ValueError()
        tracks = recent.get("track", [])
        tracks = [tracks] if isinstance(tracks, dict) else tracks
        if not isinstance(tracks, list):
            raise ValueError()
        rows = {}
        for track in tracks:
            if not isinstance(track, dict):
                raise ValueError()
            if str((track.get("@attr") or {}).get("nowplaying", "")).lower() == "true":
                continue
            timestamp = int(track["date"]["uts"])
            title, artist, album = _text(track.get("name")), _text(track.get("artist")), _text(track.get("album"))
            if not title or timestamp <= 0:
                raise ValueError()
            occurred = datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")
            identity = json.dumps([username.casefold(), timestamp, title, artist], ensure_ascii=False)
            event_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
            # Build the catalogue link from metadata rather than trusting an arbitrary upstream URL.
            track_url = "https://www.last.fm/music/" + quote(artist, safe="") + "/_/" + quote(title, safe="")
            rows[event_id] = {"id": event_id, "provider": "lastfm", "occurred_at": occurred, "title": title,
                              "creator": artist or None, "minutes": 0,
                              "source": {"media_kind": "music", "duration_known": False, "username": username,
                                         "album": album, "artwork_url": _artwork(track.get("image")), "url": track_url}}
        state = {**previous, "username": username, "profile_url": status["profile_url"],
                 "last_synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "latest_uts": max([int(previous.get("latest_uts") or 0)] + [int(datetime.fromisoformat(row["occurred_at"]).timestamp()) for row in rows.values()])}
        has_more = page < total_pages
        if initial or older:
            state.update(history_to=upper, history_next_page=page + 1, history_has_more=has_more)
        if not older:
            # Freeze the range while paging through a backlog, so new scrobbles cannot shift pages.
            state["pending"] = {"from": lower, "to": upper, "page": page + 1} if not initial and has_more else None
            if not state["pending"]:
                state["checked_at"] = upper
        return list(rows.values()), state
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError):
        raise LastfmError("Last.fm returned unreadable history. Your saved history is unchanged; try again.") from None
