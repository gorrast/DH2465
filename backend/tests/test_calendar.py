"""Google Calendar connection tests: the OAuth round trip, sync and disconnect against a fake Google and a fake PostgREST."""
import base64
import json
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from stressless.connectors import google_calendar as google
from stressless.server import calendar
from stressless.server.app import app
from stressless.server.auth import Principal, current_principal
from stressless.store import MemoryStore

ENV = {
    "NEXT_PUBLIC_SUPABASE_URL": "https://db.test", "SUPABASE_SERVICE_ROLE_KEY": "service-key", "APP_URL": "http://localhost:3000",
    "GOOGLE_CLIENT_ID": "client-id", "GOOGLE_CLIENT_SECRET": "client-secret",
    "GOOGLE_TOKEN_ENCRYPTION_KEY": base64.b64encode(bytes([7]) * 32).decode(),
}
# Produced by the Edge Function's own WebCrypto code with the key above.
EDGE_CIPHERTEXT = "v3E4Yp_x5_3xlnSvgzp-JLRK1RpbJjGBzgpl4-D8ZwrKlBH_x1X7Jg2px5aNNrMSngQcqqtxF1jh"
EDGE_STATE_HASH = "1DFxCPoklrWabhfPO9ZDmkOC490wGvIj0yt-58TekdY"
HOLIDAYS = "en.swedish#holiday@group.v.calendar.google.com"


def at(days: int, hour: int = 9) -> str:
    d = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days)
    return d.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def meeting(event_id: str, days: int = 1, **extra):
    return dict({"id": event_id, "summary": "Sync " + event_id, "start": {"dateTime": at(days, 9)}, "end": {"dateTime": at(days, 10)}}, **extra)


class Fake:
    """Just enough PostgREST and Google to drive the routes; fails loudly on anything it does not know."""

    def __init__(self):
        self.tables = {"provider_connections": [], "provider_connection_credentials": [], "calendar_events": []}
        self.events = {"me@example.com": [], HOLIDAYS: [meeting("holiday")], "unticked@example.com": [meeting("hidden")]}
        self.revoked = []
        self.fail_upsert = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.netloc == "db.test":
            assert request.headers["apikey"] == "service-key"
            return self.rest(request, url.path.rsplit("/", 1)[1], params)
        return self.google(request, url.netloc + url.path, params)

    # -- PostgREST --
    @staticmethod
    def _match(row, column, cond):
        op, _, value = cond.partition(".")
        cell = row.get(column)
        return {"eq": cell == value, "neq": cell != value, "in": cell in value.strip("()").split(","),
                "gte": str(cell) >= value, "lt": str(cell) < value}[op]

    def _rows(self, table, params):
        rows = self.tables[table]
        for column, cond in params.items():
            if column == "and":
                for part in cond.strip("()").split(","):
                    col, _, rest = part.partition(".")
                    rows = [r for r in rows if self._match(r, col, rest)]
            elif column not in ("select", "order", "limit", "offset", "on_conflict"):
                rows = [r for r in rows if self._match(r, column, cond)]
        return rows

    def rest(self, request, table, params):
        body = json.loads(request.content) if request.content else None
        hit = self._rows(table, params)
        if request.method == "GET":
            start = int(params.get("offset", 0))
            return httpx.Response(200, json=sorted(hit, key=lambda r: str(r.get("id")))[start:start + int(params.get("limit", 10 ** 6))])
        if request.method == "POST":
            if table == "calendar_events" and self.fail_upsert:
                return httpx.Response(500, json={"message": "boom"})
            keys, out = (params.get("on_conflict") or "").split(","), []
            for new in body if isinstance(body, list) else [body]:
                old = next((r for r in self.tables[table] if keys != [""] and all(r[k] == new[k] for k in keys)), None)
                if old:
                    old.update(new)
                else:
                    old = dict({"id": str(uuid.uuid4())} if table != "provider_connection_credentials" else {}, **new)
                    if table == "provider_connections":
                        old = dict({"connected_at": None, "last_synced_at": None, "provider_account_id": None}, **old)
                    self.tables[table].append(old)
                out.append(old)
            return httpx.Response(201, json=out if "representation" in request.headers.get("prefer", "") else None)
        if request.method == "PATCH":
            for r in hit:
                r.update(body)
            return httpx.Response(204)
        if request.method == "DELETE":
            gone = {id(r) for r in hit}
            self.tables[table] = [r for r in self.tables[table] if id(r) not in gone]
            if table == "provider_connections":  # on delete cascade
                ids = {r["id"] for r in self.tables[table]}
                creds = self.tables["provider_connection_credentials"]
                self.tables["provider_connection_credentials"] = [c for c in creds if c["provider_connection_id"] in ids]
            return httpx.Response(204)
        raise AssertionError("unexpected %s %s" % (request.method, table))

    # -- Google --
    def google(self, request, where, params):
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if where == "oauth2.googleapis.com/token":
            assert form["client_secret"] == "client-secret"
            if form["grant_type"] == "authorization_code":
                assert form["redirect_uri"] == "http://localhost:3000/api/calendar/google/callback"
                ok = form["code"] == "good-code"
                return httpx.Response(200 if ok else 400, json={"access_token": "at-1", "refresh_token": "rt-1"} if ok else {"error": "invalid_grant"})
            ok = form["refresh_token"] == "rt-1" and "rt-1" not in self.revoked
            return httpx.Response(200 if ok else 400, json={"access_token": "at-1"} if ok else {"error": "invalid_grant"})
        if where == "oauth2.googleapis.com/revoke":
            self.revoked.append(form["token"])
            return httpx.Response(200, json={})
        assert request.headers["authorization"] == "Bearer at-1"
        if where.endswith("/calendars/primary"):
            return httpx.Response(200, json={"id": "me@example.com"})
        if where.endswith("/users/me/calendarList"):
            return httpx.Response(200, json={"items": [{"id": "me@example.com", "selected": True}, {"id": HOLIDAYS, "selected": True},
                                                       {"id": "unticked@example.com"}]})
        cal = httpx.URL(str(request.url)).path.split("/calendars/")[1].rsplit("/events", 1)[0]
        assert params["singleEvents"] == "true"
        return httpx.Response(200, json={"items": self.events[cal]})


