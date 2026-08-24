import pytest
from unittest.mock import patch, MagicMock
from services import _sign_evidence, verify_evidence_hmac, _deduct_score, _send_alert
from datetime import datetime, timedelta
from models import DBComplianceEvidence
import uuid
import hmac
import hashlib

def test_sign_evidence():
    signature = _sign_evidence("ev1", "t1", "c1", {"key": "val"})
    assert isinstance(signature, str)
    assert len(signature) > 0

def test_verify_evidence_hmac():
    ev_id = "ev1"
    tenant = "t1"
    control = "c1"
    payload = {"k": "v"}
    
    signature = _sign_evidence(ev_id, tenant, control, payload)
    
    mock_db_row = MagicMock(spec=DBComplianceEvidence)
    mock_db_row.evidence_id = ev_id
    mock_db_row.tenant_id = tenant
    mock_db_row.control_id = control
    mock_db_row.payload = payload
    mock_db_row.evidence_hmac = signature
    
    assert verify_evidence_hmac(mock_db_row) == True
    
    mock_db_row.evidence_hmac = "invalid"
    assert verify_evidence_hmac(mock_db_row) == False
    
    mock_db_row.evidence_hmac = None
    assert verify_evidence_hmac(mock_db_row) == False

@patch("services.CONTROLS_DB", {"c1": {}})
@patch("services.DATABASE_URL", "sqlite:///./test.db")
def test_deduct_score():
    mock_db = MagicMock()
    mock_evidence = MagicMock()
    mock_evidence.payload = {"adjustment": 10}
    mock_evidence.created_at = datetime.utcnow()
    mock_evidence.severity = "high"
    
    # query().filter().all()
    mock_db.query.return_value.filter.return_value.all.return_value = [mock_evidence]
    
    _deduct_score(mock_db, "t1", 5)
    
    assert mock_db.add.called
    added_obj = mock_db.add.call_args[0][0]
    assert added_obj.payload["adjustment"] == -5
    assert added_obj.payload["new_score"] == 5.0  # 0 base + 10 adj - 5 deduct

@patch("services.ALERT_WEBHOOK_URL", "http://test-webhook")
@patch("services.httpx.Client")
def test_send_alert(mock_client):
    mock_instance = mock_client.return_value.__enter__.return_value
    _send_alert("t1", "event", "high", {"foo": "bar"})
    
    assert mock_instance.post.called
    args, kwargs = mock_instance.post.call_args
    assert args[0] == "http://test-webhook"
    assert "t1" in kwargs["json"]["text"]
    assert "HIGH" in kwargs["json"]["text"]

@patch("services.ALERT_WEBHOOK_URL", None)
@patch("services.httpx.Client")
def test_send_alert_no_webhook(mock_client):
    _send_alert("t1", "event", "high", {"foo": "bar"})
    assert not mock_client.called