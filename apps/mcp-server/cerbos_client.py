import os
import httpx
import logging

CERBOS_URL = os.getenv("CERBOS_URL", "http://cerbos.control-plane.svc.cluster.local:3592")
logger = logging.getLogger(__name__)

async def check_tool_permission(principal_id: str, role: str, tool_name: str) -> bool:
    """
    Check if the given principal (Agent) is allowed to execute the specified tool.
    Uses the Cerbos API.
    """
    payload = {
        "requestId": "mcp-req",
        "principal": {
            "id": principal_id,
            "roles": [role]
        },
        "resource": {
            "kind": "mcp_tool",
            "id": tool_name
        },
        "actions": ["execute"]
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{CERBOS_URL}/api/check/resources", json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            # Extract the effect for the 'execute' action
            results = data.get("results", [])
            if not results:
                return False
                
            effect = results[0].get("actions", {}).get("execute", "EFFECT_DENY")
            return effect == "EFFECT_ALLOW"
    except Exception as e:
        logger.error(f"Cerbos check failed: {e}")
        # Default deny on error
        return False
