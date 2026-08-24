import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from db.models import DBAgentThread, DBAgentCheckpoint

@pytest.fixture
def mock_graph():
    with patch("api.runs.get_graph") as mock_get_graph:
        graph = MagicMock()
        mock_get_graph.return_value = graph
        yield graph

def test_run_thread_missing_input(client, mock_db_session):
    mock_thread = DBAgentThread(thread_id="th_1", tenant_id="tenant-test", agent_type="agent")
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_thread
    
    # Missing input for new run
    mock_cp = DBAgentCheckpoint(state_data={"steps": []})
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_cp
    
    response = client.post("/api/v1/threads/th_1/runs", json={})
    assert response.status_code == 400
    assert "Missing 'input' field" in response.json()["detail"]

def test_run_thread_thread_not_found(client, mock_db_session):
    mock_db_session.query.return_value.filter.return_value.first.return_value = None
    response = client.post("/api/v1/threads/th_1/runs", json={"input": "test"})
    assert response.status_code == 404

def test_run_thread_no_checkpoints(client, mock_db_session):
    mock_thread = DBAgentThread(thread_id="th_1", tenant_id="tenant-test", agent_type="agent")
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_thread
    
    # No checkpoint history
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    
    response = client.post("/api/v1/threads/th_1/runs", json={"input": "test"})
    assert response.status_code == 500

def test_run_thread_hitl_resume_missing_approve_action(client, mock_db_session):
    mock_thread = DBAgentThread(thread_id="th_1", tenant_id="tenant-test", agent_type="agent")
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_thread
    
    mock_cp = DBAgentCheckpoint(state_data={"pending_action": "approve"})
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_cp
    
    response = client.post("/api/v1/threads/th_1/runs", json={})
    assert response.status_code == 400
    assert "HITL Action Pending" in response.json()["detail"]

def test_run_thread_hitl_resume_forbidden(client, mock_db_session):
    mock_thread = DBAgentThread(thread_id="th_1", tenant_id="tenant-test", agent_type="agent")
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_thread
    
    mock_cp = DBAgentCheckpoint(state_data={"pending_action": "approve", "approval_chain": ["superadmin"]})
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_cp
    
    # User only has 'admin', not 'superadmin'
    response = client.post("/api/v1/threads/th_1/runs", json={"approve_action": True})
    assert response.status_code == 403

def test_run_thread_success(client, mock_db_session, mock_graph):
    mock_thread = DBAgentThread(thread_id="th_1", tenant_id="tenant-test", agent_type="agent")
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_thread
    
    mock_cp = DBAgentCheckpoint(state_data={"steps": []})
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_cp
    
    mock_graph.invoke.return_value = {
        "output": "Test response",
        "steps": ["step1"],
        "pending_action": None
    }
    
    response = client.post("/api/v1/threads/th_1/runs", json={"input": "test input"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["output"]["response"] == "Test response"
    assert "checkpoint_id" in data
    mock_db_session.add.assert_called_once()
    mock_db_session.commit.assert_called_once()

def test_run_thread_action_required(client, mock_db_session, mock_graph):
    mock_thread = DBAgentThread(thread_id="th_1", tenant_id="tenant-test", agent_type="agent")
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_thread
    
    mock_cp = DBAgentCheckpoint(state_data={"steps": []})
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_cp
    
    mock_graph.invoke.return_value = {
        "output": "",
        "steps": ["step1"],
        "pending_action": "approve"
    }
    
    response = client.post("/api/v1/threads/th_1/runs", json={"input": "test input"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "action_required"

@pytest.mark.asyncio
async def test_stream_thread(client, mock_db_session, mock_graph):
    # Just testing the initial setup and error handling of stream, 
    # since testing full async streaming from test client requires specific setups.
    mock_thread = DBAgentThread(thread_id="th_1", tenant_id="tenant-test", agent_type="agent")
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_thread
    
    mock_cp = DBAgentCheckpoint(state_data={"steps": []})
    mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_cp
    
    mock_graph.invoke.return_value = {
        "output": "Test response",
        "steps": ["step1"],
        "pending_action": None,
        "is_safe": True
    }
    
    with patch("api.runs.httpx.AsyncClient") as mock_async_client:
        response = client.post("/api/v1/threads/th_1/runs/stream", json={"input": "test input"})
        assert response.status_code == 200
        # It's a StreamingResponse, so we can iterate its content
        content = b""
        for chunk in response.iter_bytes():
            content += chunk
        
        assert b"data:" in content
        assert b'"event": "step"' in content
        assert b'"status": "completed"' in content
