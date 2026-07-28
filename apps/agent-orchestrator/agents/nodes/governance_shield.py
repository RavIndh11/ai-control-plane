"""
agents/nodes/governance_shield.py — Microsoft AGT-aligned governance shield node.

Phase 1 enhancements over the original:
  - Reads action_risk_score from state (set by reasoning node)
  - Computes approval_chain based on risk tier
  - Sets approval_timeout_at (30 min for high-risk, 4 h for critical)
  - Computes audit_hmac over the action payload for tamper-evidence
  - Supports break_glass_used flag (super-admin fast-path)

HITL tier thresholds
  risk < 0.3   → auto-approve  (no interrupt)
  risk < 0.7   → tenant-admin approval required
  risk >= 0.7  → tenant-admin + compliance-auditor approval required
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from typing import Any, List, Optional

import httpx

from agents.state import AgentState

GOV_URL: str        = os.getenv("GOVERNANCE_ENGINE_URL", "http://localhost:8000")
_HMAC_SECRET: bytes = os.getenv("AUDIT_HMAC_SECRET", "change-me-in-production").encode()

# Risk tier thresholds
_AUTO_APPROVE_THRESHOLD = 0.30
_ADMIN_THRESHOLD        = 0.70   # below this: tenant-admin only
# above _ADMIN_THRESHOLD: tenant-admin + compliance-auditor

# Optional Langfuse tracing
try:
    from langfuse.decorators import observe, langfuse_context
except ImportError:
    def observe(name: str = ""):  # type: ignore[misc]
        def decorator(fn): return fn
        return decorator
    class langfuse_context:  # type: ignore[no-redef]
        @staticmethod
        def update_current_observation(**_: Any) -> None: pass


def _compute_hmac(payload: dict) -> str:
    """Compute HMAC-SHA256 over a JSON-serialised action payload."""
    data = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(_HMAC_SECRET, data, hashlib.sha256).hexdigest()


def _risk_to_approval_chain(risk_score: float) -> List[str]:
    if risk_score < _AUTO_APPROVE_THRESHOLD:
        return []
    if risk_score < _ADMIN_THRESHOLD:
        return ["tenant-admin"]
    return ["tenant-admin", "compliance-auditor"]


def _risk_to_timeout(risk_score: float) -> str:
    """Return ISO-8601 datetime at which the action auto-rejects."""
    delta = timedelta(hours=4) if risk_score >= _ADMIN_THRESHOLD else timedelta(minutes=30)
    return (datetime.utcnow() + delta).isoformat()


def _push_intercept_evidence(
    state: AgentState,
    pending_action: dict,
    risk_score: float,
    approval_chain: List[str],
) -> None:
    """Push HITL interception event to the Governance Engine."""
    try:
        with httpx.Client(timeout=2.0) as client:
            client.post(
                f"{GOV_URL}/api/v1/evidence",
                headers={
                    "X-Tenant-ID": state["tenant_id"],
                    "X-User-Role": "system-workload",
                },
                json={
                    "control_id":       "EU-AI-Act-Art-9",
                    "source_component": "agent-orchestrator:governance_shield",
                    "event_type":       "agent_action_intercepted",
                    "severity":         "high" if risk_score >= 0.7 else "medium",
                    "payload": {
                        "requested_tool":  pending_action["tool"],
                        "arguments":       pending_action["arguments"],
                        "risk_score":      risk_score,
                        "approval_chain":  approval_chain,
                        "message": (
                            "High-risk tool call intercepted. "
                            "Pausing graph execution for HITL approval."
                        ),
                        "audit_hmac":      state.get("audit_hmac"),
                    },
                },
            )
    except Exception as exc:
        print(f"[GovernanceShield] Failed to push intercept evidence: {exc}")


def _push_resolution_evidence(
    state: AgentState,
    approved: bool,
    break_glass: bool,
) -> None:
    """Push approval / rejection event to the Governance Engine."""
    try:
        with httpx.Client(timeout=2.0) as client:
            client.post(
                f"{GOV_URL}/api/v1/evidence",
                headers={
                    "X-Tenant-ID": state["tenant_id"],
                    "X-User-Role": "system-workload",
                },
                json={
                    "control_id":       "EU-AI-Act-Art-9",
                    "source_component": "agent-orchestrator:governance_shield",
                    "event_type":       "hitl_resolution",
                    "severity":         "info",
                    "payload": {
                        "tool":         (state.get("pending_action") or {}).get("tool"),
                        "approved":     approved,
                        "break_glass":  break_glass,
                        "audit_hmac":   state.get("audit_hmac"),
                        "resolved_by":  state.get("user_id"),
                    },
                },
            )
    except Exception as exc:
        print(f"[GovernanceShield] Failed to push resolution evidence: {exc}")


@observe(name="governance_shield_node")
def governance_shield_node(state: AgentState) -> AgentState:
    """
    LangGraph node — AGT governance shield.

    Behaviour:
      - If no pending_action: pass-through.
      - If risk < auto-approve threshold: auto-approve and continue.
      - If action_approved is None: compute chain/timeout/hmac, interrupt graph.
      - If action_approved is True/False: push resolution evidence, clear action.
    """
    state["steps"] = list(state.get("steps", [])) + ["governance_shield"]

    if not state.get("is_safe"):
        return state

    pending_action: Optional[dict] = state.get("pending_action")
    if not pending_action:
        return state  # Nothing to govern

    action_approved:  Optional[bool]  = state.get("action_approved")
    risk_score:       float           = state.get("action_risk_score") or 0.50
    break_glass:      bool            = bool(state.get("break_glass_used"))
    approval_chain:   List[str]       = _risk_to_approval_chain(risk_score)

    langfuse_context.update_current_observation(
        input={
            "tool":          pending_action.get("tool"),
            "risk_score":    risk_score,
            "approval_chain": approval_chain,
        },
        metadata={"node": "governance_shield"},
    )

    # ── Auto-approve: risk below threshold ────────────────────────────────
    if not approval_chain:
        print(
            f"[GovernanceShield] Auto-approved '{pending_action['tool']}' "
            f"(risk={risk_score:.2f} < {_AUTO_APPROVE_THRESHOLD})"
        )
        state["action_approved"]  = True
        state["approval_chain"]   = []
        state["steps"].append("governance_shield_auto_approved")
        state["pending_action"]   = None
        return state

    # ── First encounter: set up HITL interrupt ─────────────────────────────
    if action_approved is None and not break_glass:
        # Compute HMAC over the action for tamper-evidence
        hmac_payload = {
            "tool":      pending_action["tool"],
            "arguments": pending_action["arguments"],
            "tenant_id": state["tenant_id"],
            "user_id":   state["user_id"],
            "thread_id": state["thread_id"],
        }
        state["audit_hmac"]          = _compute_hmac(hmac_payload)
        state["approval_chain"]      = approval_chain
        state["approval_timeout_at"] = _risk_to_timeout(risk_score)

        _push_intercept_evidence(state, pending_action, risk_score, approval_chain)

        state["steps"].append("governance_shield_interrupt")
        print(
            f"[GovernanceShield] HITL interrupt for '{pending_action['tool']}' "
            f"(risk={risk_score:.2f}). Chain: {approval_chain}. "
            f"Timeout: {state['approval_timeout_at']}"
        )
        return state  # LangGraph will checkpoint here

    # ── Break-glass: super-admin fast-path (still audited) ─────────────────
    if break_glass and action_approved is None:
        print(
            f"[GovernanceShield] Break-glass used by {state.get('user_id')} "
            f"for '{pending_action['tool']}'. Forcing approval with mandatory audit."
        )
        state["action_approved"] = True
        _push_resolution_evidence(state, approved=True, break_glass=True)
        state["steps"].append("governance_shield_break_glass")
        state["pending_action"]  = None
        return state

    # ── Resolution: admin approved or rejected ──────────────────────────────
    if action_approved is False:
        tool_name = pending_action["tool"]
        state["output"] = (
            f"Action blocked: Execution of '{tool_name}' was rejected "
            f"by the compliance approver."
        )
        state["pending_action"] = None
        state["steps"].append("governance_shield_rejected")
        _push_resolution_evidence(state, approved=False, break_glass=False)
        print(f"[GovernanceShield] Tool '{tool_name}' rejected.")

    elif action_approved is True:
        tool_name = pending_action["tool"]
        state["output"] = f"Action approved: '{tool_name}' cleared for execution."
        state["pending_action"] = None
        state["steps"].append("governance_shield_approved")
        _push_resolution_evidence(state, approved=True, break_glass=False)
        print(f"[GovernanceShield] Tool '{tool_name}' approved.")

    langfuse_context.update_current_observation(
        output={
            "action_approved":  state.get("action_approved"),
            "break_glass_used": break_glass,
            "steps":            state["steps"],
        },
    )

    return state
