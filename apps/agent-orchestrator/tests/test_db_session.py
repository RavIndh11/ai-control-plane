import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.session import _seed_default_rules, _setup_postgres_tenant_schema, get_db

def test_seed_default_rules():
    db = MagicMock(spec=Session)
    # mock count == 0
    db.execute.return_value.scalar.return_value = 0
    
    _seed_default_rules(db)
    
    # 5 inserts + 1 count = 6 execute calls
    assert db.execute.call_count == 6
    db.commit.assert_called_once()

def test_seed_default_rules_already_seeded():
    db = MagicMock(spec=Session)
    # mock count == 5
    db.execute.return_value.scalar.return_value = 5
    
    _seed_default_rules(db)
    
    assert db.execute.call_count == 1
    db.commit.assert_not_called()

def test_seed_default_rules_exception():
    db = MagicMock(spec=Session)
    db.execute.side_effect = Exception("DB error")
    
    _seed_default_rules(db)
    
    db.rollback.assert_called_once()

@patch("db.session.DATABASE_URL", "postgresql://test")
def test_setup_postgres_tenant_schema():
    db = MagicMock(spec=Session)
    
    # Needs to be called with a fresh initialized_schemas set
    with patch("db.session._initialized_schemas", set()):
        _setup_postgres_tenant_schema(db, "test-tenant")
        
        # 1 CREATE SCHEMA, 1 SET search_path, 3 CREATE TABLE, 1 SET search_path at end
        assert db.execute.call_count == 6
        db.commit.assert_called_once()

@patch("db.session.DATABASE_URL", "postgresql://test")
def test_setup_postgres_tenant_schema_already_initialized():
    db = MagicMock(spec=Session)
    
    with patch("db.session._initialized_schemas", {"tenant_test_tenant"}):
        _setup_postgres_tenant_schema(db, "test-tenant")
        
        # Only the SET search_path at the end
        assert db.execute.call_count == 1
        db.commit.assert_not_called()

def test_get_db_sqlite():
    principal = {"tenant_id": "test-tenant"}
    
    with patch("db.session.DATABASE_URL", "sqlite:///./test.db"), \
         patch("db.session.SessionLocal") as mock_session_local, \
         patch("db.session._seed_default_rules") as mock_seed:
        
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        db_generator = get_db(principal)
        db = next(db_generator)
        
        assert db == mock_db
        mock_seed.assert_called_once_with(mock_db)
        
        # No postgres specific execution
        mock_db.execute.assert_not_called()
        
        with pytest.raises(StopIteration):
            next(db_generator)
            
        mock_db.close.assert_called_once()

def test_get_db_postgres():
    principal = {"tenant_id": "test-tenant"}
    
    with patch("db.session.DATABASE_URL", "postgresql://test"), \
         patch("db.session.SessionLocal") as mock_session_local, \
         patch("db.session._seed_default_rules"), \
         patch("db.session._setup_postgres_tenant_schema") as mock_setup:
        
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        db_generator = get_db(principal)
        db = next(db_generator)
        
        assert db == mock_db
        mock_setup.assert_called_once_with(mock_db, "test-tenant")
        mock_db.execute.assert_called_once() # SET LOCAL app.current_tenant_id = :tid
