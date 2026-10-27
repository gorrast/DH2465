"""Import-time catalogue artwork. A missing/ambiguous match never changes history."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import httpx

TMDB_SEARCH = "https://api.themoviedb.org/3/search/multi"
BATCH_SIZE = 4


class ArtworkError(Exception):
    pass


def netflix_query(title: str) -> str | None:
    title = title.strip()
    if not title or title == "Title unavailable":
        return None
    marker = re.search(r":\s*(?:season|säsong|saison|temporada|series|volume|part|del|avsnitt|episode|miniserie|limited series)\b", title, re.I)
    if marker:
        queries, kind = [title[:marker.start()].strip()], "tv"
    else:
        queries, kind = [title], None
        if ": " in title:
            queries.extend([title.rsplit(": ", 1)[0], title.split(": ", 1)[0]])
    queries = list(dict.fromkeys(query for query in queries if query and len(query) <= 200))
    return json.dumps([kind, *queries[:3]], ensure_ascii=False) if queries else None


def artwork_status() -> dict[str, Any]:
    configured = bool(os.environ.get("TMDB_READ_ACCESS_TOKEN", "").strip())
    return {"configured": configured, "message": "Posters are fetched automatically after Netflix imports." if configured else
            "Add TMDB_READ_ACCESS_TOKEN to .env.local and restart the backend to fetch Netflix posters automatically."}


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", "".join(char for char in unicodedata.normalize("NFKD", value).casefold()
                                                   if not unicodedata.combining(char))))


@lru_cache(maxsize=2048)
def _poster(token: str, query_key: str, language: str, day: int) -> dict[str, Any]:
    try:
        kind, *queries = json.loads(query_key)
        if kind not in (None, "tv") or not 1 <= len(queries) <= 3 or not all(isinstance(q, str) and 0 < len(q) <= 200 for q in queries):
            raise ValueError()
    except (ValueError, TypeError):
        return {"artwork_status": "unmatched"}
    with httpx.Client(timeout=4.0, follow_redirects=False) as client:
        for query in queries:
            try:
                response = client.get(TMDB_SEARCH, headers={"Authorization": "Bearer " + token},
                                      params={"query": query, "language": language, "include_adult": "false"})
            except httpx.HTTPError:
                raise ArtworkError("TMDB could not be reached. Your history is saved; try fetching posters again.") from None
            if response.status_code in (401, 403):
                raise ArtworkError("TMDB rejected the read access token. Check TMDB_READ_ACCESS_TOKEN and restart the backend.")
            if response.status_code == 429:
                raise ArtworkError("TMDB is limiting requests. Your history is saved; wait before retrying posters.")
            if response.status_code != 200:
                raise ArtworkError("TMDB could not provide posters. Your history is saved; try again later.")
            try:
                results = response.json()["results"]
                if not isinstance(results, list):
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise ArtworkError("TMDB returned unreadable metadata. Your history is saved; try again later.") from None
            matches = {}
            for result in results:
                if not isinstance(result, dict) or result.get("media_type") not in ("movie", "tv") or result.get("adult"):
                    continue
                if kind and result["media_type"] != kind:
                    continue
                titles = [result.get(field) for field in ("title", "name", "original_title", "original_name")]
                if any(isinstance(name, str) and _normalized(name) == _normalized(query) for name in titles):
                    matches[(result["media_type"], str(result.get("id")))] = result
            # Multiple exact names can be remakes or different shows. Do not silently pick one.
            if len(matches) > 1:
                return {"artwork_status": "unmatched"}
            if len(matches) == 1:
                result = next(iter(matches.values()))
                path, tmdb_id = result.get("poster_path"), result.get("id")
                if not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9_.-]+\.(?:jpg|png|webp)", path) or type(tmdb_id) is not int or tmdb_id <= 0:
                    return {"artwork_status": "unmatched"}
                return {"artwork_status": "matched", "artwork_source": "tmdb", "artwork_url": "https://image.tmdb.org/t/p/w342" + path,
                        "tmdb_id": tmdb_id, "tmdb_media_type": result["media_type"],
                        "artwork_page": "https://www.themoviedb.org/%s/%s" % (result["media_type"], tmdb_id)}
    return {"artwork_status": "unmatched"}


def netflix_artwork_batch(rows: list[dict]) -> tuple[list[dict], str | None]:
    token = os.environ.get("TMDB_READ_ACCESS_TOKEN", "").strip()
    if not token:
        return [], artwork_status()["message"]
    keys = list(dict.fromkeys(row.get("source", {}).get("artwork_query") for row in rows))
    keys = [key for key in keys if isinstance(key, str)][:BATCH_SIZE]
    language = os.environ.get("TMDB_LANGUAGE", "sv-SE").strip() or "sv-SE"
    day = int(datetime.now(timezone.utc).timestamp()) // 86400
    updates, error = [], None
    def lookup(key):
        try:
            return {"query": key, "source": _poster(token, key, language, day)}, None
        except ArtworkError as exc:
            return None, str(exc)
    with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
        for update, failure in executor.map(lookup, keys):
            if update:
                updates.append(update)
            error = error or failure
    return updates, error
