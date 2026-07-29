"""
auth/litellm_keys.py — LiteLLM Virtual Key resolution
"""
import os
import json

_keys_env = os.getenv("LITELLM_TENANT_KEYS", "{}")
try:
    _TENANT_KEYS = json.loads(_keys_env)
except Exception:
    _TENANT_KEYS = {}

def get_virtual_key_for_tenant(tenant_id: str) -> str:
    """Return the LiteLLM virtual key for the tenant, or a default fallback."""
    return _TENANT_KEYS.get(tenant_id, os.getenv("LITELLM_MASTER_KEY", "sk-default-master-key"))
