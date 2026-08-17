"""
api/runs.py — Agent run execution routes.

Endpoints:
  POST /threads/{thread_id}/runs        — synchronous run
  POST /threads/{thread_id}/runs/stream — SSE streaming run
"""
import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional

try:
    from langfuse import observe, get_client, propagate_attributes
    _HAS_LANGFUSE = True
except Exception:
    try:
        from langfuse.decorators import observe, langfuse_context
        _HAS_LANGFUSE = True
    except Exception:
        _HAS_LANGFUSE = False
        def observe(name: str = ""):  # type: ignore
            def decorator(fn): return fn
            return decorator
        class propagate_attributes:  # type: ignore
            def __init__(self, **kwargs): pass
            def __enter__(self): pass
            def __exit__(self, *args): pass


import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth.principal import get_principal
from agents.graph   import get_graph
from agents.state   import AgentState, empty_state
from db.models      import DBAgentThread, DBAgentCheckpoint
from db.session     import DATABASE_URL, get_db

import os

for k in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]:
    v = os.getenv(k)
    if v:
        os.environ[k] = v.strip("\"' \t\n\r")


def _flush_langfuse():
    try:
        from langfuse import Langfuse, get_client
        try:
            get_client().flush()
        except Exception:
            Langfuse().flush()
    except Exception as exc:
        print(f"[Langfuse] Explicit flush error: {exc}")

LLM_GATEWAY_URL: str   = os.getenv("LLM_GATEWAY_URL",   "http://localhost:4000/v1")
LLM_MODEL: str         = os.getenv("LLM_MODEL",         "llama2")

router = APIRouter(tags=["runs"])


class ThreadRun(BaseModel):
    input:          Optional[str]  = None
    approve_action: Optional[bool] = None   # HITL resume
    break_glass:    Optional[bool] = False  # super-admin fast-path


def _db_dep(principal: Dict[str, Any] = Depends(get_principal)):
    yield from get_db(principal)


def _resolve_state(
    req: ThreadRun,
    previous_state: dict,
    tenant_id: str,
    user_id: str,
    thread_id: str,
    agent_type: str,
) -> AgentState:
    """
    Build the AgentState to pass into the graph for this run.
    Handles both new-query runs and HITL-resume runs.
    """
    # ── HITL resume ───────────────────────────────────────────────────────────
    if previous_state.get("pending_action") and previous_state.get("action_approved") is None:
        if req.approve_action is None and not req.break_glass:
            raise HTTPException(
                status_code=400,
                detail=(
                    "HITL Action Pending. Pass 'approve_action': true/false "
                    "or 'break_glass': true to resume."
                ),
            )
        return AgentState(
            input=previous_state["input"],
            output=previous_state.get("output", ""),
            steps=previous_state.get("steps", []),
            is_safe=previous_state.get("is_safe", True),
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=thread_id,
            agent_type=agent_type,
            pending_action=previous_state["pending_action"],
            action_approved=req.approve_action,
            action_risk_score=previous_state.get("action_risk_score"),
            approval_chain=previous_state.get("approval_chain"),
            approval_timeout_at=previous_state.get("approval_timeout_at"),
            break_glass_used=bool(req.break_glass),
            audit_hmac=previous_state.get("audit_hmac"),
        )

    # ── New run ───────────────────────────────────────────────────────────────
    if not req.input:
        raise HTTPException(status_code=400, detail="Missing 'input' field.")
    return empty_state(tenant_id, user_id, thread_id, req.input, agent_type)


def _get_thread_or_404(thread_id: str, tenant_id: str, db: Session) -> DBAgentThread:
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
    return thread


def _save_checkpoint(db: Session, thread_id: str, step: str, state: dict) -> str:
    checkpoint_id = f"cp_{uuid.uuid4().hex[:8]}"
    db.add(DBAgentCheckpoint(
        thread_id=thread_id,
        checkpoint_id=checkpoint_id,
        timestamp=datetime.utcnow(),
        step=step,
        state_data=state,
    ))
    db.commit()
    return checkpoint_id


if _HAS_LANGFUSE:
    @observe(name="agent_run")
    def _execute_agent_run(state_to_run: dict, config: dict, tenant_id: str, user_id: str, thread_id: str, agent_type: str) -> dict:
        res = get_graph().invoke(state_to_run, config=config)
        return res


# -------------------------------------------------------------------------
# POST /threads/{thread_id}/runs  — synchronous
# -------------------------------------------------------------------------
@router.post("/threads/{thread_id}/runs")
def run_thread(
    thread_id: str,
    req:       ThreadRun,
    principal: Dict[str, Any] = Depends(get_principal),
    db:        Session        = Depends(_db_dep),
):
    tenant_id = principal["tenant_id"]
    user_id   = principal["id"]

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

    thread = _get_thread_or_404(thread_id, tenant_id, db)

    last_cp = (
        db.query(DBAgentCheckpoint)
        .filter(DBAgentCheckpoint.thread_id == thread_id)
        .order_by(DBAgentCheckpoint.timestamp.desc())
        .first()
    )
    if not last_cp:
        raise HTTPException(status_code=500, detail="Checkpoint history missing")

    if req.approve_action:
        approval_chain = last_cp.state_data.get("approval_chain", [])
        if not any(role in principal["roles"] for role in approval_chain):
            raise HTTPException(status_code=403, detail="Forbidden: You lack the required role to approve this HITL action.")

    state_to_run = _resolve_state(req, last_cp.state_data, tenant_id, user_id, thread_id, thread.agent_type)

    # Inject principal into LangGraph config so AGT shield node can map identity
    config       = {"configurable": {"thread_id": f"{tenant_id}:{thread_id}", "principal": principal}}
    if _HAS_LANGFUSE:
        with propagate_attributes(user_id=user_id, session_id=thread_id, metadata={"tenant_id": tenant_id}):
            final_state = _execute_agent_run(state_to_run, config, tenant_id, user_id, thread_id, thread.agent_type)
        _flush_langfuse()
    else:
        final_state = get_graph().invoke(state_to_run, config=config)

    status = "completed"
    if final_state.get("pending_action") is not None:
        status = "action_required"

    checkpoint_id = _save_checkpoint(db, thread_id, "run_completion", dict(final_state))

    return {
        "status": status,
        "output": {
            "response":         final_state["output"],
            "steps_executed":   final_state["steps"],
            "pending_action":   final_state.get("pending_action"),
            "risk_score":       final_state.get("action_risk_score"),
            "approval_chain":   final_state.get("approval_chain"),
            "approval_timeout": final_state.get("approval_timeout_at"),
            "audit_hmac":       final_state.get("audit_hmac"),
        },
        "checkpoint_id": checkpoint_id,
    }


