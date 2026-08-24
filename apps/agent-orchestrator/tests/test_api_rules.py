import pytest
from unittest.mock import MagicMock

def test_get_rules(client, mock_db_session):
    mock_db_session.execute.return_value.fetchall.return_value = [
        ("rule1", "pattern1", 1, "SOC2-CC-6.1"),
        ("rule2", "pattern2", 0, "GDPR-Art-32"),
    ]
    response = client.get("/api/v1/rules")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["rule_id"] == "rule1"
    assert data[0]["pattern"] == "pattern1"
    assert data[0]["is_active"] is True
    assert data[0]["control_id"] == "SOC2-CC-6.1"

def test_create_rule(client, mock_db_session):
    response = client.post("/api/v1/rules", json={"pattern": "new_pattern", "control_id": "TEST-1"})
    assert response.status_code == 201
    data = response.json()
    assert "rule_id" in data
    assert data["pattern"] == "new_pattern"
    assert data["control_id"] == "TEST-1"
    assert data["is_active"] is True
    mock_db_session.execute.assert_called_once()
    mock_db_session.commit.assert_called_once()

def test_delete_rule(client, mock_db_session):
    response = client.delete("/api/v1/rules/rule1")
    assert response.status_code == 200
    assert response.json() == {"status": "deleted", "rule_id": "rule1"}
    mock_db_session.execute.assert_called_once()
    mock_db_session.commit.assert_called_once()

def test_toggle_rule_not_found(client, mock_db_session):
    mock_db_session.execute.return_value.first.return_value = None
    response = client.put("/api/v1/rules/rule1/toggle")
    assert response.status_code == 404
    assert response.json() == {"detail": "Rule not found"}

def test_toggle_rule_success(client, mock_db_session):
    mock_db_session.execute.return_value.first.return_value = (1,)
    response = client.put("/api/v1/rules/rule1/toggle")
    assert response.status_code == 200
    assert response.json() == {"rule_id": "rule1", "is_active": False}
    mock_db_session.commit.assert_called_once()
