import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
import os

# Set environment variables for tests
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["KEYCLOAK_JWKS_URL"] = "http://localhost:8080/jwks"
os.environ["ALERT_WEBHOOK_URL"] = "http://localhost:8080/webhook"
os.environ["CERBOS_URL"] = "http://localhost:3592"

from main import app
from auth import get_db, get_principal

@pytest.fixture
def mock_db_session():
    session = MagicMock(spec=Session)
    return session

@pytest.fixture
def client(mock_db_session):
    def override_get_db():
        yield mock_db_session

    def override_get_principal():
        return {
            "id": "test-user",
            "email": "test@example.com",
            "roles": ["tenant-admin"],
            "tenant_id": "test-tenant",
            "auth_method": "jwt",
            "is_agent": False
        }
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_principal] = override_get_principal
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def mock_httpx():
    with patch("auth.httpx.Client") as mock_auth_client, \
         patch("services.httpx.Client") as mock_services_client:
        
        # Mock auth JWKS response
        mock_auth_instance = mock_auth_client.return_value.__enter__.return_value
        mock_auth_instance.get.return_value = MagicMock(
            status_code=200, 
            json=lambda: {"keys": [{"kid": "test-kid", "kty": "RSA"}]}
        )
        
        
        # Mock webhook post
        mock_services_instance = mock_services_client.return_value.__enter__.return_value
        mock_services_instance.post.return_value = MagicMock(status_code=200)
        
        yield
