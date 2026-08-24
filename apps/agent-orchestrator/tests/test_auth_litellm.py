import pytest
from unittest.mock import patch

from auth.litellm_keys import get_virtual_key_for_tenant
import auth.litellm_keys as litellm_keys

def test_get_virtual_key_found():
    with patch.dict(litellm_keys._TENANT_KEYS, {"tenant1": "sk-tenant1"}):
        assert get_virtual_key_for_tenant("tenant1") == "sk-tenant1"

def test_get_virtual_key_not_found():
    with patch.dict(litellm_keys._TENANT_KEYS, {}, clear=True):
        with patch("os.getenv", return_value="sk-master"):
            assert get_virtual_key_for_tenant("unknown") == "sk-master"
