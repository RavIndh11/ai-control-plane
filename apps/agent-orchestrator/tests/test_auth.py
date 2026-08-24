import pytest
from unittest.mock import patch, MagicMock
from fastapi import Request, HTTPException
from jose import JWTError

from auth.jwt import verify_jwt
from auth.principal import get_principal

def test_verify_jwt_no_jose():
    with patch("auth.jwt.HAS_JOSE", False):
        assert verify_jwt("token") is None

def test_verify_jwt_no_jwks():
    with patch("auth.jwt.HAS_JOSE", True), patch("auth.jwt._get_jwks", return_value=None):
        assert verify_jwt("token") is None

def test_verify_jwt_invalid_token():
    with patch("auth.jwt.HAS_JOSE", True), \
         patch("auth.jwt._get_jwks", return_value={"keys": [{"kid": "test-kid"}]}):
        # Mock jose.jwt to raise JWTError inside verify_jwt
        with patch("auth.jwt.jose_jwt.get_unverified_header", return_value={"kid": "test-kid"}), \
             patch("auth.jwt.jose_jwt.decode", side_effect=JWTError("Test error")):
            with pytest.raises(JWTError):
                verify_jwt("token")

def test_verify_jwt_success():
    with patch("auth.jwt.HAS_JOSE", True), \
         patch("auth.jwt._get_jwks", return_value={"keys": [{"kid": "test-kid"}]}):
        with patch("auth.jwt.jose_jwt.get_unverified_header", return_value={"kid": "test-kid"}), \
             patch("auth.jwt.jose_jwt.decode", return_value={"sub": "user_id"}):
            claims = verify_jwt("token")
            assert claims == {"sub": "user_id"}

def test_get_principal_missing_auth():
    req = MagicMock(spec=Request)
    req.headers = {}
    with pytest.raises(HTTPException) as exc:
        get_principal(req)
    assert exc.value.status_code == 401
    assert "Provide a valid Bearer JWT" in str(exc.value.detail)

def test_get_principal_success():
    req = MagicMock(spec=Request)
    req.headers = {"Authorization": "Bearer valid_token"}
    claims = {
        "realm_access": {"roles": ["admin"]},
        "tenant_id": "tenant123",
        "sub": "user_123",
        "email": "test@example.com"
    }
    with patch("auth.principal.HAS_JOSE", True), \
         patch("auth.principal.KEYCLOAK_JWKS_URL", "http://test"), \
         patch("auth.principal.verify_jwt", return_value=claims):
        principal = get_principal(req)
        assert principal["id"] == "user_123"
        assert principal["tenant_id"] == "tenant123"
        assert principal["roles"] == ["admin"]
        assert principal["auth_method"] == "jwt"
        assert principal["is_agent"] is False

def test_get_principal_agent_client():
    req = MagicMock(spec=Request)
    req.headers = {"Authorization": "Bearer valid_token"}
    claims = {
        "clientId": "agent-1",
        "organization": "tenant123",
    }
    with patch("auth.principal.HAS_JOSE", True), \
         patch("auth.principal.KEYCLOAK_JWKS_URL", "http://test"), \
         patch("auth.principal.verify_jwt", return_value=claims):
        principal = get_principal(req)
        assert principal["id"] == "agent-1"
        assert principal["tenant_id"] == "tenant123"
        assert principal["is_agent"] is True

def test_get_principal_invalid_token():
    req = MagicMock(spec=Request)
    req.headers = {"Authorization": "Bearer invalid_token"}
    with patch("auth.principal.HAS_JOSE", True), \
         patch("auth.principal.KEYCLOAK_JWKS_URL", "http://test"), \
         patch("auth.principal.verify_jwt", side_effect=Exception("error")):
        with pytest.raises(HTTPException) as exc:
            get_principal(req)
        assert exc.value.status_code == 401
        assert "Invalid JWT" in str(exc.value.detail)

def test_get_principal_unavailable():
    req = MagicMock(spec=Request)
    req.headers = {"Authorization": "Bearer valid_token"}
    with patch("auth.principal.HAS_JOSE", True), \
         patch("auth.principal.KEYCLOAK_JWKS_URL", "http://test"), \
         patch("auth.principal.verify_jwt", return_value=None):
        with pytest.raises(HTTPException) as exc:
            get_principal(req)
        assert exc.value.status_code == 503
