"""
auth/principal.py — FastAPI dependency that resolves the caller's identity.

Supports two modes:
  1. Bearer JWT from Keycloak (production)
  2. X-Tenant-ID / X-User-Role / X-User-ID headers (local dev fallback)

Also exposes make_db_dep() which wires together get_principal + get_db
so route handlers need only a single Depends().
"""
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request

from auth.jwt import HAS_JOSE, KEYCLOAK_JWKS_URL, verify_jwt


def get_principal(
    request: Request,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    x_user_role: Optional[str]  = Header(None, alias="X-User-Role"),
    x_user_id: Optional[str]    = Header(None, alias="X-User-ID"),
) -> Dict[str, Any]:
    """
    Resolve the caller principal from:
      - Authorization: Bearer <jwt>   (Keycloak, production)
      - X-Tenant-ID / X-User-Role     (header fallback, local dev)

    Returns a normalized principal dict:
      {
        id:          str   (user sub / user_default)
        email:       str
        roles:       list[str]
        tenant_id:   str
        auth_method: 'jwt' | 'header'
      }
    """
    auth_header: str = request.headers.get("Authorization", "")

    # ── Mode 1: JWT Bearer (Keycloak) ────────────────────────────────────────
    if auth_header.startswith("Bearer ") and HAS_JOSE and KEYCLOAK_JWKS_URL:
        token = auth_header[len("Bearer "):].strip()
        try:
            claims = verify_jwt(token)
            if claims:
                realm_roles = claims.get("realm_access", {}).get("roles", [])
                tenant_claim = (
                    claims.get("tenant_id")
                    or claims.get("organization")
                    or ""
                )
                # Determine if this is an Agent (Client Credentials) or Human
                client_id = claims.get("clientId") or claims.get("client_id")
                is_agent = bool(client_id)
                
                return {
                    "id":          client_id if is_agent else claims.get("sub", ""),
                    "email":       claims.get("email", ""),
                    "roles":       realm_roles,
                    "tenant_id":   tenant_claim,
                    "auth_method": "jwt",
                    "is_agent":    is_agent,
                }
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Invalid JWT: {exc}")
        raise HTTPException(status_code=503, detail="Auth service (Keycloak JWKS) unavailable")

    # ── Mode 2: Header fallback (local dev) ───────────────────────────────────
    if not x_tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Provide a Bearer JWT or X-Tenant-ID header (dev mode).",
        )
    return {
        "id":          x_user_id or "user_default",
        "email":       "",
        "roles":       [x_user_role or "tenant-user"],
        "tenant_id":   x_tenant_id,
        "auth_method": "header",
        "is_agent":    False,  # Dev headers default to human
    }
