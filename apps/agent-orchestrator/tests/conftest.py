import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from main import app
from auth.principal import get_principal
from api.rules import _db_dep as rules_db_dep
from api.threads import _db_dep as threads_db_dep
from api.runs import _db_dep as runs_db_dep

@pytest.fixture
def mock_db_session():
    session = MagicMock(spec=Session)
    return session

@pytest.fixture
def override_db_deps(mock_db_session):
    def _override():
        yield mock_db_session
    app.dependency_overrides[rules_db_dep] = _override
    app.dependency_overrides[threads_db_dep] = _override
    app.dependency_overrides[runs_db_dep] = _override
    yield
    app.dependency_overrides.pop(rules_db_dep, None)
    app.dependency_overrides.pop(threads_db_dep, None)
    app.dependency_overrides.pop(runs_db_dep, None)

@pytest.fixture
def mock_principal():
    return {
        "id": "test_user_id",
        "email": "test@example.com",
        "roles": ["admin"],
        "tenant_id": "tenant-test",
        "auth_method": "jwt",
        "is_agent": False,
    }

@pytest.fixture
def override_get_principal(mock_principal):
    def _override():
        return mock_principal
    app.dependency_overrides[get_principal] = _override
    yield
    app.dependency_overrides.pop(get_principal, None)

@pytest.fixture
def client(override_db_deps, override_get_principal):
    with TestClient(app) as client:
        yield client
