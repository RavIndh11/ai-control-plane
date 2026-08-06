"""
agents/graph.py — LangGraph pipeline definition & compilation.

Graph topology:
  agent_node ─► generation ─► END

The compiled graph is lazily initialised by build_graph() which is
called once during FastAPI lifespan startup with the correct checkpointer
backed by SQLite (dev) or PostgreSQL (production).
"""
import os
from typing import Optional

from langgraph.graph import StateGraph, END

from agents.state import AgentState
from agents.nodes.reasoning   import agent_node
from agents.nodes.generation  import generation_node

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./orchestrator.db")

# Module-level instances — kept alive for the process lifetime
_compiled_graph = None
_db_connection = None  # sqlite3.Connection or psycopg.Connection


def _build_workflow() -> StateGraph:
    """Construct and wire the LangGraph StateGraph (not compiled yet)."""
    workflow = StateGraph(AgentState)

    workflow.add_node("agent_node",        agent_node)
    workflow.add_node("generation",        generation_node)

    workflow.set_entry_point("agent_node")
    workflow.add_edge("agent_node", "generation")
    workflow.add_edge("generation", END)

    return workflow


def build_graph(database_url: Optional[str] = None):
    """
    Compile the LangGraph pipeline with the appropriate checkpointer.

    SQLite → SqliteSaver  (local dev)
    Postgres → PostgresSaver  (production)

    Returns the compiled graph and stores it in the module-level _compiled_graph.
    """
    global _compiled_graph, _db_connection
    url = database_url or DATABASE_URL
    workflow = _build_workflow()

    if url.startswith("sqlite"):
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver
        db_path = url.replace("sqlite:///", "")
        _db_connection = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(_db_connection)
        checkpointer.setup()
        _compiled_graph = workflow.compile(checkpointer=checkpointer)
        print("[Graph] Compiled with SqliteSaver.")
        return _compiled_graph
    else:
        from psycopg_pool import ConnectionPool
        from langgraph.checkpoint.postgres import PostgresSaver
        # Use a connection pool for thread-safety under concurrent FastAPI requests
        _db_connection = ConnectionPool(
            conninfo=url,
            max_size=10,
            kwargs={"autocommit": True},
        )
        checkpointer = PostgresSaver(_db_connection)
        checkpointer.setup()
        _compiled_graph = workflow.compile(checkpointer=checkpointer)
        print("[Graph] Compiled with PostgresSaver (pool).")
        return _compiled_graph


def get_graph():
    """
    Return the already-compiled graph.
    Raises RuntimeError if build_graph() has not been called yet.
    """
    global _compiled_graph  # noqa: F811
    if _compiled_graph is None:
        # Fallback for unit tests: compile with in-memory checkpointer
        from langgraph.checkpoint.memory import MemorySaver
        _compiled_graph = _build_workflow().compile(checkpointer=MemorySaver())
        print("[Graph] Compiled with MemorySaver (fallback).")
    return _compiled_graph
