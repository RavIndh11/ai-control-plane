import pytest
from agents.state import empty_state

def test_empty_state():
    state = empty_state(
        tenant_id="tenant1",
        user_id="user1",
        thread_id="thread1",
        input_text="hello world",
        agent_type="custom-agent"
    )
    
    assert state["tenant_id"] == "tenant1"
    assert state["user_id"] == "user1"
    assert state["thread_id"] == "thread1"
    assert state["input"] == "hello world"
    assert state["agent_type"] == "custom-agent"
    assert state["output"] == ""
    assert state["steps"] == []
    assert state["is_safe"] is True
    assert state["pending_action"] is None
    assert state["action_approved"] is None
    assert state["action_risk_score"] is None
    assert state["approval_chain"] is None
    assert state["approval_timeout_at"] is None
    assert state["break_glass_used"] is None
    assert state["audit_hmac"] is None

def test_empty_state_default_agent():
    state = empty_state("t", "u", "th", "input")
    assert state["agent_type"] == "compliance-agent"
