import yaml
import os
from typing import Dict, Any

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "catalog.yaml")

_agent_catalog = None

def get_agent_catalog() -> Dict[str, Any]:
    global _agent_catalog
    if _agent_catalog is None:
        try:
            with open(CATALOG_PATH, "r") as f:
                data = yaml.safe_load(f)
                # Map by agent id
                _agent_catalog = {agent["id"]: agent for agent in data.get("agents", [])}
        except Exception as e:
            print(f"[Catalog Loader] Error loading catalog.yaml: {e}")
            _agent_catalog = {}
    return _agent_catalog

def get_agent_profile(agent_id: str) -> Dict[str, Any]:
    catalog = get_agent_catalog()
    # Default to compliance-agent if not found or not specified
    return catalog.get(agent_id, catalog.get("compliance-agent", {}))
