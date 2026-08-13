import os
import asyncio
from agents.state import AgentState
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server.default.svc.cluster.local:8002")

def execute_node(state: AgentState) -> AgentState:
    """Executes the pending MCP tool call and stores the result."""
    action = state.get("pending_action")
    if not action:
        return state

    tool_name = action.get("tool")
    tool_args = action.get("arguments", {})

    async def call_mcp_tool():
        try:
            async with sse_client(f"{MCP_SERVER_URL}/sse") as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=tool_args)
                    if result.content:
                        return result.content[0].text
                    return "Tool executed successfully with no text output."
        except Exception as e:
            return f"Error executing tool: {e}"

    # Safely run the async code in a new event loop to avoid RuntimeError in FastAPI
    try:
        loop = asyncio.get_running_loop()
        # If an event loop is running, we must run it in a separate thread to avoid crashing
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            tool_result = pool.submit(lambda: asyncio.run(call_mcp_tool())).result()
    except RuntimeError:
        # No running event loop, safe to run directly
        tool_result = asyncio.run(call_mcp_tool())
    
    state["output"] = tool_result
    state["pending_action"] = None
    
    return state
