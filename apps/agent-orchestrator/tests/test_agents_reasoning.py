import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from agents.nodes.reasoning import agent_node, _get_tool_risk

def test_get_tool_risk_fallback():
    # If network fails, use fallback map
    with patch("httpx.Client.post", side_effect=Exception("network error")):
        risk = _get_tool_risk("web_search", "tenant1")
        assert risk == 0.3

def test_get_tool_risk_success():
    with patch("httpx.Client") as mock_client:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {"risk_score": 0.42}
        mock_client.return_value.__enter__.return_value.post.return_value = mock_res
        
        risk = _get_tool_risk("custom_tool", "tenant1")
        assert risk == 0.42

@patch("agents.nodes.reasoning.httpx.Client")
@patch("agents.nodes.reasoning.asyncio.run")
def test_agent_node_success_direct_reply(mock_async_run, mock_client):
    mock_async_run.return_value = []
    
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "choices": [{"message": {"content": "direct answer"}}]
    }
    mock_client.return_value.__enter__.return_value.post.return_value = mock_res
    
    state = {"is_safe": True, "tenant_id": "t1", "input": "hello"}
    
    result = agent_node(state)
    assert result["output"] == "direct answer"
    assert "pending_action" not in result

@patch("agents.nodes.reasoning.httpx.Client")
@patch("agents.nodes.reasoning.asyncio.run")
def test_agent_node_tool_call(mock_async_run, mock_client):
    mock_async_run.return_value = []
    
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "choices": [{"message": {
            "tool_calls": [{
                "id": "tc1",
                "function": {"name": "web_search", "arguments": '{"q": "test"}'}
            }]
        }}]
    }
    mock_client.return_value.__enter__.return_value.post.return_value = mock_res
    
    state = {"is_safe": True, "tenant_id": "t1", "input": "hello"}
    
    with patch("agents.nodes.reasoning._get_tool_risk", return_value=0.5):
        result = agent_node(state)
        
        assert "pending_action" in result
        assert result["pending_action"]["tool"] == "web_search"
        assert result["pending_action"]["arguments"] == {"q": "test"}
        assert result["action_risk_score"] == 0.5

@patch("agents.nodes.reasoning.httpx.Client")
@patch("agents.nodes.reasoning.asyncio.run")
def test_agent_node_network_error(mock_async_run, mock_client):
    mock_async_run.return_value = []
    mock_client.return_value.__enter__.return_value.post.side_effect = Exception("error")
    
    state = {"is_safe": True, "tenant_id": "t1", "input": "hello"}
    
    with pytest.raises(HTTPException) as exc:
        agent_node(state)
    assert exc.value.status_code == 502
