import os
import logging
import uuid
from datetime import datetime
import httpx
from fastapi import FastAPI, Request
import mcp.types as types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.responses import JSONResponse

import yaml

class GovernanceDenied(Exception):
    pass

def govern(policy: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                with open(policy, "r") as f:
                    pol = yaml.safe_load(f)
            except Exception as e:
                logging.error(f"Policy load failed: {e}")
                return func(*args, **kwargs)
            
            action_val = kwargs.get("action")
            for rule in pol.get("rules", []):
                cond = rule.get("condition", "")
                if "action.type ==" in cond and action_val:
                    target = cond.split("==")[1].strip().strip("'").strip('"')
                    if action_val == target and rule.get("action") == "deny":
                        raise GovernanceDenied(f"Policy '{rule.get('name')}' denied action '{action_val}': {rule.get('description')}")
            
            return func(*args, **kwargs)
        return wrapper
    return decorator
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

@govern(policy="policy.yaml")
def do_fetch_compliance_policy(action: str, policy_type: str) -> str:
    return f"Content for {policy_type} Policy: All data must be encrypted at rest and in transit."

@govern(policy="policy.yaml")
def do_query_user_data(action: str, user_id: str) -> str:
    return f"User Data for {user_id}: Name: John Doe, Plan: Enterprise"

@govern(policy="policy.yaml")
def do_check_kubernetes_pods(action: str, namespace: str) -> str:
    try:
        import httpx
        token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        ca_cert = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        with open(token_path, "r") as f:
            token = f.read().strip()
        
        headers = {"Authorization": f"Bearer {token}"}
        # Using sync httpx for simplicity in the wrapped function
        with httpx.Client(verify=ca_cert) as client:
            res = client.get(
                f"https://kubernetes.default.svc/api/v1/namespaces/{namespace}/pods",
                headers=headers
            )
            if res.status_code == 200:
                pods = res.json().get("items", [])
                lines = [f"Pods in namespace '{namespace}':"]
                for p in pods:
                    name = p["metadata"]["name"]
                    phase = p.get("status", {}).get("phase", "Unknown")
                    lines.append(f"- {name} ({phase})")
                return "\n".join(lines)
            else:
                return f"API Error {res.status_code}: {res.text}"
    except Exception as exc:
        return f"Failed to fetch real pods: {exc}"

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """
    Execute a tool.
    """
    try:
        if name == "fetch_compliance_policy":
            policy_type = arguments.get("policy_type") if arguments else "SOC2"
            text_val = do_fetch_compliance_policy(action=name, policy_type=policy_type)
        elif name == "query_user_data":
            user_id = arguments.get("user_id") if arguments else "unknown"
            text_val = do_query_user_data(action=name, user_id=user_id)
        elif name == "check_kubernetes_pods":
            ns = arguments.get("namespace") if arguments else "default"
            text_val = do_check_kubernetes_pods(action=name, namespace=ns)
        else:
            raise ValueError(f"Unknown tool: {name}")
            
        return [types.TextContent(type="text", text=text_val)]
    except Exception as e:
        if "GovernanceDenied" in str(type(e).__name__):
            gov_url = os.getenv("GOVERNANCE_ENGINE_URL", "http://governance-engine.default.svc.cluster.local:8000")
            try:
                httpx.post(
                    f"{gov_url}/api/v1/agt/audit_logs",
                    json={
                        "run_id": str(uuid.uuid4()),
                        "agent_id": "mcp-server",
                        "tool_name": name,
                        "action_type": name,
                        "verdict": "deny",
                        "reason": str(e),
                        "timestamp": datetime.utcnow().isoformat(),
                        "payload": {"tool": name, "arguments": arguments}
                    },
                    timeout=2.0
                )
            except Exception as post_exc:
                logging.error(f"Failed to post audit log to {gov_url}: {post_exc}")
            return [types.TextContent(type="text", text=f"ERROR: Authorization denied by AGT: {e}")]
        raise

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
