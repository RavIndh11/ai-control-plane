import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel
from mcp.server.fastapi import create_mcp_app
import mcp.types as types
from mcp.server import Server

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
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """
    Execute a tool. We assume the caller sends their identity in the request headers
    (which we would ideally extract in the FastAPI route, but for MCP over HTTP, 
    we simulate it by checking Cerbos with dummy data for now).
    """
    # In a real implementation with MCP over SSE, you'd extract the principal from the HTTP session
    # For demonstration, we'll use a hardcoded agent identity
    principal_id = "agent-123"
    role = "compliance-agent"

    # Enforce Authorization via Cerbos
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
    else:
        raise ValueError(f"Unknown tool: {name}")


# Expose the MCP server via FastAPI SSE
app = create_mcp_app(server)

@app.get("/health")
def health_check():
    return {"status": "ok"}
