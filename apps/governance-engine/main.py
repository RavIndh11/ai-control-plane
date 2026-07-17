from fastapi import FastAPI, HTTPException, Header, Depends, Request, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import uuid
import os
import httpx
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, String, DateTime, JSON, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# --- JWT Auth ---
try:
    from jose import jwt, JWTError
    HAS_JOSE = True
except ImportError:
    HAS_JOSE = False

# --- OpenTelemetry ---
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    _provider = TracerProvider()
    _otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if _otlp_endpoint:
        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint)))
    trace.set_tracer_provider(_provider)
    tracer = trace.get_tracer("governance-engine")
    HAS_OTEL = True
except Exception:
    HAS_OTEL = False
    tracer = None

# --- Database Configurations ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./governance.db")
CERBOS_URL = os.getenv("CERBOS_URL", "http://localhost:3592")

# --- Keycloak JWT Config ---
KEYCLOAK_JWKS_URL = os.getenv("KEYCLOAK_JWKS_URL", "")
KEYCLOAK_AUDIENCE = os.getenv("KEYCLOAK_AUDIENCE", "ai-control-plane")
KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER", "")

# --- MinIO Config ---
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")  # e.g. http://minio:9000
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "manifold-evidence")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Database Models ---
class DBComplianceEvidence(Base):
    __tablename__ = "compliance_evidence"

    evidence_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(64), index=True, nullable=False)
    control_id = Column(String(100), index=True, nullable=False)
    source_component = Column(String(100), nullable=False)
    event_type = Column(String(100), nullable=False)
    severity = Column(String(20), index=True, nullable=False)
    payload = Column(JSON, nullable=False)
    minio_object_path = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Auto-create tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Governance Engine API",
    description="Control-mapping and evidence service for Enterprise AI Control Plane",
    version="1.0.0"
)

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

    class Config:
        orm_mode = True
        from_attributes = True

class ControlStatus(BaseModel):
    control_id: str
    status: str
    evidence_count: int

class ComplianceStatusResponse(BaseModel):
    tenant_id: str
    overall_compliance_score: float
    controls: List[ControlStatus]

# --- JWT JWKS Cache (shared with orchestrator pattern) ---
_gov_jwks_cache: Optional[Dict] = None
_gov_jwks_fetched_at: Optional[datetime] = None
JWKS_CACHE_TTL_SECONDS = 300

def _get_jwks() -> Optional[Dict]:
    global _gov_jwks_cache, _gov_jwks_fetched_at
    if not KEYCLOAK_JWKS_URL:
        return None
    now = datetime.utcnow()
    if _gov_jwks_cache and _gov_jwks_fetched_at and (now - _gov_jwks_fetched_at).total_seconds() < JWKS_CACHE_TTL_SECONDS:
        return _gov_jwks_cache
    try:
        with httpx.Client() as client:
            res = client.get(KEYCLOAK_JWKS_URL, timeout=3.0)
            if res.status_code == 200:
                _gov_jwks_cache = res.json()
                _gov_jwks_fetched_at = now
                return _gov_jwks_cache
    except Exception as e:
        print(f"[Auth] Failed to fetch JWKS: {e}")
    return None

# --- Identity / Principal Dependency ---
# Mode 1: Bearer JWT (Keycloak) | Mode 2: X-Tenant-ID header (dev fallback)
def get_principal(
    request: Request,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
) -> Dict[str, Any]:
    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Bearer ") and HAS_JOSE and KEYCLOAK_JWKS_URL:
        token = auth_header[len("Bearer "):].strip()
        jwks = _get_jwks()
        if jwks:
            try:
                unverified_header = jwt.get_unverified_header(token)
                matching_key = next(
                    (k for k in jwks.get("keys", []) if k.get("kid") == unverified_header.get("kid")),
                    None
                )
                if not matching_key:
                    raise HTTPException(status_code=401, detail="JWT signing key not found in JWKS")
                claims = jwt.decode(
                    token, matching_key, algorithms=["RS256"],
                    audience=KEYCLOAK_AUDIENCE,
                    issuer=KEYCLOAK_ISSUER or None,
                    options={"verify_iss": bool(KEYCLOAK_ISSUER)}
                )
                realm_roles = claims.get("realm_access", {}).get("roles", [])
                tenant_claim = claims.get("tenant_id") or claims.get("organization") or ""
                return {"id": claims.get("sub", ""), "email": claims.get("email", ""),
                        "roles": realm_roles, "tenant_id": tenant_claim, "auth_method": "jwt"}
            except JWTError as e:
                raise HTTPException(status_code=401, detail=f"Invalid JWT token: {e}")
        else:
            raise HTTPException(status_code=503, detail="Auth service unavailable")

    if not x_tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Provide a Bearer JWT or X-Tenant-ID header."
        )
    return {
        "id": x_user_id or "user_default",
        "email": "",
        "roles": [x_user_role or "tenant-user"],
        "tenant_id": x_tenant_id,
        "auth_method": "header"
    }

