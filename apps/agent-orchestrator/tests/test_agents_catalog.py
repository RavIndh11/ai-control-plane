import pytest
from unittest.mock import patch, mock_open
import yaml

from agents.catalog_loader import get_agent_catalog, get_agent_profile
import agents.catalog_loader as catalog_loader

@pytest.fixture(autouse=True)
def reset_catalog():
    catalog_loader._agent_catalog = None
    yield
    catalog_loader._agent_catalog = None

def test_get_agent_catalog_success():
    yaml_data = """
agents:
  - id: compliance-agent
    name: Compliance Agent
  - id: custom-agent
    name: Custom Agent
"""
    with patch("builtins.open", mock_open(read_data=yaml_data)):
        catalog = get_agent_catalog()
        assert "compliance-agent" in catalog
        assert "custom-agent" in catalog
        assert catalog["compliance-agent"]["name"] == "Compliance Agent"
        
        # Test caching
        with patch("builtins.open") as mocked_open:
            get_agent_catalog()
            mocked_open.assert_not_called()

def test_get_agent_catalog_file_error():
    with patch("builtins.open", side_effect=FileNotFoundError):
        catalog = get_agent_catalog()
        assert catalog == {}

def test_get_agent_profile_found():
    yaml_data = """
agents:
  - id: compliance-agent
    name: Compliance Agent
  - id: custom-agent
    name: Custom Agent
"""
    with patch("builtins.open", mock_open(read_data=yaml_data)):
        profile = get_agent_profile("custom-agent")
        assert profile["name"] == "Custom Agent"

def test_get_agent_profile_not_found_fallback():
    yaml_data = """
agents:
  - id: compliance-agent
    name: Compliance Agent
"""
    with patch("builtins.open", mock_open(read_data=yaml_data)):
        profile = get_agent_profile("unknown-agent")
        assert profile["name"] == "Compliance Agent"
