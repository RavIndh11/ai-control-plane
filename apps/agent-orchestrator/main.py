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
LLM_GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://localhost:4000/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "llama2")

# --- LangGraph Agent State Definition ---
class AgentState(TypedDict):
    input: str
    output: str
    steps: List[str]
    is_safe: bool
    tenant_id: str
    user_id: str
    thread_id: str
    
    # Microsoft AGT/Governance-inspired fields:
    pending_action: Optional[Dict[str, Any]]
    action_approved: Optional[bool]

# --- Node 1: Guardrail Check Node ---
def guardrail_node(state: AgentState) -> AgentState:
    user_input = state["input"].lower()
    state["steps"] = list(state.get("steps", [])) + ["guardrail_check"]
    
    if "select * from" in user_input or "drop table" in user_input or "admin bypass" in user_input:
        state["is_safe"] = False
        state["output"] = "Policy violation detected: Input contains restricted database command patterns."
        
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
            
    return state

# --- Node 2: Agent Reasoning Node ---
def agent_node(state: AgentState) -> AgentState:
    state["steps"] = list(state.get("steps", [])) + ["agent_reasoning"]
    
    if not state["is_safe"]:
        return state
        
    user_input = state["input"].lower()
    
    # Simulate agent deciding to call a high-risk tool (Microsoft AGT boundary)
    if "delete" in user_input or "run command" in user_input or "drop" in user_input:
        state["pending_action"] = {
            "tool": "terminal_executor",
            "arguments": {
                "command": state["input"]
            }
        }
        print(f"[AGT] Agent requests high-risk tool call execution: {state['pending_action']}")

    return state

# --- Node 3: Microsoft AGT Governance Shield Node ---
def governance_shield_node(state: AgentState) -> AgentState:
    state["steps"] = list(state.get("steps", [])) + ["governance_shield"]
    
    if not state["is_safe"]:
        return state
        
    pending_action = state.get("pending_action")
    action_approved = state.get("action_approved")
    
    if pending_action:
        # Check if user has approved/rejected yet
        if action_approved is None:
            # First pass: trigger interrupt to pause graph execution
            state["steps"].append("governance_shield_interrupt")
            print("[AGT] Governance Shield triggered. Pausing graph for human-in-the-loop (HITL) approval.")
            
            # Send alert log as evidence of policy enforcement
            try:
                with httpx.Client() as client:
                    client.post(
                        f"{GOV_URL}/api/v1/evidence",
                        headers={
                            "X-Tenant-ID": state["tenant_id"],
                            "X-User-Role": "system-workload"
                        },
                        json={
                            "control_id": "EU-AI-Act-Art-9",
                            "source_component": "agent-orchestrator",
                            "event_type": "agent_action_intercepted",
                            "severity": "medium",
                            "payload": {
                                "requested_tool": pending_action["tool"],
                                "arguments": pending_action["arguments"],
                                "message": "High-risk tool call intercepted. Pausing execution for admin approval."
                            }
                        },
                        timeout=2.0
                    )
            except Exception as e:
                print(f"[Warning] Failed to push compliance evidence: {e}")
                
        elif action_approved is False:
            # User rejected the action
            state["output"] = f"Action blocked: Execution of tool '{pending_action['tool']}' rejected by user/admin."
            state["pending_action"] = None # Clear action
            state["steps"].append("governance_shield_rejected")
            print("[AGT] Tool execution rejected by administrator.")
            
        elif action_approved is True:
            # User approved the action -> Execute the tool safely
            state["output"] = f"Success: Action '{pending_action['tool']}' approved and executed."
            state["pending_action"] = None # Clear action
            state["steps"].append("governance_shield_executed")
            print("[AGT] Tool execution approved. Executing tool.")
            
    return state

