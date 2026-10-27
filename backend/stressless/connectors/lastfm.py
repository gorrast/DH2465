"""Bounded, resumable reads of Last.fm scrobbles. No playback duration is inferred.

One app-wide API key (LASTFM_API_KEY, from https://www.last.fm/api/account/create) reads public listening history.
Each StressLess user connects their own Last.fm username on the Media page; it is kept in that user's
``lastfm_sync`` media document together with the sync progress, so no per-user server setup is needed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

API_URL = "https://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = 200
# Last.fm usernames: 2-15 characters, a letter first, then letters, digits, "-" or "_".
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,14}$")


class LastfmError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _api_key() -> str:
    return os.environ.get("LASTFM_API_KEY", "").strip()


def profile_url(username: str) -> str:
    return "https://www.last.fm/user/" + quote(username, safe="")


def lastfm_status(saved: dict[str, Any] | None) -> dict[str, Any]:
    """``saved`` is the user's lastfm_sync payload (None when they never connected)."""
    available = bool(_api_key())
    username = str((saved or {}).get("username") or "").strip() or None
    connected = available and username is not None
    message = ("Connected as %s. Sync whenever you like." % username if connected else
               "Enter your Last.fm username to connect." if available else
               "Last.fm sync isn't available right now.")
    return {"available": available, "connected": connected, "configured": connected, "message": message,
            "username": username, "profile_url": profile_url(username) if username else None}


def _require(saved: dict[str, Any] | None) -> str:
    status = lastfm_status(saved)
    if not status["available"]:
        raise LastfmError(status["message"], 503)
    if not status["connected"]:
        raise LastfmError("Connect your Last.fm username first.", 409)
    return status["username"]


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


def lastfm_artwork(saved: dict[str, Any] | None, artist: str, album: str) -> str | None:
    _require(saved)
    if not artist.strip() or not album.strip() or len(artist) > 300 or len(album) > 300:
        raise LastfmError("Artwork lookup needs an artist and album of at most 300 characters each.", 400)
    return _album_artwork(_api_key(), artist.strip(), album.strip(),
                          int(datetime.now(timezone.utc).timestamp()) // 86400)


def _recent_tracks(params: dict[str, Any]) -> Any:
    """One user.getRecentTracks call, with Last.fm's errors turned into messages a person can act on."""
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
        code = int(data["error"]) if isinstance(data, dict) and data.get("error") else None
    except (ValueError, TypeError):
        raise LastfmError("Last.fm returned unreadable history. Your saved history is unchanged; try again.") from None
    if code is not None:
        unavailable = "Last.fm sync isn't available right now. Your saved listening is unchanged; try again later."
        messages = {10: unavailable, 26: unavailable,
                    6: "Last.fm has no user called %s. Check the spelling of your username." % params.get("user"),
                    17: "Your Last.fm listening history is private. Turn off \"Hide recent listening information\" "
                        "in your Last.fm privacy settings, then try again.",
                    29: "Last.fm is limiting requests. Wait a little before syncing again."}
        status = 404 if code == 6 else 403 if code == 17 else 503 if code in (11, 16, 29) else 502
        raise LastfmError(messages.get(code, "Last.fm could not provide your history. Check your account settings or try again later."), status)
    return data


def verify_username(username: str) -> str:
    """Check that a Last.fm user exists and shares their listening; returns the name as Last.fm spells it."""
    username = (username or "").strip()
    if not _api_key():
        raise LastfmError(lastfm_status(None)["message"], 503)
    if not USERNAME_RE.match(username):
        raise LastfmError("That doesn't look like a Last.fm username (2-15 letters, digits, - or _, starting with a letter).", 400)
    data = _recent_tracks({"method": "user.getRecentTracks", "api_key": _api_key(), "user": username,
                           "format": "json", "limit": 1})
    try:
        name = str(data["recenttracks"]["@attr"].get("user") or username)
    except (KeyError, TypeError, AttributeError):
        raise LastfmError("Last.fm returned an unexpected answer. Try again in a moment.") from None
    return name if USERNAME_RE.match(name) else username


def fetch_lastfm(previous: dict[str, Any] | None, *, older: bool = False) -> tuple[list[dict], dict]:
    """The next batch of the connected user's scrobbles and the updated sync state."""
    username = _require(previous)
    previous = previous or {}
    now = int(datetime.now(timezone.utc).timestamp())
    # Until a scrobble has been saved, every sync starts over from the newest page: an empty first answer (a
    # profile that was still hidden, or no listens yet) must not move the window past the existing history.
    initial = not previous.get("latest_uts")
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
    params = {"method": "user.getRecentTracks", "api_key": _api_key(),
              "user": username, "format": "json", "limit": PAGE_SIZE, "page": page, "to": upper}
    if lower is not None:
        params["from"] = lower
    data = _recent_tracks(params)
    try:
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
        state = {**previous, "username": username, "profile_url": profile_url(username),
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
