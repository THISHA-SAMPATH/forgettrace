"""Verify Supabase access tokens before using their identity in database RLS."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient


class AuthenticationError(ValueError):
    """Raised when an access token is missing, invalid, or expired."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    claims: dict[str, Any]


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True, timeout=5)


def _verify_token_sync(token: str, project_url: str) -> AuthenticatedUser:
    base = project_url.rstrip("/")
    issuer = f"{base}/auth/v1"
    jwks_url = f"{issuer}/.well-known/jwks.json"
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            leeway=30,
        )
        user_id = UUID(str(claims["sub"]))
        return AuthenticatedUser(user_id=user_id, claims=claims)
    except Exception as exc:
        # Never return token contents or low-level JWT details to API clients.
        raise AuthenticationError("Invalid or expired Supabase access token.") from exc


async def verify_supabase_access_token(
    token: str, project_url: str
) -> AuthenticatedUser:
    """Verify an asymmetric Supabase JWT without blocking the event loop.

    Configure Supabase Auth to use an asymmetric signing key (ES256 or RS256).
    Legacy HS256 projects need a separately designed secret-based verifier.
    """
    if not token or not project_url:
        raise AuthenticationError("A bearer token and Supabase project URL are required.")
    return await asyncio.to_thread(_verify_token_sync, token, project_url)
