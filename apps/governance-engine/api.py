from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from typing import Dict, Any, Optional
import uuid, json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text

try:
    from fpdf import FPDF
except ImportError:
    pass

from config import CONTROLS_DB, DATABASE_URL, observe, langfuse_context, HAS_FPDF
from schemas import (
    ComplianceStatusResponse, PolicyEvalRequest, PolicyEvalResponse,
    AIBOMResponse, TopologyResponse, AGTAuditLog, ControlStatus, AIBOMAsset, TopologyNode, TopologyLink
)
from models import DBComplianceEvidence
from auth import get_principal, get_db, is_authorized
from services import _sign_evidence, _deduct_score, _send_alert

router = APIRouter()

@router.get("/")
def read_root():
    return {"service": "governance-engine", "version": "2.0.0", "status": "running"}

@router.get("/health")
def health_check():
    return {"status": "ok"}

@router.get("/api/v1/tenants")
def get_tenants(
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session = Depends(get_db),
):
    allowed_roles = {"tenant-admin", "platform-admin", "compliance-auditor"}
    if not any(r in allowed_roles for r in principal.get("roles", [])):
        raise HTTPException(status_code=403, detail="Unauthorized: Insufficient permissions to access tenants.")

    rows = db.query(DBComplianceEvidence.tenant_id).distinct().order_by(DBComplianceEvidence.tenant_id).all()
    tenants = [r[0] for r in rows if r[0]]
    if not tenants and principal.get("tenant_id"):
        tenants = [principal["tenant_id"]]
    return {"tenants": tenants}