class CalendarTests(unittest.TestCase):
    user = "user-a"

    def setUp(self):
        self._old = {k: os.environ.get(k) for k in ENV}
        os.environ.update(ENV)
        self.fake = Fake()
        calendar._client = httpx.Client(transport=httpx.MockTransport(self.fake))
        type(self).user = "user-a"
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=type(self).user, store=MemoryStore())
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        calendar._client = None
        for k, v in self._old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def authorize(self) -> str:
        r = self.client.post("/api/calendar/google/authorize")
        self.assertEqual(r.status_code, 200, r.text)
        q = parse_qs(urlparse(r.json()["authorizationUrl"]).query)
        self.assertEqual(q["redirect_uri"], ["http://localhost:3000/api/calendar/google/callback"])
        self.assertEqual((q["access_type"], q["scope"]), (["offline"], [google.SCOPE]))
        return q["state"][0]

    def connect(self):
        r = self.client.get("/api/calendar/google/callback", params={"state": self.authorize(), "code": "good-code"})
        self.assertEqual(r.headers["location"], "http://localhost:3000/calendar?sync=google")

    def connections(self):
        return self.fake.tables["provider_connections"]

    # ------------------------------------------------------------- crypto --
    def test_reads_what_the_edge_function_wrote(self):
        self.assertEqual(calendar.decrypt(EDGE_CIPHERTEXT), "1//refresh-token-from-edge-fn")
        self.assertEqual(calendar.state_hash("some-state"), EDGE_STATE_HASH)
        self.assertEqual(calendar.decrypt(calendar.encrypt("rt")), "rt")
        self.assertNotEqual(calendar.encrypt("rt"), calendar.encrypt("rt"))

    def test_not_configured(self):
        del os.environ["GOOGLE_CLIENT_ID"]
        r = self.client.post("/api/calendar/google/authorize")
        self.assertEqual(r.status_code, 503)
        self.assertIn("GOOGLE_CLIENT_ID", r.json()["error"])
        self.assertEqual(self.connections(), [])

    # -------------------------------------------------------------- oauth --
    def test_connect(self):
        self.assertEqual(self.client.get("/api/calendar/google").json(), {"connections": []})
        self.connect()
        (c,) = self.connections()
        self.assertEqual((c["status"], c["user_id"], c["provider_account_id"]), ("connected", "user-a", "me@example.com"))
        (cred,) = self.fake.tables["provider_connection_credentials"]
        self.assertIsNone(cred["oauth_state_hash"])
        self.assertNotIn("rt-1", json.dumps(self.fake.tables))  # the refresh token is only ever stored encrypted
        self.assertEqual(calendar.decrypt(cred["refresh_token_ciphertext"]), "rt-1")
        self.assertEqual(self.client.get("/api/calendar/google").json()["connections"][0]["email"], "me@example.com")

    def test_state_is_single_use_and_bound_to_the_browser(self):
        state = self.authorize()
        other = TestClient(app, follow_redirects=False)  # same link opened in a browser that never asked for it
        r = other.get("/api/calendar/google/callback", params={"state": state, "code": "good-code"})
        self.assertEqual(r.headers["location"], "http://localhost:3000/calendar?error=google")
        self.assertEqual(self.connections()[0]["status"], "pending")
        self.connect_with(state)
        r = self.client.get("/api/calendar/google/callback", params={"state": state, "code": "good-code"})
        self.assertEqual(r.headers["location"], "http://localhost:3000/calendar?error=google")
        self.assertEqual([c["status"] for c in self.connections()], ["connected"])

    def connect_with(self, state):
        self.client.cookies.set(calendar.STATE_COOKIE, state, path=calendar.CALLBACK_PATH)
        r = self.client.get("/api/calendar/google/callback", params={"state": state, "code": "good-code"})
        self.assertEqual(r.headers["location"], "http://localhost:3000/calendar?sync=google")

    def test_failed_consent_leaves_nothing_behind(self):
        for params in ({"error": "access_denied"}, {"code": "bad-code"}):
            r = self.client.get("/api/calendar/google/callback", params=dict(params, state=self.authorize()))
            self.assertEqual(r.headers["location"], "http://localhost:3000/calendar?error=google")
            self.assertEqual(self.connections(), [])
            self.assertEqual(self.fake.tables["provider_connection_credentials"], [])

    def test_expired_state(self):
        state = self.authorize()
        old = datetime.now(timezone.utc) - timedelta(minutes=16)
        self.fake.tables["provider_connection_credentials"][0]["oauth_state_created_at"] = old.isoformat()
        r = self.client.get("/api/calendar/google/callback", params={"state": state, "code": "good-code"})
        self.assertEqual(r.headers["location"], "http://localhost:3000/calendar?error=google")
        self.assertEqual(self.connections(), [])

    def test_reconnecting_replaces_the_old_connection(self):
        self.connect()
        self.authorize()  # abandoned attempt
        self.connect()
        self.assertEqual([c["status"] for c in self.connections()], ["connected"])
        self.assertEqual(len(self.fake.tables["provider_connection_credentials"]), 1)
        self.assertEqual(self.fake.revoked, ["rt-1"])

    # --------------------------------------------------------------- sync --
    def test_sync_imports_only_what_the_engine_should_see(self):
        self.connect()
        self.fake.events["me@example.com"] = [
            meeting("m1", attendees=[{"self": True, "responseStatus": "accepted"}, {"email": "x@example.com", "displayName": "X", "responseStatus": "accepted"},
                                     {"email": "room@example.com", "resource": True}], description="secret agenda", location="Office"),
            meeting("gym", summary="Gym"), meeting("focus", eventType="focusTime"),
            meeting("declined", attendees=[{"self": True, "responseStatus": "declined"}]),
            meeting("cancelled", status="cancelled"), meeting("ooo", eventType="outOfOffice"),
            {"id": "allday", "summary": "Conference", "start": {"date": "2026-10-13"}, "end": {"date": "2026-10-14"}},
        ]
        r = self.client.post("/api/calendar/google/sync")
        self.assertEqual((r.status_code, r.json()), (200, {"imported": 3}))
        rows = {r["provider_event_id"]: r for r in self.fake.tables["calendar_events"]}
        self.assertEqual(sorted(rows), ["me@example.com:focus", "me@example.com:gym", "me@example.com:m1"])
        m1 = rows["me@example.com:m1"]
        self.assertEqual((m1["category"], m1["location"], m1["description"], m1["guests"]), ("meeting", "Office", None, [{"response_status": "accepted"}]))
        self.assertEqual((rows["me@example.com:gym"]["category"], rows["me@example.com:focus"]["category"]), ("workout", "focus"))
        self.assertNotIn("x@example.com", json.dumps(self.fake.tables["calendar_events"]))
        self.assertIsNotNone(self.connections()[0]["last_synced_at"])

    def test_resync_keeps_ids_drops_stale_and_keeps_history(self):
        self.connect()
        history = {"id": "h", "user_id": "user-a", "provider": "google_calendar", "provider_event_id": "me@example.com:old", "starts_at": at(-200)}
        someone_else = {"id": "s", "user_id": "user-b", "provider": "google_calendar", "provider_event_id": "b:1", "starts_at": at(1)}
        self.fake.tables["calendar_events"] += [history, someone_else]
        self.fake.events["me@example.com"] = [meeting("a"), meeting("b")]
        self.client.post("/api/calendar/google/sync")
        ids = {r["provider_event_id"]: r["id"] for r in self.fake.tables["calendar_events"]}
        self.fake.events["me@example.com"] = [meeting("a"), meeting("c")]
        self.assertEqual(self.client.post("/api/calendar/google/sync").json(), {"imported": 2})
        after = {r["provider_event_id"]: r["id"] for r in self.fake.tables["calendar_events"]}
        self.assertEqual(sorted(after), ["b:1", "me@example.com:a", "me@example.com:c", "me@example.com:old"])
        self.assertEqual(after["me@example.com:a"], ids["me@example.com:a"])

    def test_failed_write_does_not_lose_events(self):
        self.connect()
        self.fake.events["me@example.com"] = [meeting("a")]
        self.client.post("/api/calendar/google/sync")
        self.fake.events["me@example.com"] = [meeting("b")]
        self.fake.fail_upsert = True
        self.assertEqual(self.client.post("/api/calendar/google/sync").status_code, 502)
        self.assertEqual([r["provider_event_id"] for r in self.fake.tables["calendar_events"]], ["me@example.com:a"])

    def test_sync_needs_a_connection_and_a_live_authorization(self):
        self.assertEqual(self.client.post("/api/calendar/google/sync").status_code, 400)
        self.connect()
        self.fake.revoked.append("rt-1")  # the user removed the app's access at Google
        r = self.client.post("/api/calendar/google/sync")
        self.assertEqual(r.status_code, 409)
        self.assertIn("reconnect", r.json()["error"])
        self.assertEqual(self.connections()[0]["status"], "error")

    def test_users_only_touch_their_own_rows(self):
        self.connect()
        self.fake.events["me@example.com"] = [meeting("a")]
        self.client.post("/api/calendar/google/sync")
        type(self).user = "user-b"
        self.assertEqual(self.client.get("/api/calendar/google").json(), {"connections": []})
        self.assertEqual(self.client.post("/api/calendar/google/disconnect").json(), {"disconnected": True})
        self.assertEqual((len(self.connections()), len(self.fake.tables["calendar_events"]), self.fake.revoked), (1, 1, []))

    def test_disconnect(self):
        self.connect()
        self.fake.events["me@example.com"] = [meeting("a")]
        self.client.post("/api/calendar/google/sync")
        self.assertEqual(self.client.post("/api/calendar/google/disconnect").json(), {"disconnected": True})
        self.assertEqual(self.fake.tables, {"provider_connections": [], "provider_connection_credentials": [], "calendar_events": []})
        self.assertEqual(self.fake.revoked, ["rt-1"])


if __name__ == "__main__":
    unittest.main()
