"""
agents/nodes/guardrail.py — Guardrail LangGraph node.

Evaluation order:
  1. Guardrails AI (Semantic similarity jailbreak detection via Qdrant)
  2. DB compliance rules engine
  3. Static fallback patterns

On violation: pushes GRC evidence to the Governance Engine and
              sets state['is_safe'] = False so the graph ends early.
"""
import os
from typing import Any, Dict, List, Tuple

import httpx
from sqlalchemy import text

try:
    from guardrails import Guard
    from guardrails.validators import Validator, register_validator, ValidationResult, Pass, Fail
    _HAS_GUARDRAILS = True
except ImportError:
    _HAS_GUARDRAILS = False

from agents.state import AgentState

GOV_URL: str             = os.getenv("GOVERNANCE_ENGINE_URL", "http://localhost:8000")
LLM_GATEWAY_URL: str     = os.getenv("LLM_GATEWAY_URL", "http://localhost:4000/v1")
EMBEDDING_MODEL: str     = os.getenv("EMBEDDING_MODEL", "qwen3-embedding")
QDRANT_URL: str          = os.getenv("QDRANT_URL", "")
QDRANT_JAILBREAK_COLLECTION = os.getenv("QDRANT_JAILBREAK_COLLECTION", "jailbreak_patterns")

_STATIC_PATTERNS: List[Tuple[str, str]] = [
    ("select * from",                "SOC2-CC-6.1"),
    ("drop table",                   "SOC2-CC-6.1"),
    ("admin bypass",                 "SOC2-CC-6.1"),
    ("ignore previous instructions", "EU-AI-Act-Art-9"),
    ("disregard your",               "EU-AI-Act-Art-9"),
    ("repeat after me",              "EU-AI-Act-Art-9"),
    ("; rm -rf",                     "GDPR-Art-32"),
]

_qdrant_client = None
if QDRANT_URL:
    try:
        from qdrant_client import QdrantClient
        _qdrant_client = QdrantClient(url=QDRANT_URL, timeout=3.0)
    except Exception as exc:
        print(f"[Guardrail] Qdrant client init failed: {exc}")

# Optional Langfuse tracing
try:
    from langfuse.decorators import observe, langfuse_context
    _HAS_LANGFUSE = True
except ImportError:
    _HAS_LANGFUSE = False

    def observe(name: str = ""):  # type: ignore[misc]
        def decorator(fn):
            return fn
        return decorator

    class langfuse_context:  # type: ignore[no-redef]
        @staticmethod
        def update_current_observation(**_: Any) -> None:
            pass

if _HAS_GUARDRAILS:
    @register_validator(name="qdrant_jailbreak_check", data_type="string")
    class QdrantJailbreakCheck(Validator):
        def validate(self, value: Any, metadata: Dict = {}) -> ValidationResult:
            if not _qdrant_client:
                return Pass()

            tenant_id = metadata.get("tenant_id", "default")
            
            try:
                with httpx.Client(timeout=2.0) as client:
                    res = client.post(
                        f"{LLM_GATEWAY_URL}/embeddings",
                        json={"model": EMBEDDING_MODEL, "input": value},
                        headers={"X-Tenant-ID": tenant_id, "X-User-Role": "system-workload"},
                    )
                    if res.status_code != 200:
                        return Pass()
                    vector = res.json()["data"][0]["embedding"]

                hits = _qdrant_client.search(
                    collection_name=QDRANT_JAILBREAK_COLLECTION,
                    query_vector=vector,
                    limit=1,
                )
                
                # If similarity score is very high (e.g., > 0.85), flag it
                if hits and hits[0].score > 0.85:
                    return Fail(error_message=f"Semantic similarity jailbreak detected (score: {hits[0].score:.2f})")
                    
            except Exception as exc:
                print(f"[Guardrail] Qdrant jailbreak check failed: {exc}")
                
            return Pass()

def _load_db_patterns(tenant_id: str) -> List[Tuple[str, str]]:
    """Fetch active compliance rule patterns from the DB."""
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

    # Layer 1: Guardrails AI (Qdrant semantic jailbreak detection)
    if _HAS_GUARDRAILS and _qdrant_client:
        guard = Guard().use(QdrantJailbreakCheck(), on_fail="exception")
        try:
            guard.validate(user_input, metadata={"tenant_id": tenant_id})
        except Exception as e:
            is_safe = False
            violation_reason = str(e)
            control_violated = "EU-AI-Act-Art-9"  # Jailbreak/manipulation control

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
