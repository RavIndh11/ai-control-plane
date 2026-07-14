from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import uuid
from datetime import datetime

app = FastAPI(
    title="Governance Engine API",
    description="Control-mapping and evidence service for Enterprise AI Control Plane",
    version="1.0.0"
)

# --- In-Memory Database (for mock demo fallback) ---
EVIDENCE_DB: List[Dict[str, Any]] = []

CONTROLS_DB = {
    "SOC2-CC-6.1": {"name": "Access Control Security", "description": "Ensure authorized access to assets and models."},
    "GDPR-Art-32": {"name": "Security of Processing", "description": "Implement appropriate technical controls."},
    "EU-AI-Act-Art-9": {"name": "Risk Management System", "description": "Establish compliance frameworks for AI workflows."}
}

# --- Pydantic Schemas ---
class EvidenceCreate(BaseModel):
    control_id: str = Field(..., description="Target control identifier (e.g., SOC2-CC-6.1)")
    source_component: str = Field(..., description="The app component sending evidence")
    event_type: str = Field(..., description="Type of event (e.g., guardrail_violation)")
    severity: str = Field(..., description="Severity level: info, low, medium, high, critical")
    payload: Dict[str, Any] = Field(..., description="Detailed JSON context")

class EvidenceResponse(BaseModel):
    evidence_id: uuid.UUID
    control_id: str
    source_component: str
    event_type: str
    severity: str
    payload: Dict[str, Any]
    minio_object_path: str
    created_at: datetime

class ControlStatus(BaseModel):
    control_id: str
    status: str
    evidence_count: int

class ComplianceStatusResponse(BaseModel):
    tenant_id: str
    overall_compliance_score: float
    controls: List[ControlStatus]

# --- Dependency to simulate tenant isolation ---
def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is missing")
    return x_tenant_id

# --- Endpoint Handlers ---

@app.get("/")
def read_root():
    return {"message": "Governance Engine is running"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/v1/evidence", response_model=EvidenceResponse, status_code=201)
def create_evidence(evidence: EvidenceCreate, tenant_id: str = Depends(get_tenant_id)):
    evidence_id = uuid.uuid4()
    timestamp = datetime.utcnow()
    
    # Simulate writing raw log to MinIO object store path
    minio_path = f"tenants/{tenant_id}/evidence/{timestamp.strftime('%Y-%m-%d')}/{evidence_id}.json"
    
    evidence_entry = {
        "evidence_id": evidence_id,
        "tenant_id": tenant_id,
        "control_id": evidence.control_id,
        "source_component": evidence.source_component,
        "event_type": evidence.event_type,
        "severity": evidence.severity,
        "payload": evidence.payload,
        "minio_object_path": minio_path,
        "created_at": timestamp
    }
    
    EVIDENCE_DB.append(evidence_entry)
    
    # Log the compliance event to console for transparency
    print(f"[{timestamp.isoformat()}] GRC Audit Event saved for Tenant '{tenant_id}': Control={evidence.control_id}, Severity={evidence.severity}")
    
    return evidence_entry

@app.get("/api/v1/compliance/status", response_model=ComplianceStatusResponse)
def get_compliance_status(tenant_id: str = Depends(get_tenant_id)):
    # Filter evidence for this tenant
    tenant_evidence = [e for e in EVIDENCE_DB if e["tenant_id"] == tenant_id]
    
    controls_summary = []
    compliant_count = 0
    
    for control_id in CONTROLS_DB.keys():
        evidence_count = len([e for e in tenant_evidence if e["control_id"] == control_id])
        
        # Simple policy: if we have evidence, control is "compliant", else "action_required"
        if evidence_count > 0:
            status = "compliant"
            compliant_count += 1
        else:
            status = "action_required"
            
        controls_summary.append(
            ControlStatus(
                control_id=control_id,
                status=status,
                evidence_count=evidence_count
            )
        )
    
    # Calculate simple score
    total_controls = len(CONTROLS_DB)
    score = (compliant_count / total_controls) * 100.0 if total_controls > 0 else 100.0
    
    return ComplianceStatusResponse(
        tenant_id=tenant_id,
        overall_compliance_score=round(score, 2),
        controls=controls_summary
    )
