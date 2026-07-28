"""
auth/jwt.py — Keycloak JWKS fetching and JWT verification.

Provides:
  verify_jwt(token) -> claims dict
  _get_jwks()       -> cached JWKS keys
"""
import os
from datetime import datetime
from typing import Dict, Optional

import httpx

KEYCLOAK_JWKS_URL: str  = os.getenv("KEYCLOAK_JWKS_URL", "")
KEYCLOAK_AUDIENCE: str  = os.getenv("KEYCLOAK_AUDIENCE", "ai-control-plane")
KEYCLOAK_ISSUER: str    = os.getenv("KEYCLOAK_ISSUER", "")
JWKS_CACHE_TTL: int     = 300  # seconds

try:
    from jose import jwt, JWTError
    HAS_JOSE = True
except ImportError:
    HAS_JOSE = False

_jwks_cache: Optional[Dict] = None
_jwks_fetched_at: Optional[datetime] = None


def _get_jwks() -> Optional[Dict]:
    """Fetch and cache Keycloak JWKS public keys."""
    global _jwks_cache, _jwks_fetched_at
    if not KEYCLOAK_JWKS_URL:
        return None
    now = datetime.utcnow()
    if (
        _jwks_cache
        and _jwks_fetched_at
        and (now - _jwks_fetched_at).total_seconds() < JWKS_CACHE_TTL
    ):
        return _jwks_cache
    try:
        with httpx.Client(timeout=3.0) as client:
            res = client.get(KEYCLOAK_JWKS_URL)
            if res.status_code == 200:
                _jwks_cache = res.json()
                _jwks_fetched_at = now
                return _jwks_cache
    except Exception as exc:
        print(f"[Auth] JWKS fetch failed: {exc}")
    return None


def verify_jwt(token: str) -> Optional[Dict]:
    """
    Verify a Bearer JWT against Keycloak JWKS.
    Returns the decoded claims dict on success, or None if JWKS unavailable.
    Raises jose.JWTError on invalid token.
    """
    if not HAS_JOSE:
        return None
    jwks = _get_jwks()
    if not jwks:
        return None

    from jose import jwt as jose_jwt, JWTError  # noqa: F401

    unverified_header = jose_jwt.get_unverified_header(token)
    matching_key = next(
        (k for k in jwks.get("keys", []) if k.get("kid") == unverified_header.get("kid")),
        None,
    )
    if matching_key is None:
        from jose import JWTError
        raise JWTError("JWT signing key not found in JWKS")

    claims = jose_jwt.decode(
        token,
        matching_key,
        algorithms=["RS256"],
        audience=KEYCLOAK_AUDIENCE,
        issuer=KEYCLOAK_ISSUER or None,
        options={"verify_iss": bool(KEYCLOAK_ISSUER)},
    )
    return claims
