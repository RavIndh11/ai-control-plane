from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import HTTPException, Request, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
import httpx

try:
    from jose import jwt, JWTError
    HAS_JOSE = True
except ImportError:
    HAS_JOSE = False

from config import KEYCLOAK_JWKS_URL, KEYCLOAK_AUDIENCE, KEYCLOAK_ISSUER, DATABASE_URL
from database import SessionLocal

_gov_jwks_cache: Optional[Dict] = None
_gov_jwks_fetched_at: Optional[datetime] = None
JWKS_CACHE_TTL_SECONDS = 300

def _get_jwks() -> Optional[Dict]:
    global _gov_jwks_cache, _gov_jwks_fetched_at
    if not KEYCLOAK_JWKS_URL:
        return None
    now = datetime.utcnow()
    if _gov_jwks_cache and _gov_jwks_fetched_at and (now - _gov_jwks_fetched_at).total_seconds() < JWKS_CACHE_TTL_SECONDS:
        return _gov_jwks_cache
    try:
        with httpx.Client() as client:
            res = client.get(KEYCLOAK_JWKS_URL, timeout=3.0)
            if res.status_code == 200:
                _gov_jwks_cache = res.json()
                _gov_jwks_fetched_at = now
                return _gov_jwks_cache
    except Exception as e:
        print(f"[Auth] Failed to fetch JWKS: {e}")
    return None

def get_principal(request: Request) -> Dict[str, Any]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and HAS_JOSE and KEYCLOAK_JWKS_URL:
        token = auth_header[len("Bearer "):].strip()
        jwks = _get_jwks()
        if jwks:
            try:
                unverified_header = jwt.get_unverified_header(token)
                matching_key = next(
                    (k for k in jwks.get("keys", []) if k.get("kid") == unverified_header.get("kid")), None
                )
                if not matching_key:
                    raise HTTPException(status_code=401, detail="JWT signing key not found")
                claims = jwt.decode(
                    token, matching_key, algorithms=["RS256"],
                    audience=KEYCLOAK_AUDIENCE,
                    issuer=KEYCLOAK_ISSUER or None,
                    options={"verify_iss": bool(KEYCLOAK_ISSUER)},
                )
                realm_roles = claims.get("realm_access", {}).get("roles", [])
                tenant_claim = claims.get("tenant_id") or claims.get("organization") or ""
                
                client_id = claims.get("clientId") or claims.get("client_id")
                is_agent = bool(client_id)

                return {
                    "id": client_id if is_agent else claims.get("sub", ""), 
                    "email": claims.get("email", ""),
                    "roles": realm_roles, 
                    "tenant_id": tenant_claim, 
                    "auth_method": "jwt",
                    "is_agent": is_agent
                }
            except JWTError as e:
                raise HTTPException(status_code=401, detail=f"Invalid JWT token: {e}")
        else:
            raise HTTPException(status_code=503, detail="Auth service unavailable")

    raise HTTPException(status_code=401, detail="Unauthorized: Provide a valid Bearer JWT.")

def get_db(principal: Dict[str, Any] = Depends(get_principal)):
    db = SessionLocal()
    tenant_id = principal.get("tenant_id", "default")
    if not DATABASE_URL.startswith("sqlite") and tenant_id:
        schema_name = f"tenant_{tenant_id.replace('-', '_')}"
        try:
            db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name};"))
            db.execute(text(f"SET search_path TO {schema_name}, public;"))
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS compliance_evidence (
                    evidence_id       VARCHAR(36)  PRIMARY KEY,
                    tenant_id         VARCHAR(64)  NOT NULL,
                    control_id        VARCHAR(100) NOT NULL,
                    source_component  VARCHAR(100) NOT NULL,
                    event_type        VARCHAR(100) NOT NULL,
                    severity          VARCHAR(20)  NOT NULL,
                    payload           JSON         NOT NULL,
                    minio_object_path VARCHAR(512),
                    evidence_hmac     VARCHAR(64),
                    created_at        TIMESTAMP WITHOUT TIME ZONE
                                      DEFAULT timezone('utc'::text, now())
                );
            """))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[Database] Error setting up schema/tables: {e}")
    try:
        yield db
    finally:
        db.close()

def is_authorized(principal: Dict[str, Any], resource_kind: str, resource_id: str, action: str, resource_attr: Dict[str, Any]) -> bool:
    roles = principal["roles"]
    tenant_id = principal["tenant_id"]
    res_tenant_id = resource_attr.get("tenant_id")

    if "super-admin" in roles:
        return True
    if action == "create":
        return bool(set(roles) & {"system-workload", "agent-orchestrator", "tenant-admin", "tenant-user"})
    if action == "read":
        if "compliance-auditor" in roles:
            return True
        if "tenant-admin" in roles and tenant_id == res_tenant_id:
            return True
    return False
