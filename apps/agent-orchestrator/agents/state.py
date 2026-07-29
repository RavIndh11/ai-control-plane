"""
agents/state.py — Canonical AgentState TypedDict.

Phase 1 adds risk / AGT governance fields to the original schema:
  action_risk_score   — 0.0 to 1.0 risk score computed by governance_shield
  approval_chain      — ordered list of roles that must approve a HITL action
  approval_timeout_at — ISO datetime string; action auto-rejects after this
  break_glass_used    — True if super-admin bypassed normal approval flow
  audit_hmac          — HMAC-SHA256 hex of this state slice for tamper detection

All new fields are Optional so existing checkpoints remain compatible.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict):
    # ── Core execution ───────────────────────────────────────────────────────
    input:    str
    output:   str
    steps:    List[str]
    is_safe:  bool

    # ── Identity ─────────────────────────────────────────────────────────────
    tenant_id: str
    user_id:   str
    thread_id: str
    agent_type: str

    # ── AGT / Governance fields (Phase 1 additions) ──────────────────────────
    pending_action:      Optional[Dict[str, Any]]   # tool + args awaiting HITL
    action_approved:     Optional[bool]             # None=pending, True, False
    action_risk_score:   Optional[float]            # 0.0–1.0
    approval_chain:      Optional[List[str]]        # e.g. ["tenant-admin"]
    approval_timeout_at: Optional[str]              # ISO-8601 datetime string
    break_glass_used:    Optional[bool]
    audit_hmac:          Optional[str]              # HMAC-SHA256 hex


def empty_state(tenant_id: str, user_id: str, thread_id: str, input_text: str, agent_type: str = "compliance-agent") -> AgentState:
    """Return a freshly-initialised AgentState for a new run."""
    return AgentState(
        input=input_text,
        output="",
        steps=[],
        is_safe=True,
        tenant_id=tenant_id,
        user_id=user_id,
        thread_id=thread_id,
        agent_type=agent_type,
        pending_action=None,
        action_approved=None,
        action_risk_score=None,
        approval_chain=None,
        approval_timeout_at=None,
        break_glass_used=None,
        audit_hmac=None,
    )
