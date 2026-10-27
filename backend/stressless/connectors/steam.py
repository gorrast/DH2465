"""Read a personally configured Steam library; never expose the API key to clients."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .media import parse_steam_file

LIBRARY_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"


class SteamSyncError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def steam_sync_status(user_id: str) -> dict[str, Any]:
    key = os.environ.get("STEAM_WEB_API_KEY", "").strip()
    steam_id = os.environ.get("STEAM_ID", "").strip()
    owner = os.environ.get("STEAM_SYNC_USER_ID", "").strip()
    configured = False
    if not key or not steam_id or not owner:
        message = "Set STEAM_WEB_API_KEY, STEAM_ID and STEAM_SYNC_USER_ID in .env.local, then restart the backend."
    elif owner != user_id:
        message = "Steam sync is not enabled for this signed-in account."
    elif not re.fullmatch(r"[0-9]{17}", steam_id):
        message = "STEAM_ID must be your 17-digit SteamID64, not your profile name."
    else:
        configured = True
        message = "Ready to refresh your Steam library."
    return {"configured": configured, "message": message, "user_id": user_id,
            "steam_id": steam_id if configured else None}


def fetch_steam_library(user_id: str) -> dict[str, Any]:
    status = steam_sync_status(user_id)
    if not status["configured"]:
        owner = os.environ.get("STEAM_SYNC_USER_ID", "").strip()
        raise SteamSyncError(status["message"], 403 if owner and owner != user_id else 503)
    try:
        response = httpx.get(
            LIBRARY_URL,
            # Steam supports this header: keep credentials out of URLs and URL logs.
            headers={"x-webapi-key": os.environ["STEAM_WEB_API_KEY"].strip()},
            params={"input_json": json.dumps({"steamid": status["steam_id"], "include_appinfo": True,
                                               "include_played_free_games": True})},
            timeout=15.0, follow_redirects=False,
        )
    except httpx.TimeoutException:
        raise SteamSyncError("Steam took too long to respond. Your saved library is unchanged; try again.", 504) from None
    except httpx.HTTPError:
        raise SteamSyncError("Could not reach Steam. Your saved library is unchanged; try again.") from None
    if response.status_code in (401, 403):
        raise SteamSyncError("Steam rejected the API key. Check STEAM_WEB_API_KEY and restart the backend.")
    if response.status_code == 429:
        raise SteamSyncError("Steam is limiting requests. Wait a little before syncing again.", 503)
    if response.status_code != 200:
        raise SteamSyncError("Steam could not provide your library. Try again later.")
    try:
        data = response.json()
        body = data.get("response") if isinstance(data, dict) else None
        if not isinstance(body, dict) or not (isinstance(body.get("games"), list) or body.get("game_count") == 0):
            raise SteamSyncError("Steam did not return a visible library. Check your SteamID64 and set Steam Profile and Game details to Public.")
        if body.get("game_count") == 0 and not body.get("games"):
            document = {"kind": "steam_library", "games": [],
                        "snapshot_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        else:
            document = parse_steam_file(json.dumps(data).encode("utf-8"))
    except (ValueError, TypeError, KeyError):
        raise SteamSyncError("Steam returned an unreadable library. Your saved library is unchanged; try again.") from None
    return {**document, "steam_id": status["steam_id"], "origin": "steam_api"}
