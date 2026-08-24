import uuid
from typing import Dict, Any, List, Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class EvidenceCreate(BaseModel):
    control_id:       str           = Field(..., description="Target control e.g. SOC2-CC-6.1")
    source_component: str           = Field(..., description="Component emitting the event")
    event_type:       str           = Field(..., description="e.g. guardrail_violation")
    severity:         str           = Field(..., description="info | low | medium | high | critical")
    payload:          Dict[str, Any]= Field(..., description="Arbitrary JSON context")

class EvidenceResponse(BaseModel):
    evidence_id:       uuid.UUID
    control_id:        str
    source_component:  str
    event_type:        str
    severity:          str
    payload:           Dict[str, Any]
    minio_object_path: Optional[str] = None
    evidence_hmac:     Optional[str] = None
    created_at:        Optional[datetime] = None

    class Config:
        orm_mode = True
        from_attributes = True

class ControlStatus(BaseModel):
    control_id:     str
    status:         str
    evidence_count: int

class ComplianceStatusResponse(BaseModel):
    tenant_id:                str
    overall_compliance_score: float
    controls:                 List[ControlStatus]

class PolicyEvalRequest(BaseModel):
    action:       str
    resource_kind:str
    resource_attr:Dict[str, Any] = {}
    context:      Dict[str, Any] = {}

class PolicyEvalResponse(BaseModel):
    decision:   Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"]
    risk_score: float
    reason:     str
    control_id: Optional[str] = None

class AGTAuditLog(BaseModel):
    run_id: str
    agent_id: str
    tool_name: str
    action_type: str
    verdict: str
    reason: str
    timestamp: str
    payload: Dict[str, Any]

class AIBOMAsset(BaseModel):
    asset_id:     str
    name:         str
    type:         str
    location:     str
    status:       str
    risk_level:   str
    risk_factors: List[str]

class AIBOMResponse(BaseModel):
    generated_at:            datetime
    total_discovered_assets: int
    high_risk_violations:    int
    assets:                  List[AIBOMAsset]

class TopologyNode(BaseModel):
    id:      str
    label:   str
    type:    str
    status:  str
    details: str

class TopologyLink(BaseModel):
    source: str
    target: str
    label:  str

class TopologyResponse(BaseModel):
    nodes: List[TopologyNode]
    links: List[TopologyLink]
