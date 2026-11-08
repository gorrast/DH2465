"""Small authenticated Supabase HTTP client using only the Python standard library."""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class APIError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    # Do not send credentials to a redirected endpoint.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def settings(config):
    url = (config.get('NEXT_PUBLIC_SUPABASE_URL') or config.get('SUPABASE_URL') or '').rstrip('/')
    key = config.get('NEXT_PUBLIC_SUPABASE_ANON_KEY') or config.get('SUPABASE_PUBLISHABLE_KEY') or ''
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path:
        raise APIError('Fill NEXT_PUBLIC_SUPABASE_URL with your HTTPS project URL, without a path.')
    if not key or key.startswith('sb_secret_'):
        raise APIError('Fill NEXT_PUBLIC_SUPABASE_ANON_KEY with a publishable key; secret keys are not supported.')
    if not key.startswith('sb_publishable_'):
        try:
            claims = json.loads(base64.urlsafe_b64decode(key.split('.')[1] + '==='))
        except (ValueError, IndexError):
            raise APIError('Expected a publishable key or legacy anon key.') from None
        if claims.get('role') != 'anon':
            raise APIError('Use a publishable/anon key, not an elevated service-role key.')
    return url, key, hashlib.sha256(('supabase-api-v1:' + url).encode()).hexdigest()


class Client:
    def __init__(self, url, key, opener=None, sleep=time.sleep):
        self.url, self.key = url, key
        self.opener = opener or build_opener(NoRedirect())
        self.sleep = sleep
        self.access_token = self.refresh_token = self.user_id = None
        self.expires_at = 0

    def _request(self, method, path, data=None, authenticated=True, retry=True):
        allowed = ((method == 'GET' and path in ('/auth/v1/user', '/functions/v1/apple-import'))
                   or (method == 'POST' and path in ('/auth/v1/token?grant_type=password',
                       '/auth/v1/token?grant_type=refresh_token', '/functions/v1/apple-import')))
        if not allowed:
            raise APIError('Only authentication and the standalone Apple endpoint are supported.')
        if authenticated and not self.access_token:
            raise APIError('Sign in before making a data request.')
        if authenticated and self.refresh_token and self.expires_at and time.time() >= self.expires_at - 60:
            self.refresh()
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode() if data is not None else None
        refreshed = False
        for attempt in range(5):
            headers = {'apikey': self.key, 'Content-Type': 'application/json', 'Accept': 'application/json'}
            if authenticated:
                headers['Authorization'] = 'Bearer ' + self.access_token
            request = Request(self.url + path, data=body, headers=headers, method=method)
            try:
                with self.opener.open(request, timeout=30) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None
            except HTTPError as exc:
                # Never display the response body: auth errors or SQL diagnostics
                # can include tokens, credentials or private measurement values.
                exc.close()
                if exc.code == 401 and authenticated and self.refresh_token and not refreshed:
                    self.refresh()
                    refreshed = True
                    continue
                if retry and exc.code in (429, 502, 503, 504) and attempt < 4:
                    self.sleep(min(2 ** attempt, 8))
                    continue
                if exc.code in (401, 403):
                    raise APIError(f'HTTP {exc.code}: sign-in failed/expired or access was denied by your app permissions.') from None
                if exc.code in (400, 404, 413, 415):
                    raise APIError(f'HTTP {exc.code}: the standalone endpoint is missing or the batch is invalid. See README.md.') from None
                if exc.code == 409:
                    raise APIError('HTTP 409: missing or incompatible registry definitions; stop and review registry_review.sql.') from None
                raise APIError(f'Supabase request failed (HTTP {exc.code}); the batch can be retried.') from None
            except (URLError, TimeoutError, OSError):
                if retry and attempt < 4:
                    self.sleep(min(2 ** attempt, 8))
                    continue
                raise APIError('Could not reach Supabase securely. Check the project URL/network, then resume.') from None
        raise APIError('Supabase request failed after retries; resume the run.')

    def _session(self, session):
        if not isinstance(session, dict) or not session.get('access_token'):
            raise APIError('The login response did not contain a user session.')
        self.access_token = session['access_token']
        self.refresh_token = session.get('refresh_token') or self.refresh_token
        self.expires_at = session.get('expires_at') or (time.time() + session.get('expires_in', 3600))

    def login(self, config):
        token = config.get('SUPABASE_ACCESS_TOKEN', '')
        if token:
            self.access_token = token
            self.refresh_token = config.get('SUPABASE_REFRESH_TOKEN') or None
        else:
            email = config.get('SUPABASE_EMAIL', '').strip()
            if not email:
                raise APIError('Set SUPABASE_EMAIL for app-user login, or SUPABASE_ACCESS_TOKEN for an existing signed-in session.')
            password = config.get('SUPABASE_PASSWORD') or getpass.getpass('App user password (not your Supabase dashboard password): ')
            self._session(self._request('POST', '/auth/v1/token?grant_type=password',
                                        {'email': email, 'password': password}, authenticated=False, retry=False))
        user = self._request('GET', '/auth/v1/user')
        if not isinstance(user, dict) or not user.get('id') or user.get('is_anonymous'):
            raise APIError('An existing, non-anonymous app user must sign in.')
        self.user_id = user['id']
        return self.user_id

    def refresh(self):
        if not self.refresh_token:
            raise APIError('Your access token expired. Sign in again and resume the saved run.')
        # Refresh tokens rotate. Retain the new token in memory only, and do not
        # retry an ambiguous refresh request with a potentially consumed token.
        self._session(self._request('POST', '/auth/v1/token?grant_type=refresh_token',
                                    {'refresh_token': self.refresh_token}, authenticated=False, retry=False))
        user = self._request('GET', '/auth/v1/user')
        if self.user_id and user.get('id') != self.user_id:
            raise APIError('Refreshed session belongs to a different user; stopped.')

    def rpc(self, name, data=None):
        raise APIError('The old database-function uploader is disabled. Use the standalone Edge Function.')

    def preflight(self):
        result = self._request('GET', '/functions/v1/apple-import')
        if (not isinstance(result, dict) or result.get('version') != 1 or result.get('contract_version') != 3
                or result.get('user_id') != self.user_id or result.get('mode') != 'append-only'
                or result.get('writes_existing_rows') is not False or result.get('changes_schema') is not False
                or result.get('tables') != ['source_records', 'daily_metrics']
                or result.get('project_ref') != urlsplit(self.url).hostname.split('.')[0]):
            raise APIError('The endpoint does not match the reviewed append-only contract; stopped.')
        self.project_ref = result['project_ref']
        return result

    def import_batch(self, table, rows, preview=True):
        if table not in ('source_records', 'daily_metrics') or not getattr(self, 'project_ref', None):
            raise APIError('Check the standalone endpoint before importing.')
        result = self._request('POST', '/functions/v1/apple-import', dict(
            action='preview' if preview else 'insert', table=table, rows=rows,
            expected_user_id=self.user_id, expected_project_ref=self.project_ref))
        keys = ('would_insert', 'would_skip') if preview else ('inserted', 'skipped')
        if (not isinstance(result, dict) or result.get('submitted') != len(rows)
                or any(type(result.get(k)) is not int or result[k] < 0 for k in keys)
                or sum(result[k] for k in keys) != len(rows)
                or preview and result.get('writes') != 0):
            raise APIError('Unexpected import response; stopped.')
        return result

