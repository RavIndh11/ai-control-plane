from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, List, TypedDict, Optional
import uuid
import httpx
import os
from datetime import datetime
from langgraph.graph import StateGraph, END
from sqlalchemy import create_engine, Column, String, DateTime, JSON, ForeignKey, Integer, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# --- Database Configurations ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./orchestrator.db")
CERBOS_URL = os.getenv("CERBOS_URL", "http://localhost:3592")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Database Models ---
class DBAgentThread(Base):
    __tablename__ = "agent_threads"

    thread_id = Column(String(255), primary_key=True)
    tenant_id = Column(String(64), index=True, nullable=False)
    agent_type = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    checkpoints = relationship("DBAgentCheckpoint", back_populates="thread", cascade="all, delete-orphan")

class DBAgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String(255), ForeignKey("agent_threads.thread_id", ondelete="CASCADE"), nullable=False)
    checkpoint_id = Column(String(255), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    step = Column(String(100), nullable=False)
    state_data = Column(JSON, nullable=False)

    thread = relationship("DBAgentThread", back_populates="checkpoints")

# Auto-create tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Agent Orchestrator API",
    description="Multi-agent orchestrator service built on LangGraph",
    version="1.0.0"
)

GOV_URL = os.getenv("GOVERNANCE_ENGINE_URL", "http://localhost:8000")

# --- LangGraph Agent State Definition ---
class AgentState(TypedDict):
    input: str
    output: str
    steps: List[str]
    is_safe: bool
    tenant_id: str

# --- Node 1: Guardrail Check Node ---
def guardrail_node(state: AgentState) -> AgentState:
    user_input = state["input"].lower()
    steps = list(state.get("steps", []))
    steps.append("guardrail_check")
    
    is_safe = True
    output = ""
    if "select * from" in user_input or "drop table" in user_input or "admin bypass" in user_input:
        is_safe = False
        output = "Policy violation detected: Input contains restricted database command patterns."
        
        try:
            with httpx.Client() as client:
                client.post(
                    f"{GOV_URL}/api/v1/evidence",
                    headers={
                        "X-Tenant-ID": state["tenant_id"],
                        "X-User-Role": "system-workload"
                    },
                    json={
                        "control_id": "SOC2-CC-6.1",
                        "source_component": "agent-orchestrator",
                        "event_type": "guardrail_violation",
                        "severity": "high",
                        "payload": {
                            "input_query": state["input"],
                            "message": "Blocked SQL injection or security bypass query pattern."
                        }
                    },
                    timeout=2.0
                )
        except Exception as e:
            print(f"[Warning] Failed to push compliance evidence: {e}")
            
    return {
        "input": state["input"],
        "output": output,
        "steps": steps,
        "is_safe": is_safe,
        "tenant_id": state["tenant_id"]
    }

# --- Node 2: Generation Node ---
def generation_node(state: AgentState) -> AgentState:
    steps = list(state.get("steps", []))
    steps.append("generation")
    
    if not state["is_safe"]:
        return state
        
    user_input = state["input"]
    output = f"Processed query '{user_input}' successfully within tenant context."
    
    return {
        "input": state["input"],
        "output": output,
        "steps": steps,
        "is_safe": state["is_safe"],
        "tenant_id": state["tenant_id"]
    }

def routing_logic(state: AgentState) -> str:
    if not state["is_safe"]:
        return END
    return "generation"

# --- Build LangGraph Pipeline ---
workflow = StateGraph(AgentState)
workflow.add_node("guardrail", guardrail_node)
workflow.add_node("generation", generation_node)

workflow.set_entry_point("guardrail")
workflow.add_conditional_edges(
    "guardrail",
    routing_logic,
    {
        "generation": "generation",
        END: END
    }
)
workflow.add_edge("generation", END)
compiled_graph = workflow.compile()

# --- Pydantic API Models ---
class ThreadCreate(BaseModel):
    agent_type: str = "customer-support-graph"
    initial_state: Optional[Dict[str, Any]] = None

class ThreadRun(BaseModel):
    input: str
    stream: bool = False

# --- Database Session Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Identity / Principal Dependency ---
def get_principal(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_user_role: str = Header("tenant-user", alias="X-User-Role"),
    x_user_id: str = Header("user_default", alias="X-User-ID")
) -> Dict[str, Any]:
    return {
        "id": x_user_id,
        "roles": [x_user_role],
        "tenant_id": x_tenant_id
    }

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
        print(f"[Warning] Cerbos PDP unreachable at {CERBOS_URL}. Emulating authorization rules locally.")
    
    # --- Local Emulation of agent_threads.yaml Policies ---
    roles = principal["roles"]
    tenant_id = principal["tenant_id"]
    res_tenant_id = resource_attr.get("tenant_id")
    
    if "super-admin" in roles:
        return True
        
    if action in ["read", "write"]:
        if "tenant-user" in roles and tenant_id == res_tenant_id:
            return True
        if "tenant-admin" in roles and tenant_id == res_tenant_id:
            return True
            
    if action == "delete":
        if "tenant-admin" in roles and tenant_id == res_tenant_id:
            return True
            
    return False

