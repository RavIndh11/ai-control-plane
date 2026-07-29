import os
import logging
from typing import Any
from fastapi import FastAPI, Request
import mcp.types as types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.responses import JSONResponse

from cerbos_client import check_tool_permission

# Create an MCP server instance
server = Server("ai-control-plane-mcp")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    List available tools for the MCP server.
    """
    return [
        types.Tool(
            name="fetch_compliance_policy",
            description="Fetch the latest SOC2 or GDPR compliance policies for the tenant",
            inputSchema={
                "type": "object",
                "properties": {
                    "policy_type": {"type": "string", "enum": ["SOC2", "GDPR"]},
                },
                "required": ["policy_type"],
            },
        ),
        types.Tool(
            name="query_user_data",
            description="Query sensitive user data from the central store (Requires strict AuthZ)",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                },
                "required": ["user_id"],
            },
        ),
        types.Tool(
            name="check_kubernetes_pods",
            description="Fetch the status of pods in a specific Kubernetes namespace.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                },
                "required": ["namespace"],
            },
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """
    Execute a tool.
    """
    principal_id = "agent-123"
    role = "compliance-agent"

    is_allowed = await check_tool_permission(principal_id, role, name)
    if not is_allowed:
        return [
            types.TextContent(
                type="text",
                text=f"ERROR: Authorization denied. Agent '{principal_id}' (role: {role}) is not allowed to execute tool '{name}'."
            )
        ]

    if name == "fetch_compliance_policy":
        policy_type = arguments.get("policy_type") if arguments else "SOC2"
        return [
            types.TextContent(
                type="text",
                text=f"Content for {policy_type} Policy: All data must be encrypted at rest and in transit."
            )
        ]
    elif name == "query_user_data":
        user_id = arguments.get("user_id") if arguments else "unknown"
        return [
            types.TextContent(
                type="text",
                text=f"User Data for {user_id}: Name: John Doe, Plan: Enterprise"
            )
        ]
    elif name == "check_kubernetes_pods":
        ns = arguments.get("namespace") if arguments else "default"
        # Simulate a kubectl command for the dashboard testing
        return [
            types.TextContent(
                type="text",
                text=f"Pods in {ns}:\n- agent-orchestrator-8b5d... (Running)\n- mcp-server-578a... (Running)\n- postgres-0 (Running)"
            )
        ]
    else:
        raise ValueError(f"Unknown tool: {name}")


# FastAPI Application
app = FastAPI()

# SSE Transport
sse = SseServerTransport("/messages")

@app.get("/sse")
async def handle_sse(request: Request):
    """
    Establish SSE connection for MCP.
    """
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())

@app.post("/messages")
async def handle_messages(request: Request):
    """
    Receive POST messages from MCP client.
    """
    await sse.handle_post_message(request.scope, request.receive, request._send)

@app.get("/health")
def health_check():
    return {"status": "ok"}
