import hmac
import hashlib
import json
import uuid
from datetime import datetime
import httpx
from sqlalchemy.orm import Session

from models import DBComplianceEvidence
from config import AUDIT_HMAC_SECRET, CONTROLS_DB, DATABASE_URL, ALERT_WEBHOOK_URL

def _sign_evidence(evidence_id: str, tenant_id: str, control_id: str, payload: dict) -> str:
    data = json.dumps(
        {"evidence_id": evidence_id, "tenant_id": tenant_id,
         "control_id": control_id, "payload": payload},
        sort_keys=True,
    ).encode()
    return hmac.new(AUDIT_HMAC_SECRET, data, hashlib.sha256).hexdigest()

def verify_evidence_hmac(db_row: DBComplianceEvidence) -> bool:
    if not db_row.evidence_hmac:
        return False
    expected = _sign_evidence(
        db_row.evidence_id, db_row.tenant_id, db_row.control_id, db_row.payload
    )
    return hmac.compare_digest(expected, db_row.evidence_hmac)

def _deduct_score(db: Session, tenant_id: str, points: int) -> None:
    SEVERITY_WEIGHTS = {"info": 0, "low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}
    FRESHNESS_DAYS = 7
    freshness_cutoff = datetime.utcnow()
    score_sum = 0.0
    for control_id in CONTROLS_DB:
        if DATABASE_URL.startswith("sqlite"):
            evidence_rows = db.query(DBComplianceEvidence).filter(
                DBComplianceEvidence.tenant_id == tenant_id,
                DBComplianceEvidence.control_id == control_id,
            ).all()
        else:
            evidence_rows = db.query(DBComplianceEvidence).filter(
                DBComplianceEvidence.control_id == control_id,
            ).all()

        fresh_rows = [
            r for r in evidence_rows
            if r.created_at and (freshness_cutoff - r.created_at).days <= FRESHNESS_DAYS
        ]

        if fresh_rows:
            avg_weight = sum(SEVERITY_WEIGHTS.get(r.severity, 0) for r in fresh_rows) / len(fresh_rows)
            if avg_weight <= 0.1:
                score_contribution = 1.0
            elif avg_weight <= 0.5:
                score_contribution = 0.5
            else:
                score_contribution = 0.0
        else:
            score_contribution = 0.0
        score_sum += score_contribution

    total = len(CONTROLS_DB)
    current_score = (score_sum / total) * 100.0 if total > 0 else 100.0

    if DATABASE_URL.startswith("sqlite"):
        adj_rows = db.query(DBComplianceEvidence).filter(
            DBComplianceEvidence.tenant_id == tenant_id,
            DBComplianceEvidence.control_id == "SCORE_ADJUSTMENT"
        ).all()
    else:
        adj_rows = db.query(DBComplianceEvidence).filter(
            DBComplianceEvidence.control_id == "SCORE_ADJUSTMENT"
        ).all()
        
    for r in adj_rows:
        if r.payload and "adjustment" in r.payload:
            current_score += r.payload["adjustment"]

    new_score = max(0.0, current_score - points)
    
    evidence_id = str(uuid.uuid4())
    payload = {"adjustment": -points, "computed_score": current_score, "new_score": new_score}
    hmac_val = _sign_evidence(evidence_id, tenant_id, "SCORE_ADJUSTMENT", payload)
    
    db_evidence = DBComplianceEvidence(
        evidence_id=evidence_id,
        tenant_id=tenant_id,
        control_id="SCORE_ADJUSTMENT",
        source_component="governance-engine",
        event_type="score_adjustment",
        severity="high",
        payload=payload,
        evidence_hmac=hmac_val,
        created_at=datetime.utcnow()
    )
    db.add(db_evidence)

def _send_alert(tenant_id: str, event_type: str, severity: str, payload: dict) -> None:
    if not ALERT_WEBHOOK_URL:
        return
    try:
        msg = {
            "text": (
                f":rotating_light: *Governance Alert* [{severity.upper()}]\n"
                f"*Tenant*: `{tenant_id}` | *Event*: `{event_type}`\n"
                f"*Details*: {json.dumps(payload, indent=2)[:400]}"
            )
        }
        with httpx.Client(timeout=3.0) as client:
            client.post(ALERT_WEBHOOK_URL, json=msg)
    except Exception as exc:
        print(f"[Alert] Webhook POST failed: {exc}")
