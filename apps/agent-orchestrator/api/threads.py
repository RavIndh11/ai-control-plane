"""
api/threads.py — Agent thread CRUD routes.

Endpoints:
  POST /threads              — create a new agent thread
  GET  /threads/{id}/state   — read thread checkpoint history
  GET  /runs/pending         — list all threads awaiting HITL approval
  POST /threads/{id}/approve — admin approve/reject a pending action
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth.principal import get_principal
from authz.cerbos   import is_authorized
from db.models      import DBAgentThread, DBAgentCheckpoint
from db.session     import DATABASE_URL, get_db

router = APIRouter(tags=["threads"])


# --- Pydantic models ---
class ThreadCreate(BaseModel):
    agent_type:    str = "customer-support-graph"
    initial_state: Optional[Dict[str, Any]] = None


class ApproveActionRequest(BaseModel):
    approve: bool


# --- Helper to wire get_db dependency correctly ---
def _db_dep(principal: Dict[str, Any] = Depends(get_principal)):
    yield from get_db(principal)


# -------------------------------------------------------------------------
# POST /threads  — create thread
# -------------------------------------------------------------------------
@router.post("/threads")
def create_thread(
    req: ThreadCreate,
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session              = Depends(_db_dep),
):
    tenant_id = principal["tenant_id"]

    if not is_authorized(
        principal, "agent_thread", "new", "write", {"tenant_id": tenant_id}
    ):
        raise HTTPException(status_code=403, detail="Unauthorized: cannot create threads")

    thread_id = f"th_{uuid.uuid4().hex[:12]}"
    timestamp = datetime.utcnow()

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

    db_thread = DBAgentThread(
        thread_id=thread_id,
        tenant_id=tenant_id,
        agent_type=req.agent_type,
        created_at=timestamp,
    )
    db.add(db_thread)

    init_checkpoint = DBAgentCheckpoint(
        thread_id=thread_id,
        checkpoint_id=f"cp_{uuid.uuid4().hex[:8]}",
        timestamp=timestamp,
        step="init",
        state_data={
            "input": "", "output": "Session initialized.",
            "steps": [], "is_safe": True,
            "tenant_id": tenant_id,
            "pending_action": None, "action_approved": None,
            "action_risk_score": None, "approval_chain": None,
            "approval_timeout_at": None, "break_glass_used": None,
            "audit_hmac": None,
        },
    )
    db.add(init_checkpoint)
    db.commit()

    return {"thread_id": thread_id, "status": "idle", "created_at": timestamp.isoformat()}


# -------------------------------------------------------------------------
# GET /threads/{thread_id}/state
# -------------------------------------------------------------------------
@router.get("/threads/{thread_id}/state")
def get_thread_state(
    thread_id: str,
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session              = Depends(_db_dep),
):
    tenant_id = principal["tenant_id"]

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

    thread = (
        db.query(DBAgentThread)
        .filter(
            DBAgentThread.thread_id == thread_id,
            *([DBAgentThread.tenant_id == tenant_id] if DATABASE_URL.startswith("sqlite") else []),
        )
        .first()
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    if not is_authorized(
        principal, "agent_thread", thread_id, "read", {"tenant_id": thread.tenant_id}
    ):
        raise HTTPException(status_code=403, detail="Unauthorized: cannot read this thread")

    checkpoints = (
        db.query(DBAgentCheckpoint)
        .filter(DBAgentCheckpoint.thread_id == thread_id)
        .order_by(DBAgentCheckpoint.timestamp.desc())
        .all()
    )

    history = [
        {
            "checkpoint_id": cp.checkpoint_id,
            "timestamp":     cp.timestamp.isoformat(),
            "step":          cp.step,
            "status": (
                "action_required"
                if "governance_shield_interrupt" in cp.state_data.get("steps", [])
                else "completed"
            ),
            "risk_score":     cp.state_data.get("action_risk_score"),
            "approval_chain": cp.state_data.get("approval_chain"),
        }
        for cp in checkpoints
    ]
    return {"thread_id": thread_id, "history": history}


# -------------------------------------------------------------------------
# GET /runs/pending  — HITL approval queue
# -------------------------------------------------------------------------
@router.get("/runs/pending")
def get_pending_runs(
    principal: Dict[str, Any] = Depends(get_principal),
    db: Session              = Depends(_db_dep),
):
    checkpoints = (
        db.query(DBAgentCheckpoint)
        .order_by(DBAgentCheckpoint.timestamp.desc())
        .all()
    )
    pending = []
    seen = set()
    for cp in checkpoints:
        if cp.thread_id in seen:
            continue
        seen.add(cp.thread_id)
        s = cp.state_data
        if s.get("pending_action") and s.get("action_approved") is None:
            pending.append({
                "thread_id":       cp.thread_id,
                "checkpoint_id":   cp.checkpoint_id,
                "timestamp":       cp.timestamp.isoformat(),
                "step":            cp.step,
                "tenant_id":       s.get("tenant_id"),
                "user_id":         s.get("user_id"),
                "pending_action":  s.get("pending_action"),
                "risk_score":      s.get("action_risk_score"),
                "approval_chain":  s.get("approval_chain"),
                "timeout_at":      s.get("approval_timeout_at"),
            })
    return pending


# -------------------------------------------------------------------------
# POST /threads/{thread_id}/approve
# -------------------------------------------------------------------------
@router.post("/threads/{thread_id}/approve")
def approve_thread_run(
    thread_id: str,
    req:       ApproveActionRequest,
    principal: Dict[str, Any] = Depends(get_principal),
    db:        Session        = Depends(_db_dep),
):
    tenant_id = principal["tenant_id"]
    if not is_authorized(
        principal, "agent_thread", thread_id, "write", {"tenant_id": tenant_id}
    ):
        raise HTTPException(status_code=403, detail="Unauthorized")

    checkpoint = (
        db.query(DBAgentCheckpoint)
        .filter(DBAgentCheckpoint.thread_id == thread_id)
        .order_by(DBAgentCheckpoint.timestamp.desc())
        .first()
    )
    if not checkpoint:
        raise HTTPException(status_code=404, detail="No checkpoints found")

    state = dict(checkpoint.state_data)
    if not state.get("pending_action") or state.get("action_approved") is not None:
        raise HTTPException(status_code=400, detail="No pending action to approve/reject")

    state["action_approved"] = req.approve
    checkpoint.state_data    = state

    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(checkpoint, "state_data")
    db.commit()

    return {
        "status":         "success",
        "thread_id":      thread_id,
        "action_approved": req.approve,
    }
