"""Supabase authentication for the API: verify the caller's access token and open their UserStore.

Tokens are verified locally — with the project's JWKS (asymmetric signing keys, the Supabase default) or with
SUPABASE_JWT_SECRET (legacy HS256 projects). If neither works the token is checked against Supabase Auth itself.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Optional

import httpx
import jwt
from fastapi import Request

from ..engine.pipeline import EngineError
from ..store import SupabaseStore, UserStore

log = logging.getLogger("stressless.server.auth")


class Unauthorized(EngineError):
    status = 401


@dataclass
class Principal:
    user_id: str
    store: UserStore


def supabase_url() -> str:
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    if not url:
        raise EngineError("Server misconfigured: NEXT_PUBLIC_SUPABASE_URL is not set")
    return url.rstrip("/")


def supabase_key() -> str:
    key = (os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
           or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY"))
    if not key:
        raise EngineError("Server misconfigured: NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY is not set")
    return key


_jwks_lock = threading.Lock()
_jwks: Optional[jwt.PyJWKClient] = None


def _jwks_client() -> jwt.PyJWKClient:
    global _jwks
    with _jwks_lock:
        if _jwks is None:
            _jwks = jwt.PyJWKClient(supabase_url() + "/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=600)
        return _jwks


def _verify_remote(token: str) -> str:
    """Last resort: ask Supabase Auth who this token belongs to."""
    try:
        r = httpx.get(supabase_url() + "/auth/v1/user", headers={"apikey": supabase_key(), "Authorization": "Bearer " + token}, timeout=10.0)
    except httpx.HTTPError as exc:
        raise Unauthorized("Could not verify session: %s" % exc)
    if r.status_code != 200:
        raise Unauthorized("Session expired or invalid — please sign in again.")
    return str(r.json()["id"])


def verify_token(token: str) -> str:
    """Return the user id (``sub``) of a valid Supabase access token, or raise Unauthorized."""
    try:
        secret = os.environ.get("SUPABASE_JWT_SECRET")
        if secret:
            claims = jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
        else:
            header = jwt.get_unverified_header(token)
            if header.get("alg") == "HS256":
                return _verify_remote(token)
            key = _jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["ES256", "RS256", "EdDSA"], audience="authenticated")
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Session expired — please sign in again.")
    except jwt.PyJWKClientError as exc:
        log.warning("JWKS lookup failed (%s); verifying with Supabase Auth", exc)
        return _verify_remote(token)
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("Invalid session token: %s" % exc)
    sub = claims.get("sub")
    if not sub:
        raise Unauthorized("Session token has no subject")
    return str(sub)


def current_principal(request: Request) -> Principal:
    """FastAPI dependency: the signed-in user and their store. Tests override this."""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise Unauthorized("Not signed in")
    token = auth[7:].strip()
    user_id = verify_token(token)
    return Principal(user_id=user_id, store=SupabaseStore(supabase_url(), supabase_key(), token, user_id))
