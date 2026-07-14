from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, List, TypedDict, Optional
import uuid
import httpx
from datetime import datetime
import os
from langgraph.graph import StateGraph, END

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
    
    # Simulating simple SQL injection or bypass detection
    is_safe = True
    output = ""
    if "select * from" in user_input or "drop table" in user_input or "admin bypass" in user_input:
        is_safe = False
        output = "Policy violation detected: Input contains restricted database command patterns."
        
        # Trigger async report to Governance Engine
        try:
            with httpx.Client() as client:
                client.post(
                    f"{GOV_URL}/api/v1/evidence",
                    headers={"X-Tenant-ID": state["tenant_id"]},
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
            # Fallback output logging if Governance Engine is not currently running
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
    
    # Safe fallback if guardrails marked state as unsafe
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

# --- Router function ---
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

# --- Mock Checkpoint DB ---
THREAD_STORE: Dict[str, List[Dict[str, Any]]] = {}

# --- Pydantic API Models ---
class ThreadCreate(BaseModel):
    agent_type: str = "customer-support-graph"
    initial_state: Optional[Dict[str, Any]] = None

class ThreadRun(BaseModel):
    input: str
    stream: bool = False

# --- Helper header dependency ---
def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id

# --- FastAPI endpoints ---

@app.get("/")
def read_root():
    return {"message": "Agent Orchestrator is running"}

@app.post("/api/v1/threads")
def create_thread(req: ThreadCreate, tenant_id: str = Depends(get_tenant_id)):
    thread_id = f"th_{uuid.uuid4().hex[:12]}"
    THREAD_STORE[thread_id] = []
    
    # Store initial state checkpoint
    checkpoint = {
        "checkpoint_id": f"cp_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.utcnow().isoformat(),
        "step": "init",
        "state": {
            "input": "",
            "output": "Session initialized.",
            "steps": [],
            "is_safe": True,
            "tenant_id": tenant_id
        }
    }
    THREAD_STORE[thread_id].append(checkpoint)
    return {"thread_id": thread_id, "status": "idle", "created_at": checkpoint["timestamp"]}

@app.post("/api/v1/threads/{thread_id}/runs")
def run_thread(thread_id: str, req: ThreadRun, tenant_id: str = Depends(get_tenant_id)):
    if thread_id not in THREAD_STORE:
        raise HTTPException(status_code=404, detail="Thread session not found")
        
    initial_state: AgentState = {
        "input": req.input,
        "output": "",
        "steps": [],
        "is_safe": True,
        "tenant_id": tenant_id
    }
    
    # Execute LangGraph workflow synchronously
    final_output_state = compiled_graph.invoke(initial_state)
    
    # Save checkpoint state history
    checkpoint = {
        "checkpoint_id": f"cp_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.utcnow().isoformat(),
        "step": "run_completion",
        "state": dict(final_output_state)
    }
    THREAD_STORE[thread_id].append(checkpoint)
    
    return {
        "output": {
            "response": final_output_state["output"],
            "steps_executed": final_output_state["steps"]
        },
        "checkpoint_id": checkpoint["checkpoint_id"]
    }

@app.get("/api/v1/threads/{thread_id}/state")
def get_thread_state(thread_id: str):
    if thread_id not in THREAD_STORE:
        raise HTTPException(status_code=404, detail="Thread session not found")
        
    history = []
    for cp in THREAD_STORE[thread_id]:
        history.append({
            "checkpoint_id": cp["checkpoint_id"],
            "timestamp": cp["timestamp"],
            "step": cp["step"]
        })
        
    return {
        "thread_id": thread_id,
        "history": list(reversed(history))
    }