# --- Database Session Dependency ---
def get_db(principal: Dict[str, Any] = Depends(get_principal)):
    db = SessionLocal()
    tenant_id = principal.get("tenant_id", "default")
    if not DATABASE_URL.startswith("sqlite") and tenant_id:
        schema_name = f"tenant_{tenant_id.replace('-', '_')}"
        try:
            db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name};"))
            db.execute(text(f"SET search_path TO {schema_name}, public;"))
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS compliance_evidence (
                    evidence_id VARCHAR(36) PRIMARY KEY,
                    tenant_id VARCHAR(64) NOT NULL,
                    control_id VARCHAR(100) NOT NULL,
                    source_component VARCHAR(100) NOT NULL,
                    event_type VARCHAR(100) NOT NULL,
                    severity VARCHAR(20) NOT NULL,
                    payload JSON NOT NULL,
                    minio_object_path VARCHAR(512),
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('utc'::text, now())
                );
            """))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[Database] Error setting up schema/tables: {e}")
    try:
        yield db
    finally:
        db.close()

# --- Cerbos Authz Verification ---
def is_authorized(principal: Dict[str, Any], resource_kind: str, resource_id: str, action: str, resource_attr: Dict[str, Any]) -> bool:
    payload = {
        "requestId": str(uuid.uuid4()),
        "principal": {
            "id": principal["id"],
            "roles": principal["roles"],
            "attr": {"tenant_id": principal["tenant_id"]}
        },
        "resources": [
            {
                "actions": [action],
                "resource": {
                    "id": resource_id,
                    "kind": resource_kind,
                    "attr": resource_attr
                }
            }
        ]
    }
    
    try:
        with httpx.Client() as client:
            res = client.post(f"{CERBOS_URL}/api/check/resources", json=payload, timeout=2.0)
            if res.status_code == 200:
                results = res.json().get("results", [])
                if results:
                    effect = results[0].get("actions", {}).get(action, "EFFECT_DENY")
                    return effect == "EFFECT_ALLOW"
    except Exception:
        # Fallback to local policy emulator if Cerbos PDP server is unreachable
        print(f"[Warning] Cerbos PDP unreachable at {CERBOS_URL}. Emulating authorization rules locally.")
    
    # --- Local Emulation of compliance_evidence.yaml Policies ---
    roles = principal["roles"]
    tenant_id = principal["tenant_id"]
    res_tenant_id = resource_attr.get("tenant_id")
    
    if "super-admin" in roles:
        return True
        
    if action == "create":
        # Allow system-workload to push evidence
        return "system-workload" in roles or "agent-orchestrator" in roles or "tenant-admin" in roles or "tenant-user" in roles
        
    if action == "read":
        if "compliance-auditor" in roles:
            return True
        if "tenant-admin" in roles and tenant_id == res_tenant_id:
            return True
            
    return False

# --- Endpoint Handlers ---

@app.get("/")
def read_root():
    return {"message": "Governance Engine is running"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/v1/evidence", response_model=EvidenceResponse, status_code=201)
def create_evidence(
    evidence: EvidenceCreate, 
    principal: Dict[str, Any] = Depends(get_principal), 
    db: Session = Depends(get_db)
):
    # Authz check
    tenant_id = principal["tenant_id"]
    if not is_authorized(principal, "compliance_evidence", "new", "create", {"tenant_id": tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized: Principal cannot write GRC compliance evidence")

    evidence_id = str(uuid.uuid4())
    timestamp = datetime.utcnow()
    minio_path = f"tenants/{tenant_id}/evidence/{timestamp.strftime('%Y-%m-%d')}/{evidence_id}.json"

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

    db_evidence = DBComplianceEvidence(
        evidence_id=evidence_id,
        tenant_id=tenant_id,
        control_id=evidence.control_id,
        source_component=evidence.source_component,
        event_type=evidence.event_type,
        severity=evidence.severity,
        payload=evidence.payload,
        minio_object_path=minio_path,
        created_at=timestamp
    )
    db.add(db_evidence)
    db.commit()
    db.refresh(db_evidence)

    # ── Upload evidence JSON to MinIO in background ────────────────────────
    if MINIO_ENDPOINT:
        evidence_json = json.dumps({
            "evidence_id": evidence_id,
            "tenant_id": tenant_id,
            "control_id": evidence.control_id,
            "source_component": evidence.source_component,
            "event_type": evidence.event_type,
            "severity": evidence.severity,
            "payload": evidence.payload,
            "created_at": timestamp.isoformat()
        })
        try:
            with httpx.Client() as minio_client:
                put_res = minio_client.put(
                    f"{MINIO_ENDPOINT}/{MINIO_BUCKET}/{minio_path}",
                    content=evidence_json.encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(len(evidence_json))
                    },
                    auth=(MINIO_ACCESS_KEY, MINIO_SECRET_KEY),
                    timeout=5.0
                )
                if put_res.status_code not in (200, 201, 204):
                    print(f"[MinIO] Upload warning: {put_res.status_code} {put_res.text[:100]}")
                else:
                    print(f"[MinIO] Evidence uploaded to: {minio_path}")
        except Exception as e:
            print(f"[MinIO] Upload failed (non-blocking): {e}")

    return {
        "evidence_id": uuid.UUID(db_evidence.evidence_id),
        "control_id": db_evidence.control_id,
        "source_component": db_evidence.source_component,
        "event_type": db_evidence.event_type,
        "severity": db_evidence.severity,
        "payload": db_evidence.payload,
        "minio_object_path": db_evidence.minio_object_path,
        "created_at": db_evidence.created_at
    }

@app.get("/api/v1/compliance/status", response_model=ComplianceStatusResponse)
def get_compliance_status(
    principal: Dict[str, Any] = Depends(get_principal), 
    db: Session = Depends(get_db)
):
    tenant_id = principal["tenant_id"]
    # Authz check
    if not is_authorized(principal, "compliance_evidence", "status", "read", {"tenant_id": tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized: Principal cannot read GRC compliance status")

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text(f"SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

    controls_summary = []
    compliant_count = 0

    # Severity weights for graded scoring
    SEVERITY_WEIGHTS = {"info": 0, "low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}
    # Evidence is considered fresh if within the last 7 days
    FRESHNESS_DAYS = 7
    freshness_cutoff = datetime.utcnow()

    for control_id in CONTROLS_DB.keys():
        if DATABASE_URL.startswith("sqlite"):
            evidence_rows = db.query(DBComplianceEvidence).filter(
                DBComplianceEvidence.tenant_id == tenant_id,
                DBComplianceEvidence.control_id == control_id
            ).all()
        else:
            evidence_rows = db.query(DBComplianceEvidence).filter(
                DBComplianceEvidence.control_id == control_id
            ).all()

        evidence_count = len(evidence_rows)

        # ── Graded scoring ──────────────────────────────────────────────────
        # A control is COMPLIANT when: at least one fresh evidence exists AND
        # the weighted average severity of fresh events is below a threshold.
        fresh_rows = [
            r for r in evidence_rows
            if r.created_at and (freshness_cutoff - r.created_at).days <= FRESHNESS_DAYS
        ]
        fresh_count = len(fresh_rows)
        if fresh_count == 0:
            status = "non_compliant" if evidence_count == 0 else "stale"
            score_contribution = 0.0
        else:
            # Average severity weight of fresh violations (0 = good, 1 = bad)
            avg_weight = sum(SEVERITY_WEIGHTS.get(r.severity, 0) for r in fresh_rows) / fresh_count
            # Compliance improves as severity drops; baseline: info-only events = compliant
            if avg_weight <= 0.1:
                status = "compliant"
                score_contribution = 1.0
                compliant_count += 1
            elif avg_weight <= 0.5:
                status = "partial"
                score_contribution = 0.5
            else:
                status = "non_compliant"
                score_contribution = 0.0
        # Use graded result — no binary override
        controls_summary.append(
            ControlStatus(
                control_id=control_id,
                status=status,
                evidence_count=evidence_count
            )
        )
        compliant_count += score_contribution  # accumulate weighted scores

    total_controls = len(CONTROLS_DB)
    score = (compliant_count / total_controls) * 100.0 if total_controls > 0 else 100.0

    return ComplianceStatusResponse(
        tenant_id=tenant_id,
        overall_compliance_score=round(score, 2),
        controls=controls_summary
    )

# --- AI-SPM & AI-BOM Pydantic Models ---
class AIBOMAsset(BaseModel):
    asset_id: str
    name: str
    type: str
    location: str
    status: str
    risk_level: str
    risk_factors: List[str]

class AIBOMResponse(BaseModel):
    generated_at: datetime
    total_discovered_assets: int
    high_risk_violations: int
    assets: List[AIBOMAsset]

class TopologyNode(BaseModel):
    id: str
    label: str
    type: str # 'endpoint', 'app', 'database', 'runtime'
    status: str # 'safe', 'warning', 'danger'
    details: str

class TopologyLink(BaseModel):
    source: str
    target: str
    label: str

class TopologyResponse(BaseModel):
    nodes: List[TopologyNode]
    links: List[TopologyLink]

# --- AI-SPM Endpoints ---

@app.get("/api/v1/compliance/ai-bom", response_model=AIBOMResponse)
def get_ai_bom(principal: Dict[str, Any] = Depends(get_principal), db: Session = Depends(get_db)):
    tenant_id = principal["tenant_id"]
    if not is_authorized(principal, "compliance_evidence", "status", "read", {"tenant_id": tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized: Principal cannot read AI-BOM")

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text(f"SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

    # Fetch evidence logs to compute risks dynamically
    if DATABASE_URL.startswith("sqlite"):
        evidences = db.query(DBComplianceEvidence).filter(DBComplianceEvidence.tenant_id == tenant_id).all()
    else:
        evidences = db.query(DBComplianceEvidence).all()

    # Track risk factors
    guardrail_violations = [e for e in evidences if e.event_type == "guardrail_violation"]
    agt_violations = [e for e in evidences if e.event_type == "agent_action_intercepted"]

    assets = []
    high_risk_count = 0

    # 1. User/Developer workstation (Vector: Endpoint)
    endpoint_risk = "info"
    endpoint_factors = []
    if guardrail_violations:
        endpoint_risk = "medium"
        endpoint_factors.append("policy_violation_in_history")
    
    assets.append(AIBOMAsset(
        asset_id="ast_endpoint_01",
        name=f"Developer Workstation ({principal['id']})",
        type="developer_endpoint",
        location=f"LAN Client Host IP (Tenant: {tenant_id})",
        status="active",
        risk_level=endpoint_risk,
        risk_factors=endpoint_factors
    ))

    # 2. Agent Orchestrator (Vector: Agentic Monitor)
    orch_risk = "info"
    orch_factors = []
    if agt_violations:
        orch_risk = "high"
        high_risk_count += 1
        orch_factors.append("unapproved_tool_execution_intercepted")
    
    assets.append(AIBOMAsset(
        asset_id="ast_orchestrator_01",
        name="Agent Orchestrator (LangGraph Core)",
        type="autonomous_agent",
        location="Kubernetes Cluster Pod Namespace",
        status="active",
        risk_level=orch_risk,
        risk_factors=orch_factors
    ))

    # 3. LiteLLM Proxy Gateway (Vector: Network & API Proxy)
    assets.append(AIBOMAsset(
        asset_id="ast_gateway_01",
        name="LiteLLM API Gateway Router",
        type="ai_gateway_proxy",
        location="Kubernetes Cluster Service (Port 4000)",
        status="active",
        risk_level="info",
        risk_factors=[]
    ))

    # 4. External Ollama Machine (Vector: External Host)
    assets.append(AIBOMAsset(
        asset_id="ast_llm_01",
        name="External Ollama Model Runner",
        type="llm_model_runtime",
        location="LAN Server IP (Port 11434)",
        status="active",
        risk_level="info",
        risk_factors=[]
    ))

    # 5. Qdrant & Postgres Databases (Vector: Datastore)
    assets.append(AIBOMAsset(
        asset_id="ast_qdrant_01",
        name="Qdrant Vector Database",
        type="vector_datastore",
        location="Kubernetes Cluster StatefulSet (Port 6333)",
        status="active",
        risk_level="info",
        risk_factors=[]
    ))

    return AIBOMResponse(
        generated_at=datetime.utcnow(),
        total_discovered_assets=len(assets),
        high_risk_violations=high_risk_count,
        assets=assets
    )

@app.get("/api/v1/compliance/topology", response_model=TopologyResponse)
def get_topology(principal: Dict[str, Any] = Depends(get_principal), db: Session = Depends(get_db)):
    tenant_id = principal["tenant_id"]
    if not is_authorized(principal, "compliance_evidence", "status", "read", {"tenant_id": tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized: Principal cannot read topology map")

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text(f"SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

    # Fetch evidence logs to determine node statuses
    if DATABASE_URL.startswith("sqlite"):
        evidences = db.query(DBComplianceEvidence).filter(DBComplianceEvidence.tenant_id == tenant_id).all()
    else:
        evidences = db.query(DBComplianceEvidence).all()

    has_guardrail = any(e.event_type == "guardrail_violation" for e in evidences)
    has_agt = any(e.event_type == "agent_action_intercepted" for e in evidences)

    nodes = [
        TopologyNode(
            id="user", 
            label="User Browser", 
            type="endpoint", 
            status="danger" if has_guardrail else "safe",
            details=f"LAN User Session (Role: {principal['roles'][0]})"
        ),
        TopologyNode(
            id="dashboard", 
            label="Dashboard Console", 
            type="app", 
            status="safe",
            details="React UI Console (NodePort: 30082)"
        ),
        TopologyNode(
            id="orchestrator", 
            label="Agent Orchestrator", 
            type="app", 
            status="danger" if has_agt else "safe",
            details="LangGraph Orchestration Pod (Port 8001)"
        ),
        TopologyNode(
            id="governance", 
            label="Governance Engine", 
            type="app", 
            status="safe",
            details="FastAPI Auditing Pod (Port 8000)"
        ),
        TopologyNode(
            id="postgres", 
            label="PostgreSQL Database", 
            type="database", 
            status="safe",
            details="Audits & Checkpoints Storage (Port 5432)"
        ),
        TopologyNode(
            id="qdrant", 
            label="Qdrant Vector DB", 
            type="database", 
            status="safe",
            details="Knowledge Vectors Storage (Port 6333)"
        ),
        TopologyNode(
            id="litellm", 
            label="LiteLLM Gateway", 
            type="runtime", 
            status="safe",
            details="Model Gateway Router (Port 4000)"
        ),
        TopologyNode(
            id="ollama", 
            label="External Ollama Node", 
            type="runtime", 
            status="safe",
            details="LAN Model Runner Machine (Port 11434)"
        )
    ]

    links = [
        TopologyLink(source="user", target="dashboard", label="HTTPS"),
        TopologyLink(source="dashboard", target="orchestrator", label="REST API"),
        TopologyLink(source="orchestrator", target="postgres", label="SQL"),
        TopologyLink(source="orchestrator", target="governance", label="GRC webhook"),
        TopologyLink(source="governance", target="postgres", label="SQL"),
        TopologyLink(source="orchestrator", target="qdrant", label="gRPC"),
        TopologyLink(source="orchestrator", target="litellm", label="REST API"),
        TopologyLink(source="litellm", target="ollama", label="External bridge")
    ]

    return TopologyResponse(nodes=nodes, links=links)