# --- FastAPI endpoints ---

@app.get("/")
def read_root():
    return {"message": "Agent Orchestrator is running"}

@app.post("/api/v1/threads")
def create_thread(req: ThreadCreate, principal: Dict[str, Any] = Depends(get_principal), db: Session = Depends(get_db)):
    tenant_id = principal["tenant_id"]
    
    # Check Cerbos Authz
    if not is_authorized(principal, "agent_thread", "new", "write", {"tenant_id": tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized: Principal cannot write threads for this tenant")

    thread_id = f"th_{uuid.uuid4().hex[:12]}"
    timestamp = datetime.utcnow()
    
    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text(f"SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

    # Save Thread
    db_thread = DBAgentThread(
        thread_id=thread_id,
        tenant_id=tenant_id,
        agent_type=req.agent_type,
        created_at=timestamp
    )
    db.add(db_thread)
    
    # Save Initial State Checkpoint
    checkpoint_data = {
        "input": "",
        "output": "Session initialized.",
        "steps": [],
        "is_safe": True,
        "tenant_id": tenant_id
    }
    
    db_checkpoint = DBAgentCheckpoint(
        thread_id=thread_id,
        checkpoint_id=f"cp_{uuid.uuid4().hex[:8]}",
        timestamp=timestamp,
        step="init",
        state_data=checkpoint_data
    )
    db.add(db_checkpoint)
    db.commit()
    
    return {"thread_id": thread_id, "status": "idle", "created_at": timestamp.isoformat()}

@app.post("/api/v1/threads/{thread_id}/runs")
def run_thread(thread_id: str, req: ThreadRun, principal: Dict[str, Any] = Depends(get_principal), db: Session = Depends(get_db)):
    tenant_id = principal["tenant_id"]

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text(f"SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

    # Fetch thread checking isolation
    if DATABASE_URL.startswith("sqlite"):
        thread = db.query(DBAgentThread).filter(
            DBAgentThread.thread_id == thread_id,
            DBAgentThread.tenant_id == tenant_id
        ).first()
    else:
        thread = db.query(DBAgentThread).filter(DBAgentThread.thread_id == thread_id).first()
        
    if not thread:
        raise HTTPException(status_code=404, detail="Thread session not found")
        
    # Check Cerbos Authz
    if not is_authorized(principal, "agent_thread", thread_id, "write", {"tenant_id": thread.tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized: Principal cannot write to this thread")

    initial_state: AgentState = {
        "input": req.input,
        "output": "",
        "steps": [],
        "is_safe": True,
        "tenant_id": tenant_id
    }
    
    # Execute LangGraph workflow synchronously
    final_output_state = compiled_graph.invoke(initial_state)
    
    # Save Checkpoint
    checkpoint_id = f"cp_{uuid.uuid4().hex[:8]}"
    db_checkpoint = DBAgentCheckpoint(
        thread_id=thread_id,
        checkpoint_id=checkpoint_id,
        timestamp=datetime.utcnow(),
        step="run_completion",
        state_data=dict(final_output_state)
    )
    db.add(db_checkpoint)
    db.commit()
    
    return {
        "output": {
            "response": final_output_state["output"],
            "steps_executed": final_output_state["steps"]
        },
        "checkpoint_id": checkpoint_id
    }

@app.get("/api/v1/threads/{thread_id}/state")
def get_thread_state(thread_id: str, principal: Dict[str, Any] = Depends(get_principal), db: Session = Depends(get_db)):
    tenant_id = principal["tenant_id"]

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text(f"SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})

    # Fetch thread checking isolation
    if DATABASE_URL.startswith("sqlite"):
        thread = db.query(DBAgentThread).filter(
            DBAgentThread.tenant_id == tenant_id,
            DBAgentThread.thread_id == thread_id
        ).first()
    else:
        thread = db.query(DBAgentThread).filter(DBAgentThread.thread_id == thread_id).first()
        
    if not thread:
        raise HTTPException(status_code=404, detail="Thread session not found")
        
    # Check Cerbos Authz
    if not is_authorized(principal, "agent_thread", thread_id, "read", {"tenant_id": thread.tenant_id}):
        raise HTTPException(status_code=403, detail="Unauthorized: Principal cannot read this thread")

    checkpoints = db.query(DBAgentCheckpoint).filter(
        DBAgentCheckpoint.thread_id == thread_id
    ).order_by(DBAgentCheckpoint.timestamp.desc()).all()
    
    history = []
    for cp in checkpoints:
        history.append({
            "checkpoint_id": cp.checkpoint_id,
            "timestamp": cp.timestamp.isoformat(),
            "step": cp.step
        })
        
    return {
        "thread_id": thread_id,
        "history": history
    }
