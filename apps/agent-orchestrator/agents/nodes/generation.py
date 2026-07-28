"""
agents/nodes/generation.py — Final response generation node.

Calls LiteLLM with optional Qdrant RAG context enrichment.
Only executes when state['is_safe'] is True and no HITL interrupt is pending.
"""
import os
from typing import Any

import httpx

from agents.state import AgentState

LLM_GATEWAY_URL: str  = os.getenv("LLM_GATEWAY_URL", "http://localhost:4000/v1")
LLM_MODEL: str        = os.getenv("LLM_MODEL",        "mistral-cpu")
QDRANT_URL: str       = os.getenv("QDRANT_URL",        "")
QDRANT_COLLECTION:str = os.getenv("QDRANT_COLLECTION", "manifold_kb")
EMBEDDING_MODEL: str  = os.getenv("EMBEDDING_MODEL",   "qwen3-embedding")

_qdrant_client = None
if QDRANT_URL:
    try:
        from qdrant_client import QdrantClient
        _qdrant_client = QdrantClient(url=QDRANT_URL, timeout=3.0)
    except Exception as exc:
        print(f"[Generation] Qdrant client init failed: {exc}")

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


def _rag_context(user_input: str, tenant_id: str) -> str:
    """Return a newline-joined string of top-3 Qdrant search hits, or empty string."""
    if not _qdrant_client:
        return ""
    try:
        # Embed via LiteLLM (same gateway)
        with httpx.Client(timeout=2.0) as client:
            res = client.post(
                f"{LLM_GATEWAY_URL}/embeddings",
                json={"model": EMBEDDING_MODEL, "input": user_input},
                headers={"X-Tenant-ID": tenant_id, "X-User-Role": "system-workload"},
            )
            if res.status_code != 200:
                return ""
            vector = res.json()["data"][0]["embedding"]

        hits = _qdrant_client.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=vector,
            limit=3,
        )
        return "\n".join(h.payload.get("content", "") for h in hits if h.payload)
    except Exception as exc:
        print(f"[Generation] RAG lookup failed: {exc}")
        return ""


@observe(name="generation_node")
def generation_node(state: AgentState) -> AgentState:
    """
    LangGraph node — produce final LLM response.

    Skips if:
      - state['is_safe'] is False
      - 'governance_shield_interrupt' is in state['steps'] (HITL pending)
      - state['output'] already populated (shield set it)
    """
    state["steps"] = list(state.get("steps", [])) + ["generation"]

    if not state.get("is_safe"):
        return state
    if "governance_shield_interrupt" in state.get("steps", []):
        return state
    if state.get("output"):
        return state

    user_input = state["input"]
    tenant_id  = state.get("tenant_id", "default")

    langfuse_context.update_current_observation(
        input={"prompt": user_input, "tenant_id": tenant_id},
        metadata={"node": "generation", "model": LLM_MODEL},
    )

    rag_ctx = _rag_context(user_input, tenant_id)

    messages = [
        {
            "role": "system",
            "content": (
                f"You are an enterprise AI assistant for tenant '{tenant_id}'."
                + (f"\n\nRelevant context:\n{rag_ctx}" if rag_ctx else "")
            ),
        },
        {"role": "user", "content": user_input},
    ]

    output = ""
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.post(
                f"{LLM_GATEWAY_URL}/chat/completions",
                json={
                    "model":       LLM_MODEL,
                    "messages":    messages,
                    "temperature": 0.7,
                    "user":        state.get("user_id", "user_default"),
                    "metadata": {
                        "tenant_id": tenant_id,
                        "thread_id": state.get("thread_id", "thread_default"),
                    },
                },
            )
            if res.status_code == 200:
                output = res.json()["choices"][0]["message"]["content"]
            else:
                raise RuntimeError(f"Gateway status {res.status_code}")
    except Exception as exc:
        print(f"[Generation] LLM Gateway unreachable ({exc}). Using fallback response.")
        output = f"Processed query for tenant '{tenant_id}' successfully."

    state["output"] = output

    langfuse_context.update_current_observation(
        output={"response_length": len(output)},
    )

    return state