# -------------------------------------------------------------------------
# POST /threads/{thread_id}/runs/stream  — SSE streaming
# -------------------------------------------------------------------------
@router.post("/threads/{thread_id}/runs/stream")
async def stream_thread(
    thread_id: str,
    req:       ThreadRun,
    principal: Dict[str, Any] = Depends(get_principal),
    db:        Session        = Depends(_db_dep),
):
    tenant_id = principal["tenant_id"]
    user_id   = principal["id"]

    if not DATABASE_URL.startswith("sqlite"):
        db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

    thread = _get_thread_or_404(thread_id, tenant_id, db)

    last_cp = (
        db.query(DBAgentCheckpoint)
        .filter(DBAgentCheckpoint.thread_id == thread_id)
        .order_by(DBAgentCheckpoint.timestamp.desc())
        .first()
    )
    if not last_cp:
        raise HTTPException(status_code=500, detail="Checkpoint history missing")

    if req.approve_action:
        approval_chain = last_cp.state_data.get("approval_chain", [])
        if not any(role in principal["roles"] for role in approval_chain):
            raise HTTPException(status_code=403, detail="Forbidden: You lack the required role to approve this HITL action.")

    state_to_run = _resolve_state(req, last_cp.state_data, tenant_id, user_id, thread_id, thread.agent_type)

    async def event_generator() -> AsyncGenerator[str, None]:
        def sse(payload: Dict) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        yield sse({"event": "step", "step": "guardrail_check", "status": "running"})
        await asyncio.sleep(0)

        loop = asyncio.get_event_loop()
        config = {"configurable": {"thread_id": f"{tenant_id}:{thread_id}", "principal": principal}}
        try:
            if _HAS_LANGFUSE:
                def _run_with_attrs():
                    with propagate_attributes(user_id=user_id, session_id=thread_id, metadata={"tenant_id": tenant_id}):
                        return _execute_agent_run(state_to_run, config, tenant_id, user_id, thread_id, thread.agent_type)
                intermediate_state = await loop.run_in_executor(None, _run_with_attrs)
                _flush_langfuse()
            else:
                intermediate_state = await loop.run_in_executor(
                    None, lambda: get_graph().invoke(state_to_run, config=config)
                )
        except Exception as exc:
            yield sse({"event": "error", "detail": str(exc)})
            return

        for step in intermediate_state.get("steps", []):
            yield sse({"event": "step", "step": step, "status": "ok"})

        if intermediate_state.get("pending_action"):
            yield sse({
                "event":          "hitl_required",
                "pending_action": intermediate_state["pending_action"],
                "risk_score":     intermediate_state.get("action_risk_score"),
                "approval_chain": intermediate_state.get("approval_chain"),
                "timeout_at":     intermediate_state.get("approval_timeout_at"),
                "audit_hmac":     intermediate_state.get("audit_hmac"),
            })
            cp_id = _save_checkpoint(
                db, thread_id, "stream_hitl_interrupt", dict(intermediate_state)
            )
            yield sse({"event": "done", "status": "action_required", "checkpoint_id": cp_id})
            return

        # ── Stream generation tokens from LiteLLM ──────────────────────────────
        if intermediate_state.get("is_safe") and not intermediate_state.get("output"):
            yield sse({"event": "step", "step": "generation_streaming", "status": "running"})

            messages = [
                {"role": "system", "content": f"You are an enterprise AI assistant for tenant '{tenant_id}'."},
                {"role": "user",   "content": state_to_run["input"]},
            ]
            full_output = ""
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST",
                        f"{LLM_GATEWAY_URL}/chat/completions",
                        json={
                            "model": LLM_MODEL, "messages": messages,
                            "stream": True, "temperature": 0.7,
                            "user": user_id,
                            "metadata": {"tenant_id": tenant_id, "thread_id": thread_id},
                        },
                        timeout=60.0,
                    ) as llm_stream:
                        async for raw_line in llm_stream.aiter_lines():
                            if raw_line.startswith("data: "):
                                chunk_str = raw_line[6:]
                                if chunk_str.strip() == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(chunk_str)
                                    delta = chunk["choices"][0]["delta"].get("content", "")
                                    if delta:
                                        full_output += delta
                                        yield sse({"event": "token", "token": delta})
                                except Exception:
                                    pass
                intermediate_state["output"] = full_output
            except Exception as exc:
                fallback = intermediate_state.get("output") or f"[LLM unavailable] Tenant '{tenant_id}'."
                intermediate_state["output"] = fallback
                yield sse({"event": "token", "token": fallback})
        else:
            yield sse({"event": "token", "token": intermediate_state.get("output", "")})

        cp_id = _save_checkpoint(db, thread_id, "stream_completion", dict(intermediate_state))
        yield sse({"event": "done", "status": "completed", "checkpoint_id": cp_id})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
