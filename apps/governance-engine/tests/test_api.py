import pytest
from unittest.mock import MagicMock, patch
from schemas import EvidenceCreate
from models import DBComplianceEvidence
import json
import uuid

def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "governance-engine"

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_get_tenants(client, mock_db_session):
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = ["tenant-1", "tenant-2"]
    response = client.get("/api/v1/tenants")
    assert response.status_code == 200
    assert "tenants" in response.json()

def test_get_evidence(client, mock_db_session):
    mock_evidence = MagicMock()
    mock_evidence.evidence_id = str(uuid.uuid4())
    mock_evidence.control_id = "SOC2-CC-6.1"
    mock_evidence.source_component = "test-comp"
    mock_evidence.event_type = "test-event"
    mock_evidence.severity = "low"
    mock_evidence.payload = {}
    mock_evidence.minio_object_path = None
    mock_evidence.evidence_hmac = "dummy-hmac"
    
    mock_query = mock_db_session.query.return_value.filter.return_value.filter.return_value
    mock_query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [mock_evidence]
    mock_query.count.return_value = 1
    
    
    response = client.get("/api/v1/evidence?control_id=SOC2-CC-6.1")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1

@patch("api._sign_evidence", return_value="dummy-hmac")
def test_ingest_agt_audit_log(mock_sign, client, mock_db_session):
    payload = {
        "run_id": "r1",
        "agent_id": "a1",
        "tool_name": "t1",
        "action_type": "action",
        "verdict": "ALLOW",
        "reason": "ok",
        "timestamp": "2023-01-01T00:00:00Z",
        "payload": {}
    }
    response = client.post("/api/v1/agt/audit_logs", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "ingested"
def test_get_compliance_status(client, mock_db_session):
    response = client.get("/api/v1/compliance/status")
    assert response.status_code == 200
    assert "overall_compliance_score" in response.json()

@patch("api.langfuse_context")
def test_evaluate_policy(mock_langfuse, client):
    payload = {
        "action": "terminal_executor",
        "resource_kind": "system",
        "resource_attr": {},
        "context": {}
    }
    response = client.post("/api/v1/policies/evaluate", json=payload)
    assert response.status_code == 200
    assert response.json()["decision"] == "REQUIRE_APPROVAL"
    
    payload_allow = {
        "action": "unknown_action",
        "resource_kind": "model",
        "resource_attr": {},
        "context": {}
    }
    response_allow = client.post("/api/v1/policies/evaluate", json=payload_allow)
    assert response_allow.status_code == 200
    assert response_allow.json()["decision"] == "ALLOW"

def test_get_ai_bom(client):
    response = client.get("/api/v1/compliance/ai-bom")
    assert response.status_code == 200
    assert "assets" in response.json()

def test_get_topology(client):
    response = client.get("/api/v1/compliance/topology")
    assert response.status_code == 200
    assert "nodes" in response.json()

@patch("api.HAS_FPDF", False)
def test_generate_pdf_report_no_fpdf(client):
    response = client.get("/api/v1/compliance/report/pdf")
    assert response.status_code == 501

@patch("api.HAS_FPDF", True)
@patch("api.FPDF")
def test_generate_pdf_report_success(mock_fpdf, client):
    mock_pdf_instance = mock_fpdf.return_value
    mock_pdf_instance.output.return_value = b"dummy pdf content"
    response = client.get("/api/v1/compliance/report/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
