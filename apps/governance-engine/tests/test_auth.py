import pytest
from fastapi import HTTPException
from unittest.mock import patch, MagicMock
from auth import get_principal, is_authorized, get_db

def test_is_authorized():
    principal = {"roles": ["tenant-admin"], "tenant_id": "t1"}
    
    assert is_authorized(principal, "res", "id", "read", {"tenant_id": "t1"}) == True
    assert is_authorized(principal, "res", "id", "read", {"tenant_id": "t2"}) == False
    
    super_principal = {"roles": ["super-admin"], "tenant_id": "t1"}
    assert is_authorized(super_principal, "res", "id", "create", {}) == True
    
    auditor = {"roles": ["compliance-auditor"], "tenant_id": "t1"}
    assert is_authorized(auditor, "res", "id", "read", {"tenant_id": "t2"}) == True

@patch("auth.HAS_JOSE", True)
@patch("auth.KEYCLOAK_JWKS_URL", "http://test")
@patch("auth._get_jwks")
@patch("auth.jwt")
def test_get_principal_success(mock_jwt, mock_get_jwks):
    mock_get_jwks.return_value = {"keys": [{"kid": "test-kid"}]}
    mock_jwt.get_unverified_header.return_value = {"kid": "test-kid"}
    mock_jwt.decode.return_value = {
        "realm_access": {"roles": ["test-role"]},
        "tenant_id": "test-tenant",
        "sub": "user-123"
    }
    
    request = MagicMock()
    request.headers.get.return_value = "Bearer dummy-token"
    
    principal = get_principal(request)
    assert principal["id"] == "user-123"
    assert principal["tenant_id"] == "test-tenant"
    assert principal["roles"] == ["test-role"]

@patch("auth.HAS_JOSE", True)
@patch("auth.KEYCLOAK_JWKS_URL", "http://test")
@patch("auth._get_jwks")
def test_get_principal_invalid_key(mock_get_jwks):
    mock_get_jwks.return_value = None
    request = MagicMock()
    request.headers.get.return_value = "Bearer dummy-token"
    
    with pytest.raises(HTTPException) as exc:
        get_principal(request)
    assert exc.value.status_code == 503

def test_get_principal_no_header():
    request = MagicMock()
    request.headers.get.return_value = ""
    with pytest.raises(HTTPException) as exc:
        get_principal(request)
    assert exc.value.status_code == 401

@patch("auth.DATABASE_URL", "sqlite:///./test.db")
def test_get_db():
    principal = {"tenant_id": "t1"}
    gen = get_db(principal)
    db = next(gen)
    assert db is not None
    # close it
    try:
        next(gen)
    except StopIteration:
        pass
