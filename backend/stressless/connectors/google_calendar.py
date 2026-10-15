"""Google Calendar over OAuth: the consent URL, token exchange and the event listing that feeds ``calendar_events``.

Read-only. What is kept per event is what the engine uses — title, times, location and how many guests — not the
description and not who the guests are. Like the .ics importer, all-day and cancelled events are skipped.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import quote, urlencode

import httpx

from ..engine.pipeline import EngineError
from .base import classify_event, parse_ts

log = logging.getLogger("stressless.connectors.google")

PROVIDER = "google_calendar"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
WINDOW_PAST_DAYS = 70
WINDOW_FUTURE_DAYS = 90
# Google's own generated calendars (holidays, birthdays, week numbers) all live under this domain.
GENERATED_CALENDARS = "@group.v.calendar.google.com"
SKIPPED_EVENT_TYPES = ("workingLocation", "outOfOffice", "birthday")


class GoogleError(EngineError):
    status = 502


class ReconnectNeeded(EngineError):
    """Google no longer accepts the stored authorization; the user has to connect again."""
    status = 409


def authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "access_type": "offline",
        "prompt": "consent", "scope": SCOPE, "state": state,
    })


def _token(http: httpx.Client, form: Dict[str, str]) -> httpx.Response:
    try:
        return http.post(TOKEN_URL, data=form)
    except httpx.HTTPError as exc:
        raise GoogleError("Google unreachable: %s" % exc) from exc


def exchange_code(http: httpx.Client, client_id: str, client_secret: str, redirect_uri: str, code: str) -> Dict[str, Any]:
    """Trade the one-time code from the consent screen for tokens; the refresh token is the one worth keeping."""
    r = _token(http, {"code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri,
                      "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise GoogleError("Google could not complete the authorization")
    tokens = r.json()
    if not tokens.get("refresh_token") or not tokens.get("access_token"):
        raise GoogleError("Google did not return a refresh token")
    return tokens


def refresh_access_token(http: httpx.Client, client_id: str, client_secret: str, refresh_token: str) -> str:
    r = _token(http, {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token,
                      "grant_type": "refresh_token"})
    if r.status_code in (400, 401):
        raise ReconnectNeeded("Google Calendar authorization expired; reconnect your calendar")
    if r.status_code != 200 or not isinstance(r.json().get("access_token"), str):
        raise GoogleError("Google could not refresh the calendar authorization")
    return r.json()["access_token"]


def revoke(http: httpx.Client, refresh_token: str) -> None:
    """Best effort: the connection is forgotten on our side whether or not Google answers."""
    try:
        http.post(REVOKE_URL, data={"token": refresh_token})
    except httpx.HTTPError as exc:
        log.warning("could not revoke Google token: %s", exc)


def _pages(http: httpx.Client, access_token: str, url: str, params: Dict[str, str], what: str) -> Iterator[Dict[str, Any]]:
    page: Optional[str] = None
    while True:
        try:
            r = http.get(url, params=dict(params, pageToken=page) if page else params, headers={"Authorization": "Bearer " + access_token})
        except httpx.HTTPError as exc:
            raise GoogleError("Google unreachable: %s" % exc) from exc
        if r.status_code in (401, 403):
            raise ReconnectNeeded("Google Calendar access is missing for your account; reconnect your calendar")
        if r.status_code != 200:
            raise GoogleError("Google could not read %s" % what)
        body = r.json()
        yield from body.get("items") or []
        page = body.get("nextPageToken")
        if not page:
            return


def account_email(http: httpx.Client, access_token: str) -> Optional[str]:
    """The connected account, read off its primary calendar (whose id is the account's address)."""
    try:
        r = http.get(API + "/calendars/primary", headers={"Authorization": "Bearer " + access_token})
        return r.json().get("id") if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


def calendar_ids(http: httpx.Client, access_token: str) -> List[str]:
    """The calendars the user has ticked in Google Calendar, minus Google's generated ones."""
    params = {"showHidden": "false", "minAccessRole": "reader", "maxResults": "250"}
    return [c["id"] for c in _pages(http, access_token, API + "/users/me/calendarList", params, "your calendars")
            if c.get("id") and c.get("selected") and not c["id"].endswith(GENERATED_CALENDARS)]


def sync_window(now: Optional[datetime] = None) -> tuple:
    now = now or datetime.now(timezone.utc)
    return now - timedelta(days=WINDOW_PAST_DAYS), now + timedelta(days=WINDOW_FUTURE_DAYS)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_row(user_id: str, calendar_id: str, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One Google event as a ``calendar_events`` row, or None for events that say nothing about the user's day."""
    start, end = (event.get("start") or {}).get("dateTime"), (event.get("end") or {}).get("dateTime")
    if not event.get("id") or event.get("status") == "cancelled" or not start or not end:
        return None  # all-day events carry a date, not a dateTime
    if event.get("eventType") in SKIPPED_EVENT_TYPES:
        return None
    attendees = event.get("attendees") or []
    if any(a.get("self") and a.get("responseStatus") == "declined" for a in attendees):
        return None
    try:
        starts_at, ends_at = parse_ts(start, "UTC"), parse_ts(end, "UTC")
    except ValueError:
        return None
    if ends_at <= starts_at:
        return None
    title, location = event.get("summary") or "Untitled event", event.get("location") or None
    return {
        "user_id": user_id, "provider": PROVIDER, "provider_event_id": "%s:%s" % (calendar_id, event["id"]),
        "title": title, "category": "focus" if event.get("eventType") == "focusTime" else classify_event(title, location),
        "starts_at": iso(starts_at), "ends_at": iso(ends_at), "location": location, "description": None,
        "guests": [{"response_status": a.get("responseStatus")} for a in attendees if not a.get("self") and not a.get("resource")],
    }


def event_rows(http: httpx.Client, access_token: str, user_id: str, time_min: datetime, time_max: datetime) -> List[Dict[str, Any]]:
    params = {"timeMin": iso(time_min), "timeMax": iso(time_max), "singleEvents": "true", "orderBy": "startTime", "maxResults": "2500"}
    rows: Dict[str, Dict[str, Any]] = {}
    for cal in calendar_ids(http, access_token):
        for event in _pages(http, access_token, "%s/calendars/%s/events" % (API, quote(cal, safe="")), params, "calendar events"):
            row = event_row(user_id, cal, event)
            if row:
                rows[row["provider_event_id"]] = row
    return list(rows.values())
