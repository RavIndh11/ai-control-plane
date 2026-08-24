import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from agents.nodes.generation import generation_node, _rag_context

def test_rag_context_no_client():
    with patch("agents.nodes.generation._qdrant_client", None):
        assert _rag_context("test", "t1") == ""

@patch("agents.nodes.generation.httpx.Client")
@patch("agents.nodes.generation._qdrant_client")
def test_rag_context_success(mock_qdrant, mock_client):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"data": [{"embedding": [0.1, 0.2]}]}
    mock_client.return_value.__enter__.return_value.post.return_value = mock_res
    
    mock_hit1 = MagicMock()
    mock_hit1.payload = {"content": "hit 1"}
    mock_hit2 = MagicMock()
    mock_hit2.payload = {"content": "hit 2"}
    mock_qdrant.search.return_value = [mock_hit1, mock_hit2]
    
    ctx = _rag_context("test", "t1")
    assert ctx == "hit 1\nhit 2"

def test_generation_node_unsafe():
    state = {"is_safe": False, "input": "test"}
    result = generation_node(state)
    assert result == state
    
def test_generation_node_already_output():
    state = {"is_safe": True, "output": "exists", "input": "test"}
    result = generation_node(state)
    assert result == state

@patch("agents.nodes.generation.httpx.Client")
@patch("agents.nodes.generation._rag_context", return_value="context")
def test_generation_node_success(mock_rag, mock_client):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "choices": [{"message": {"content": "generated response"}}]
    }
    mock_client.return_value.__enter__.return_value.post.return_value = mock_res
    
    state = {"is_safe": True, "tenant_id": "t1", "input": "hello"}
    
    with patch("agents.nodes.generation.Guard") as mock_guard:
        result = generation_node(state)
        assert result["output"] == "generated response"
        mock_guard.return_value.use.return_value.validate.assert_called_once_with("generated response")

@patch("agents.nodes.generation.httpx.Client")
@patch("agents.nodes.generation._rag_context", return_value="")
def test_generation_node_guardrail_failure(mock_rag, mock_client):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "choices": [{"message": {"content": "BEGIN RSA PRIVATE KEY generated response"}}]
    }
    mock_client.return_value.__enter__.return_value.post.return_value = mock_res
    
    state = {"is_safe": True, "tenant_id": "t1", "input": "hello"}
    
    result = generation_node(state)
    assert result["is_safe"] is False
    assert "blocked" in result["output"].lower()

@patch("agents.nodes.generation.httpx.Client")
def test_generation_node_network_error(mock_client):
    mock_client.return_value.__enter__.return_value.post.side_effect = Exception("network error")
    
    state = {"is_safe": True, "tenant_id": "t1", "input": "hello"}
    
    with pytest.raises(HTTPException) as exc:
        generation_node(state)
    assert exc.value.status_code == 502
