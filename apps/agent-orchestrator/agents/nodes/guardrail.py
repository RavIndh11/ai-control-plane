"""
agents/nodes/guardrail.py — Guardrail LangGraph node.

Evaluation order:
  1. NeMo Guardrails service (if configured)
  2. DB compliance rules engine
  3. Static fallback patterns

On violation: pushes GRC evidence to the Governance Engine and
              sets state['is_safe'] = False so the graph ends early.
"""
import os
from typing import Any, Dict, List, Tuple

import httpx
from sqlalchemy import text

from agents.state import AgentState

NEMO_GUARDRAILS_URL: str = os.getenv("NEMO_GUARDRAILS_URL", "")
GOV_URL: str             = os.getenv("GOVERNANCE_ENGINE_URL", "http://localhost:8000")

_STATIC_PATTERNS: List[Tuple[str, str]] = [
    ("select * from",                "SOC2-CC-6.1"),
    ("drop table",                   "SOC2-CC-6.1"),
    ("admin bypass",                 "SOC2-CC-6.1"),
    ("ignore previous instructions", "EU-AI-Act-Art-9"),
    ("disregard your",               "EU-AI-Act-Art-9"),
    ("repeat after me",              "EU-AI-Act-Art-9"),
    ("; rm -rf",                     "GDPR-Art-32"),
]

# Optional Langfuse tracing
try:
    from langfuse.decorators import observe, langfuse_context
    _HAS_LANGFUSE = True
except ImportError:
    _HAS_LANGFUSE = False

    def observe(name: str = ""):  # type: ignore[misc]
        """No-op decorator when Langfuse is not installed."""
        def decorator(fn):
            return fn
        return decorator

    class langfuse_context:  # type: ignore[no-redef]
        @staticmethod
        def update_current_observation(**_: Any) -> None:
            pass


def _load_db_patterns(tenant_id: str) -> List[Tuple[str, str]]:
    """Fetch active compliance rule patterns from the DB."""
    # Import here to avoid circular imports at module load time
    from db.session import DATABASE_URL, SessionLocal

    db = SessionLocal()
    patterns: List[Tuple[str, str]] = []
    try:
        if not DATABASE_URL.startswith("sqlite"):
            schema = f"tenant_{tenant_id.replace('-', '_')}"
            db.execute(text(f"SET search_path TO {schema}, public;"))

        table_exists: bool = True
        if not DATABASE_URL.startswith("sqlite"):
            table_exists = bool(
                db.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = :schema
                            AND   table_name   = 'compliance_rules'
                        )
                    """),
                    {"schema": f"tenant_{tenant_id.replace('-', '_')}"},
                ).scalar()
            )

        if table_exists:
            rows = db.execute(
                text("SELECT pattern, control_id FROM compliance_rules WHERE is_active = TRUE")
            ).fetchall()
            patterns = [(r[0], r[1]) for r in rows]
    except Exception as exc:
        print(f"[Guardrail] DB rules lookup failed ({exc}). Using static patterns.")
    finally:
        db.close()

    return patterns or _STATIC_PATTERNS


def _check_nemo(user_input: str) -> Tuple[bool, str]:
    """
    Call NeMo Guardrails and parse the refusal heuristic.
    Returns (is_safe, reason).
    """
    try:
        with httpx.Client(timeout=5.0) as client:
            res = client.post(
                f"{NEMO_GUARDRAILS_URL}/v1/chat/completions",
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": user_input}],
                },
            )
            if res.status_code == 200:
                reply: str = res.json()["choices"][0]["message"]["content"]
                refusal_phrases = [
                    "i cannot", "i'm sorry", "i can't",
                    "not allowed", "cannot execute", "security control",
                ]
                if any(p in reply.lower() for p in refusal_phrases):
                    return False, reply
    except Exception as exc:
        print(f"[Guardrail] NeMo unreachable ({exc}). Falling back to DB rules.")
    return True, ""


def _push_violation_evidence(state: AgentState, control_id: str, reason: str) -> None:
    """Fire-and-forget POST to the Governance Engine."""
    try:
        with httpx.Client(timeout=2.0) as client:
            client.post(
                f"{GOV_URL}/api/v1/evidence",
                headers={
                    "X-Tenant-ID": state["tenant_id"],
                    "X-User-Role": "system-workload",
                },
                json={
                    "control_id":        control_id,
                    "source_component":  "agent-orchestrator:guardrail_node",
                    "event_type":        "guardrail_violation",
                    "severity":          "high",
                    "payload": {
                        "input_query": state["input"],
                        "message":     reason,
                    },
                },
            )
    except Exception as exc:
        print(f"[Guardrail] Failed to push evidence: {exc}")


@observe(name="guardrail_node")
def guardrail_node(state: AgentState) -> AgentState:
    """
    LangGraph node — evaluate input against all guardrail layers.

    Sets state['is_safe'] = False and state['output'] = violation message
    if the input should be blocked.
    """
    user_input  = state["input"]
    tenant_id   = state["tenant_id"]
    state["steps"] = list(state.get("steps", [])) + ["guardrail_check"]

    langfuse_context.update_current_observation(
        input={"prompt": user_input, "tenant_id": tenant_id},
        metadata={"node": "guardrail"},
    )

    is_safe         = True
    violation_reason = ""
    control_violated = "SOC2-CC-6.1"

    # Layer 1: NeMo Guardrails (if configured)
    if NEMO_GUARDRAILS_URL:
        is_safe, violation_reason = _check_nemo(user_input)

    # Layer 2: DB + static pattern rules
    if is_safe:
        patterns = _load_db_patterns(tenant_id)
        lower = user_input.lower()
        for pattern, ctrl_id in patterns:
            if pattern in lower:
                is_safe          = False
                violation_reason = (
                    f"Policy violation: input matches blocked pattern '{pattern}'."
                )
                control_violated = ctrl_id
                break

    langfuse_context.update_current_observation(
        output={"is_safe": is_safe, "violation_reason": violation_reason},
        level="WARNING" if not is_safe else "DEFAULT",
    )

    if not is_safe:
        state["is_safe"] = False
        state["output"]  = violation_reason or "Policy violation detected."
        _push_violation_evidence(state, control_violated, violation_reason)

    return state