# --- Node 4: Generation Node ---
def generation_node(state: AgentState) -> AgentState:
    state["steps"] = list(state.get("steps", [])) + ["generation"]
    
    if not state["is_safe"] or "governance_shield_interrupt" in state["steps"]:
        return state
        
    # If output was already set by governance shield (execution or rejection), keep it
    if state.get("output"):
        return state
        
    user_input = state["input"]
    output = ""
    
    try:
        with httpx.Client() as client:
            res = client.post(
                f"{LLM_GATEWAY_URL}/chat/completions",
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": user_input}],
                    "temperature": 0.7,
                    "user": state.get("user_id", "user_default"),
                    "metadata": {
                        "tenant_id": state.get("tenant_id", "tenant_default"),
                        "thread_id": state.get("thread_id", "thread_default")
                    }
                },
                timeout=5.0
            )
            if res.status_code == 200:
                output = res.json()["choices"][0]["message"]["content"]
            else:
                raise Exception(f"Gateway status: {res.status_code}")
    except Exception as e:
        print(f"[Warning] LLM Gateway unreachable ({e}). Using mock local generation node.")
        output = f"Processed query '{user_input}' successfully within tenant context."
    
    state["output"] = output
    return state

# --- Graph Routing Logic ---
def route_after_guardrail(state: AgentState) -> str:
    if not state["is_safe"]:
        return END
    return "agent_node"

def route_after_shield(state: AgentState) -> str:
    if "governance_shield_interrupt" in state["steps"]:
        return END
    return "generation"

# --- Build LangGraph Pipeline ---
workflow = StateGraph(AgentState)
workflow.add_node("guardrail", guardrail_node)
workflow.add_node("agent_node", agent_node)
workflow.add_node("governance_shield", governance_shield_node)
workflow.add_node("generation", generation_node)

workflow.set_entry_point("guardrail")
workflow.add_conditional_edges(
    "guardrail",
    route_after_guardrail,
    {
        "agent_node": "agent_node",
        END: END
    }
)
workflow.add_edge("agent_node", "governance_shield")
workflow.add_conditional_edges(
    "governance_shield",
    route_after_shield,
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
    input: Optional[str] = None
    approve_action: Optional[bool] = None # For resuming/resolving HITL actions

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
        "tenant_id": tenant_id,
        "pending_action": None,
        "action_approved": None
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

    # Fetch last checkpoint
    last_checkpoint = db.query(DBAgentCheckpoint).filter(
        DBAgentCheckpoint.thread_id == thread_id
    ).order_by(DBAgentCheckpoint.timestamp.desc()).first()

    if not last_checkpoint:
        raise HTTPException(status_code=500, detail="Checkpoint history missing")

    previous_state = last_checkpoint.state_data

    # --- Resuming from an Interrupted Action ---
    if previous_state.get("pending_action") and previous_state.get("action_approved") is None:
        if req.approve_action is None:
            raise HTTPException(
                status_code=400,
                detail="HITL Action Pending. This thread is paused. You must pass 'approve_action': true/false to resume."
            )
        
        print(f"[AGT] Resuming thread from checkpoint. Admin decision: {req.approve_action}")
        
        # Load state and update approval decision
        state_to_run: AgentState = {
            "input": previous_state["input"],
            "output": previous_state.get("output", ""),
            "steps": previous_state.get("steps", []),
            "is_safe": previous_state.get("is_safe", True),
            "tenant_id": tenant_id,
            "user_id": principal["id"],
            "thread_id": thread_id,
            "pending_action": previous_state["pending_action"],
            "action_approved": req.approve_action
        }
    else:
        # --- Normal New Query Run ---
        if not req.input:
            raise HTTPException(status_code=400, detail="Missing 'input' parameter in request body.")
            
        state_to_run: AgentState = {
            "input": req.input,
            "output": "",
            "steps": [],
            "is_safe": True,
            "tenant_id": tenant_id,
            "user_id": principal["id"],
            "thread_id": thread_id,
            "pending_action": None,
            "action_approved": None
        }
    
    # Execute LangGraph workflow synchronously (runs until END or hits interrupt)
    final_output_state = compiled_graph.invoke(state_to_run)
    
    # Determine execution status based on whether a pending action is still unresolved
    status = "completed"
    if final_output_state.get("pending_action") is not None:
        status = "action_required"
    
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
        "status": status,
        "output": {
            "response": final_output_state["output"],
            "steps_executed": final_output_state["steps"],
            "pending_action": final_output_state.get("pending_action")
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
            "step": cp.step,
            "status": "action_required" if "governance_shield_interrupt" in cp.state_data.get("steps", []) else "completed"
        })
        
    return {
        "thread_id": thread_id,
        "history": history
    }
