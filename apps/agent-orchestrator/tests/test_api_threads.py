import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from db.models import DBAgentThread, DBAgentCheckpoint

def test_create_thread(client, mock_db_session, mock_principal):
    response = client.post("/api/v1/threads", json={"agent_type": "test_agent"})
    assert response.status_code == 200
    data = response.json()
    assert "thread_id" in data
    assert data["status"] == "idle"
    assert "created_at" in data
    assert mock_db_session.add.call_count == 2
    assert mock_db_session.commit.call_count == 1

def test_create_thread_empty_agent_type(client):
    response = client.post("/api/v1/threads", json={"agent_type": ""})
    assert response.status_code == 422 # Pydantic validation error

def test_get_thread_state_not_found(client, mock_db_session):
    mock_db_session.query.return_value.filter.return_value.first.return_value = None
    response = client.get("/api/v1/threads/th_123/state")
    assert response.status_code == 404

def test_get_thread_state_success(client, mock_db_session):
    mock_thread = DBAgentThread(thread_id="th_123", tenant_id="tenant-test", agent_type="test_agent")
    
    mock_cp = DBAgentCheckpoint(
        checkpoint_id="cp_1", 
        timestamp=datetime.utcnow(), 
        step="init", 
        state_data={"steps": ["init"]}
    )
    
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_thread
    
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_cp]
    
    response = client.get("/api/v1/threads/th_123/state")
    assert response.status_code == 200
    data = response.json()
    assert data["thread_id"] == "th_123"
    assert len(data["history"]) == 1
    assert data["history"][0]["checkpoint_id"] == "cp_1"

def test_get_pending_runs(client, mock_db_session):
    mock_cp = DBAgentCheckpoint(
        thread_id="th_1",
        checkpoint_id="cp_1",
        timestamp=datetime.utcnow(),
        step="wait",
        state_data={"pending_action": "approve_something"}
    )
    
    mock_db_session.query.return_value.order_by.return_value.all.return_value = [mock_cp]
    
    response = client.get("/api/v1/runs/pending")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["thread_id"] == "th_1"

def test_approve_thread_run_not_found(client, mock_db_session):
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    response = client.post("/api/v1/threads/th_123/approve", json={"approve": True})
    assert response.status_code == 404

def test_approve_thread_run_no_pending_action(client, mock_db_session):
    mock_cp = DBAgentCheckpoint(state_data={})
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_cp
    response = client.post("/api/v1/threads/th_123/approve", json={"approve": True})
    assert response.status_code == 400

def test_approve_thread_run_success(client, mock_db_session):
    mock_cp = MagicMock(spec=DBAgentCheckpoint)
    mock_cp.state_data = {"pending_action": "action"}
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_cp
    
    with patch("api.threads.flag_modified") as mock_flag_modified:
        response = client.post("/api/v1/threads/th_123/approve", json={"approve": True})
        
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["action_approved"] is True
        mock_db_session.commit.assert_called_once()
        mock_flag_modified.assert_called_once_with(mock_cp, "state_data")