@router.get("/api/v1/evidence")
def get_evidence(
    limit: int = 50,
    offset: int = 0,
    control_id: Optional[str] = None,
    severity: Optional[str] = None,
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session = Depends(get_db),
):
    allowed_roles = {"tenant-admin", "compliance-auditor"}
    if not any(r in allowed_roles for r in principal.get("roles", [])):
        raise HTTPException(status_code=403, detail="Unauthorized: Insufficient permissions to view evidence.")

    tenant_id = principal["tenant_id"]
    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

    query = db.query(DBComplianceEvidence).filter(DBComplianceEvidence.tenant_id == tenant_id)
    if control_id:
        query = query.filter(DBComplianceEvidence.control_id == control_id)
    if severity:
        query = query.filter(DBComplianceEvidence.severity == severity)

    total = query.count()
    rows = query.order_by(DBComplianceEvidence.created_at.desc()).offset(offset).limit(limit).all()

    items = [
        {
            "evidence_id": str(r.evidence_id),
            "control_id": r.control_id,
            "source_component": r.source_component,
            "event_type": r.event_type,
            "severity": r.severity,
            "payload": r.payload,
            "minio_object_path": r.minio_object_path,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"items": items, "total": total}

@router.post("/api/v1/agt/audit_logs", status_code=201)
def ingest_agt_audit_log(
    audit_log: AGTAuditLog,
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session = Depends(get_db),
):
    tenant_id = principal.get("tenant_id", "default")
    
    evidence_id = str(uuid.uuid4())
    timestamp   = datetime.utcnow()
    minio_path  = f"tenants/{tenant_id}/evidence/agt_audit/{timestamp.strftime('%Y-%m-%d')}/{evidence_id}.json"

    control_id = "AGT-TOOL-GOV-01"
    
    evidence_hmac = _sign_evidence(evidence_id, tenant_id, control_id, audit_log.model_dump())

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

    db_evidence = DBComplianceEvidence(
        evidence_id=evidence_id,
        tenant_id=tenant_id,
        control_id=control_id,
        source_component="agent-governance-toolkit",
        event_type="audit_log",
        severity="high" if audit_log.verdict == "deny" else "info",
        payload=audit_log.model_dump(),
        minio_object_path=minio_path,
        evidence_hmac=evidence_hmac,
        created_at=timestamp
    )
    db.add(db_evidence)
    
    if audit_log.verdict == "deny":
        _deduct_score(db, tenant_id, 2)
        _send_alert(tenant_id, "agt_policy_violation", "high", audit_log.model_dump())

    db.commit()
    return {"status": "ingested", "evidence_id": evidence_id}

@router.get("/api/v1/compliance/status", response_model=ComplianceStatusResponse)
@observe(name="get_compliance_status")
def get_compliance_status(
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session = Depends(get_db),
):
    tenant_id = principal["tenant_id"]
    if not is_authorized(principal, "compliance_evidence", "status", "read", {"tenant_id": tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized: cannot read compliance status")

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

    SEVERITY_WEIGHTS = {"info": 0, "low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}
    FRESHNESS_DAYS   = 7
    freshness_cutoff = datetime.utcnow()

    controls_summary = []
    score_sum        = 0.0

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

        evidence_count = len(evidence_rows)
        fresh_rows = [
            r for r in evidence_rows
            if r.created_at and (freshness_cutoff - r.created_at).days <= FRESHNESS_DAYS
        ]

        if not fresh_rows:
            status             = "non_compliant" if evidence_count == 0 else "stale"
            score_contribution = 0.0
        else:
            avg_weight = sum(SEVERITY_WEIGHTS.get(r.severity, 0) for r in fresh_rows) / len(fresh_rows)
            if avg_weight <= 0.1:
                status, score_contribution = "compliant", 1.0
            elif avg_weight <= 0.5:
                status, score_contribution = "partial", 0.5
            else:
                status, score_contribution = "non_compliant", 0.0

        controls_summary.append(ControlStatus(control_id=control_id, status=status, evidence_count=evidence_count))
        score_sum += score_contribution

    total = len(CONTROLS_DB)
    score = (score_sum / total) * 100.0 if total > 0 else 100.0
    
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
            score += r.payload["adjustment"]
            
    score = max(0.0, score)
    return ComplianceStatusResponse(tenant_id=tenant_id, overall_compliance_score=round(score, 2), controls=controls_summary)

@router.post("/api/v1/policies/evaluate", response_model=PolicyEvalResponse)
@observe(name="evaluate_policy")
def evaluate_policy(
    req: PolicyEvalRequest,
    principal: Dict[str, Any] = Depends(get_principal),
):
    action        = req.action
    resource_kind = req.resource_kind
    context       = req.context

    langfuse_context.update_current_observation(
        input={"action": action, "resource_kind": resource_kind, "context": context},
        metadata={"node": "policy_evaluate"},
    )

    RISK_TABLE = {
        "terminal_executor": (0.95, "REQUIRE_APPROVAL", "EU-AI-Act-Art-9"),
        "database_mutator":  (0.80, "REQUIRE_APPROVAL", "SOC2-CC-6.1"),
        "file_writer":       (0.75, "REQUIRE_APPROVAL", "GDPR-Art-32"),
        "file_reader":       (0.10, "ALLOW",            None),
        "knowledge_search":  (0.05, "ALLOW",            None),
        "web_search":        (0.30, "ALLOW",            None),
    }

    tool_name = context.get("tool") or action

    if tool_name in RISK_TABLE:
        risk_score, decision, control_id = RISK_TABLE[tool_name]
        reason = (
            f"Tool '{tool_name}' has risk score {risk_score:.2f} — "
            f"{'HITL approval required' if decision == 'REQUIRE_APPROVAL' else 'auto-approved'}."
        )
        langfuse_context.update_current_observation(
            output={"decision": decision, "risk_score": risk_score},
        )
        return PolicyEvalResponse(
            decision=decision, risk_score=risk_score,
            reason=reason, control_id=control_id,
        )

    return PolicyEvalResponse(
        decision="ALLOW", risk_score=0.10,
        reason=f"Action '{action}' on '{resource_kind}' has no specific policy — defaulting to ALLOW.",
    )

@router.get("/api/v1/compliance/ai-bom", response_model=AIBOMResponse)
def get_ai_bom(principal: Dict[str, Any] = Depends(get_principal), db: Session = Depends(get_db)):
    tenant_id = principal["tenant_id"]
    if not is_authorized(principal, "compliance_evidence", "status", "read", {"tenant_id": tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

    if DATABASE_URL.startswith("sqlite"):
        evidences = db.query(DBComplianceEvidence).filter(DBComplianceEvidence.tenant_id == tenant_id).all()
    else:
        evidences = db.query(DBComplianceEvidence).all()

    guardrail_violations = [e for e in evidences if e.event_type == "guardrail_violation"]
    agt_violations       = [e for e in evidences if e.event_type == "agent_action_intercepted"]
    discovered_assets_ev = [e for e in evidences if e.event_type == "asset_discovered"]

    discovered_assets: Dict[str, AIBOMAsset] = {}
    for ev in discovered_assets_ev:
        p = ev.payload
        ast_id = p.get("asset_id")
        if ast_id and ast_id not in discovered_assets:
            discovered_assets[ast_id] = AIBOMAsset(
                asset_id=ast_id, name=p.get("name", "Unknown"), type=p.get("type", "llm_model_runtime"),
                location=p.get("location", ""), status=p.get("status", "active"),
                risk_level="info", risk_factors=[],
            )

    assets = []
    high_risk_count = 0

    endpoint_risk    = "medium" if guardrail_violations else "info"
    endpoint_factors = ["policy_violation_in_history"] if guardrail_violations else []
    assets.append(AIBOMAsset(
        asset_id="ast_endpoint_01", name=f"Developer Workstation ({principal['id']})",
        type="developer_endpoint", location=f"LAN Client (Tenant: {tenant_id})",
        status="active", risk_level=endpoint_risk, risk_factors=endpoint_factors,
    ))

    orch_risk    = "high" if agt_violations else "info"
    orch_factors = ["unapproved_tool_execution_intercepted"] if agt_violations else []
    if agt_violations:
        high_risk_count += 1
    assets.append(AIBOMAsset(
        asset_id="ast_orchestrator_01", name="Agent Orchestrator (LangGraph Core)",
        type="autonomous_agent", location="Kubernetes Pod Namespace",
        status="active", risk_level=orch_risk, risk_factors=orch_factors,
    ))
    assets.append(AIBOMAsset(
        asset_id="ast_gateway_01", name="LiteLLM API Gateway Router",
        type="ai_gateway_proxy", location="Kubernetes Service (Port 4000)",
        status="active", risk_level="info", risk_factors=[],
    ))
    assets.append(AIBOMAsset(
        asset_id="ast_llm_01", name="External Ollama Model Runner",
        type="llm_model_runtime", location="LAN Server (Port 11434)",
        status="active", risk_level="info", risk_factors=[],
    ))
    assets.append(AIBOMAsset(
        asset_id="ast_qdrant_01", name="Qdrant Vector Database",
        type="vector_datastore", location="Kubernetes StatefulSet (Port 6333)",
        status="active", risk_level="info", risk_factors=[],
    ))
    assets.extend(discovered_assets.values())

    return AIBOMResponse(
        generated_at=datetime.utcnow(),
        total_discovered_assets=len(assets),
        high_risk_violations=high_risk_count,
        assets=assets,
    )

@router.get("/api/v1/compliance/topology", response_model=TopologyResponse)
def get_topology(principal: Dict[str, Any] = Depends(get_principal), db: Session = Depends(get_db)):
    tenant_id = principal["tenant_id"]
    if not is_authorized(principal, "compliance_evidence", "status", "read", {"tenant_id": tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

    if DATABASE_URL.startswith("sqlite"):
        evidences = db.query(DBComplianceEvidence).filter(DBComplianceEvidence.tenant_id == tenant_id).all()
    else:
        evidences = db.query(DBComplianceEvidence).all()

    has_guardrail = any(e.event_type == "guardrail_violation" for e in evidences)
    has_agt       = any(e.event_type == "agent_action_intercepted" for e in evidences)

    nodes = [TopologyNode(id="user",         label="User Browser",           type="endpoint", status="danger" if has_guardrail else "safe",  details=f"LAN User (Role: {principal['roles'][0]})"),
        TopologyNode(id="dashboard",    label="Dashboard Console",       type="app",      status="safe",                                 details="React UI (NodePort 30082)"),
        TopologyNode(id="orchestrator", label="Agent Orchestrator",      type="app",      status="danger" if has_agt else "safe",        details="LangGraph Pod (Port 8001)"),
        TopologyNode(id="governance",   label="Governance Engine",       type="app",      status="safe",                                 details="FastAPI Audit Pod (Port 8000)"),
        TopologyNode(id="postgres",     label="PostgreSQL Database",     type="database", status="safe",                                 details="Audits & Checkpoints (Port 5432)"),
        TopologyNode(id="qdrant",       label="Qdrant Vector DB",        type="database", status="safe",                                 details="Knowledge Vectors (Port 6333)"),
        TopologyNode(id="litellm",      label="LiteLLM Gateway",         type="runtime",  status="safe",                                 details="Model Router (Port 4000)"),
        TopologyNode(id="ollama",       label="External Ollama Node",    type="runtime",  status="safe",                                 details="LAN Model Runner (Port 11434)"),
    ]
    links = [TopologyLink(source="user",         target="dashboard",    label="HTTPS"),
        TopologyLink(source="dashboard",    target="orchestrator", label="REST API"),
        TopologyLink(source="orchestrator", target="postgres",     label="SQL"),
        TopologyLink(source="orchestrator", target="governance",   label="GRC webhook"),
        TopologyLink(source="governance",   target="postgres",     label="SQL"),
        TopologyLink(source="orchestrator", target="qdrant",       label="gRPC"),
        TopologyLink(source="orchestrator", target="litellm",      label="REST API"),
        TopologyLink(source="litellm",      target="ollama",       label="External bridge"),
    ]
    return TopologyResponse(nodes=nodes, links=links)

@router.get("/api/v1/compliance/report/pdf")
@observe(name="generate_pdf_report")
def generate_pdf_report(principal: Dict[str, Any] = Depends(get_principal), db: Session = Depends(get_db)):
    if not HAS_FPDF:
        raise HTTPException(status_code=501, detail="fpdf2 is not installed on this server.")

    tenant_id = principal["tenant_id"]
    if not is_authorized(principal, "compliance_evidence", "report", "read", {"tenant_id": tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
        evidences = db.query(DBComplianceEvidence).all()
    else:
        evidences = db.query(DBComplianceEvidence).filter(DBComplianceEvidence.tenant_id == tenant_id).all()

    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", size=16)
        pdf.cell(200, 10, txt=f"Compliance Audit Report", new_x="LMARGIN", new_y="NEXT", align='C')
        pdf.set_font("helvetica", size=14)
        pdf.cell(200, 10, txt=f"Tenant: {tenant_id}", new_x="LMARGIN", new_y="NEXT", align='C')
        pdf.ln(10)

        pdf.set_font("helvetica", size=12)
        pdf.cell(200, 10, txt=f"Generated at: {datetime.utcnow().isoformat()}Z", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(200, 10, txt=f"Total Auditable Events: {len(evidences)}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(10)

        for ev in evidences:
            pdf.set_font("helvetica", "B", 10)
            pdf.cell(0, 8, txt=f"[{ev.severity.upper()}] {ev.control_id} - {ev.event_type}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 10)
            pdf.cell(0, 8, txt=f"Date: {ev.created_at} | ID: {ev.evidence_id[:8]}", new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(0, 8, txt=f"Details: {json.dumps(ev.payload)}")
            pdf.ln(5)

        pdf_bytes = pdf.output()
        return Response(content=bytes(pdf_bytes), media_type="application/pdf", headers={
            "Content-Disposition": f"attachment; filename=compliance_report_{tenant_id}.pdf"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")
