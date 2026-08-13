import os
import asyncio
from agents.state import AgentState
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server.control-plane.svc.cluster.local:8002")

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

    tool_result = asyncio.run(call_mcp_tool())
    
    # Store the result so generation_node or agent_node can use it
    state["output"] = tool_result
    state["pending_action"] = None
    
    return state
