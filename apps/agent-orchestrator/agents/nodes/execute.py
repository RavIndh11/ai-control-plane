import os
import asyncio
from agents.state import AgentState
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

NAMESPACE = os.getenv("NAMESPACE", "default")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", f"http://mcp-server.{NAMESPACE}.svc.cluster.local:8002")

def execute_node(state: AgentState) -> AgentState:
    """Executes the pending MCP tool call and stores the result."""
    action = state.get("pending_action")
    if not action:
        return state

    tool_name = action.get("tool")
    tool_args = action.get("arguments", {})

    async def call_mcp_tool():
        async with sse_client(f"{MCP_SERVER_URL}/sse") as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=tool_args)
                if result.content:
                    return result.content[0].text
                return "Tool executed successfully with no text output."

    def run_in_new_loop():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(call_mcp_tool())
        finally:
            new_loop.close()

    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            tool_result = pool.submit(run_in_new_loop).result()
        
        state["output"] = tool_result
    finally:
        state["pending_action"] = None
    
    return state
