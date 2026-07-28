"""
authz/cerbos.py — Cerbos ABAC policy decision point client.

Provides is_authorized() which first attempts the live Cerbos PDP,
then falls back to a local in-process policy emulator that mirrors
the YAML policies in platform/policy/cerbos/policies/.
"""
import os
import uuid
from typing import Any, Dict

import httpx

CERBOS_URL: str = os.getenv("CERBOS_URL", "http://localhost:3592")


def is_authorized(
    principal: Dict[str, Any],
    resource_kind: str,
    resource_id: str,
    action: str,
    resource_attr: Dict[str, Any],
) -> bool:
    """
    Check whether *principal* may perform *action* on *resource_kind*.

    Args:
        principal:     dict from get_principal() — must have 'id', 'roles', 'tenant_id'
        resource_kind: Cerbos resource name  (e.g. 'agent_thread')
        resource_id:   stable resource id    (e.g. thread_id)
        action:        action string         ('read' | 'write' | 'delete')
        resource_attr: arbitrary resource attributes checked by policies

    Returns:
        True if EFFECT_ALLOW, False otherwise.
    """
    payload = {
        "requestId": str(uuid.uuid4()),
        "principal": {
            "id":    principal["id"],
            "roles": principal["roles"],
            "attr":  {"tenant_id": principal["tenant_id"]},
        },
        "resources": [
            {
                "actions": [action],
                "resource": {
                    "id":   resource_id,
                    "kind": resource_kind,
                    "attr": resource_attr,
                },
            }
        ],
    }

    # ── Live Cerbos PDP ───────────────────────────────────────────────────────
    try:
        with httpx.Client(timeout=2.0) as client:
            res = client.post(f"{CERBOS_URL}/api/check/resources", json=payload)
            if res.status_code == 200:
                results = res.json().get("results", [])
                if results:
                    effect = results[0].get("actions", {}).get(action, "EFFECT_DENY")
                    return effect == "EFFECT_ALLOW"
    except Exception:
        print(f"[Authz] Cerbos PDP unreachable — falling back to local emulator.")

    # ── Local emulator (mirrors cerbos/policies/*.yaml) ───────────────────────
    return _local_policy(principal, resource_kind, action, resource_attr)


def _local_policy(
    principal: Dict[str, Any],
    resource_kind: str,
    action: str,
    resource_attr: Dict[str, Any],
) -> bool:
    """In-process ABAC emulator — must stay in sync with cerbos YAML policies."""
    roles      = principal["roles"]
    tenant_id  = principal["tenant_id"]
    res_tenant = resource_attr.get("tenant_id", "")

    # super-admin: full access everywhere
    if "super-admin" in roles:
        return True

    # --- agent_thread policy ---
    if resource_kind == "agent_thread":
        if action in ("read", "write") and "tenant-user" in roles:
            return tenant_id == res_tenant
        if action in ("read", "write", "delete") and "tenant-admin" in roles:
            return tenant_id == res_tenant

    # --- compliance_evidence policy ---
    if resource_kind == "compliance_evidence":
        if action == "create":
            return bool(
                set(roles) & {"system-workload", "agent-orchestrator",
                               "tenant-admin", "tenant-user"}
            )
        if action == "read":
            if "compliance-auditor" in roles:
                return True
            if "tenant-admin" in roles:
                return tenant_id == res_tenant

    return False
