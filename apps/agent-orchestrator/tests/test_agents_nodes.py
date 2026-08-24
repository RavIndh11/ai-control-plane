import pytest
from unittest.mock import patch, MagicMock, ANY
from langchain_core.runnables import RunnableConfig
from agents.nodes.execute import execute_node
import concurrent.futures

def test_execute_node_no_pending_action():
    state = {"pending_action": None, "output": ""}
    result = execute_node(state)
    assert result == state

@patch("agents.nodes.execute._mcp_execute_pool.submit")
def test_execute_node_success(mock_submit):
    mock_future = MagicMock()
    mock_future.result.return_value = "Tool execution result"
    mock_submit.return_value = mock_future
    
    state = {"pending_action": {"tool": "test_tool", "arguments": {}}, "output": ""}
    result = execute_node(state)
    assert result["output"] == "Tool execution result"
    assert result["pending_action"] is None
    mock_submit.assert_called_once()

@patch("agents.nodes.governance_shield.AgentEvaluationPolicy")
def test_governance_shield_no_pending_action(mock_policy):
    from agents.nodes.governance_shield import governance_shield_node
    state = {"pending_action": None, "steps": []}
    result = governance_shield_node(state, {})
    assert result == state
    mock_policy.assert_not_called()

@patch("agents.nodes.governance_shield.AgentEvaluationPolicy")
def test_governance_shield_allowed(mock_policy_class):
    from agents.nodes.governance_shield import governance_shield_node
    mock_policy = MagicMock()
    mock_eval = MagicMock()
    mock_eval.is_allowed = True
    mock_eval.requires_hitl = False
    mock_eval.risk_score = 0.1
    mock_policy.evaluate.return_value = mock_eval
    mock_policy_class.return_value = mock_policy
    
    state = {"pending_action": {"tool": "test", "tool_input": {}}, "steps": []}
    config = {"configurable": {"principal": {"id": "1", "roles": ["admin"]}}}
    
    result = governance_shield_node(state, config)
    assert "governance_approved" in result["steps"]
    assert result["action_risk_score"] == 0.1
    
@patch("agents.nodes.governance_shield.AgentEvaluationPolicy")
def test_governance_shield_requires_hitl(mock_policy_class):
    from agents.nodes.governance_shield import governance_shield_node
    mock_policy = MagicMock()
    mock_eval = MagicMock()
    mock_eval.is_allowed = True
    mock_eval.requires_hitl = True
    mock_eval.risk_score = 0.8
    mock_eval.required_roles = ["superadmin"]
    mock_policy.evaluate.return_value = mock_eval
    mock_policy_class.return_value = mock_policy
    
    state = {"pending_action": {"tool": "test"}, "steps": []}
    config = {}
    
    result = governance_shield_node(state, config)
    assert result["requires_hitl"] is True
    assert "governance_shield_interrupt" in result["steps"]
    assert result["approval_chain"] == ["superadmin"]
    assert result["action_risk_score"] == 0.8

@patch("agents.nodes.governance_shield.AgentEvaluationPolicy")
def test_governance_shield_blocked(mock_policy_class):
    from agents.nodes.governance_shield import governance_shield_node
    mock_policy = MagicMock()
    mock_eval = MagicMock()
    mock_eval.is_allowed = False
    mock_eval.reason = "test reason"
    mock_policy.evaluate.return_value = mock_eval
    mock_policy_class.return_value = mock_policy
    
    state = {"pending_action": {"tool": "test"}, "steps": []}
    
    result = governance_shield_node(state, {})
    assert result["pending_action"] is None
    assert "governance_blocked" in result["steps"]
    assert "AGT Blocked" in result["output"]["error"]

@patch("agents.nodes.governance_shield.AgentEvaluationPolicy")
def test_governance_shield_exception(mock_policy_class):
    from agents.nodes.governance_shield import governance_shield_node
    mock_policy = MagicMock()
    mock_policy.evaluate.side_effect = Exception("test error")
    mock_policy_class.return_value = mock_policy
    
    state = {"pending_action": {"tool": "test"}, "steps": []}
    
    result = governance_shield_node(state, {})
    assert result["pending_action"] is None
    assert "governance_blocked" in result["steps"]
    assert "AGT Evaluation Failure" in result["output"]["error"]
