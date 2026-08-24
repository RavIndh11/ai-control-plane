import pytest
from main import read_root, health

def test_read_root():
    response = read_root()
    assert response["service"] == "agent-orchestrator"
    assert response["status"] == "running"
    assert "version" in response

def test_health():
    response = health()
    assert response["status"] == "ok"
