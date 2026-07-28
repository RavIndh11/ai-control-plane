"""
agents/graph.py — LangGraph pipeline definition & compilation.

Graph topology:
  guardrail ─┬─(safe)────► agent_node ─► governance_shield ─┬─(no interrupt)─► generation ─► END
            └─(unsafe)─► END                                        └─(interrupt)─► END

The compiled graph is lazily initialised by build_graph() which is
called once during FastAPI lifespan startup with the correct checkpointer
backed by SQLite (dev) or PostgreSQL (production).
"""
import os
from typing import Optional

from langgraph.graph import StateGraph, END

from agents.state import AgentState
from agents.nodes.guardrail   import guardrail_node
from agents.nodes.reasoning   import agent_node
from agents.nodes.governance_shield import governance_shield_node
from agents.nodes.generation  import generation_node

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./orchestrator.db")

# Module-level graph instance (set by build_graph at startup)
_compiled_graph = None


def _route_after_guardrail(state: AgentState) -> str:
    return END if not state["is_safe"] else "agent_node"


def _route_after_shield(state: AgentState) -> str:
    return END if "governance_shield_interrupt" in state.get("steps", []) else "generation"


def _build_workflow() -> StateGraph:
    """Construct and wire the LangGraph StateGraph (not compiled yet)."""
    workflow = StateGraph(AgentState)

    workflow.add_node("guardrail",         guardrail_node)
    workflow.add_node("agent_node",        agent_node)
    workflow.add_node("governance_shield", governance_shield_node)
    workflow.add_node("generation",        generation_node)

    workflow.set_entry_point("guardrail")
    workflow.add_conditional_edges(
        "guardrail",
        _route_after_guardrail,
        {"agent_node": "agent_node", END: END},
    )
    workflow.add_edge("agent_node", "governance_shield")
    workflow.add_conditional_edges(
        "governance_shield",
        _route_after_shield,
        {"generation": "generation", END: END},
    )
    workflow.add_edge("generation", END)

    return workflow


def build_graph(database_url: Optional[str] = None):
    """
    Compile the LangGraph pipeline with the appropriate checkpointer.

    SQLite → SqliteSaver  (local dev)
    Postgres → PostgresSaver  (production)

    Returns the compiled graph and stores it in the module-level _compiled_graph.
    """
    global _compiled_graph
    url = database_url or DATABASE_URL
    workflow = _build_workflow()

    if url.startswith("sqlite"):
        from langgraph.checkpoint.sqlite import SqliteSaver
        db_path = url.replace("sqlite:///", "")
        with SqliteSaver.from_conn_string(db_path) as checkpointer:
            checkpointer.setup()
            _compiled_graph = workflow.compile(checkpointer=checkpointer)
            print("[Graph] Compiled with SqliteSaver.")
            return _compiled_graph
    else:
        from langgraph.checkpoint.postgres import PostgresSaver
        with PostgresSaver.from_conn_string(url) as checkpointer:
            checkpointer.setup()
            _compiled_graph = workflow.compile(checkpointer=checkpointer)
            print("[Graph] Compiled with PostgresSaver.")
            return _compiled_graph


def get_graph():
    """
    Return the already-compiled graph.
    Raises RuntimeError if build_graph() has not been called yet.
    """
    if _compiled_graph is None:
        # Fallback for unit tests: compile with in-memory checkpointer
        from langgraph.checkpoint.memory import MemorySaver
        global _compiled_graph  # noqa: F811
        _compiled_graph = _build_workflow().compile(checkpointer=MemorySaver())
        print("[Graph] Compiled with MemorySaver (fallback).")
    return _compiled_graph
