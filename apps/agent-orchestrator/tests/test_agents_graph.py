import pytest
from unittest.mock import patch, MagicMock

import agents.graph as graph_module
from agents.graph import build_graph, get_graph, _route_after_agent, _route_after_shield

@pytest.fixture(autouse=True)
def reset_graph():
    graph_module._compiled_graph = None
    graph_module._db_connection = None
    yield
    graph_module._compiled_graph = None
    graph_module._db_connection = None

def test_route_after_agent():
    assert _route_after_agent({"pending_action": True}) == "governance_shield"
    assert _route_after_agent({"pending_action": None}) == "generation"
    assert _route_after_agent({}) == "generation"

def test_route_after_shield():
    assert _route_after_shield({"action_approved": True}) == "execute"
    assert _route_after_shield({"action_approved": None, "pending_action": None}) == "generation"
    assert _route_after_shield({"action_approved": None, "pending_action": True, "steps": ["governance_shield_interrupt"]}) == "generation"
    assert _route_after_shield({"action_approved": None, "pending_action": True, "steps": []}) == "execute"

def test_build_graph_sqlite():
    with patch("sqlite3.connect") as mock_connect, \
         patch("langgraph.checkpoint.sqlite.SqliteSaver") as mock_saver, \
         patch("agents.graph._build_workflow") as mock_build_workflow:
        
        mock_workflow = MagicMock()
        mock_build_workflow.return_value = mock_workflow
        
        graph = build_graph("sqlite:///./test.db")
        
        assert graph is not None
        mock_connect.assert_called_once_with("./test.db", check_same_thread=False)
        mock_saver.return_value.setup.assert_called_once()
        mock_workflow.compile.assert_called_once()

def test_build_graph_postgres():
    with patch("psycopg_pool.ConnectionPool") as mock_pool, \
         patch("langgraph.checkpoint.postgres.PostgresSaver") as mock_saver, \
         patch("agents.graph._build_workflow") as mock_build_workflow:
        
        mock_workflow = MagicMock()
        mock_build_workflow.return_value = mock_workflow
        
        graph = build_graph("postgresql://user:pass@host/db")
        
        assert graph is not None
        mock_pool.assert_called_once()
        mock_saver.return_value.setup.assert_called_once()
        mock_workflow.compile.assert_called_once()

def test_get_graph_fallback():
    # If not built, it uses MemorySaver
    with patch("agents.graph._build_workflow") as mock_build_workflow, \
         patch("langgraph.checkpoint.memory.MemorySaver") as mock_memory_saver:
        
        mock_workflow = MagicMock()
        mock_build_workflow.return_value = mock_workflow
        mock_workflow.compile.return_value = "compiled_memory_graph"
        
        graph = get_graph()
        assert graph == "compiled_memory_graph"
        
        # Second call uses cached
        graph2 = get_graph()
        assert graph2 == "compiled_memory_graph"
        assert mock_build_workflow.call_count == 1
