"""Contract tests for the domain_intel tool wiring (T-020).

Parsing/network-degradation logic is already covered end to end in
test_domain_intel.py with a mocked requests.get - these tests only check
that server.py's tool wrapper validates input and delegates correctly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.server import domain_intel


def test_empty_domain_is_rejected():
    with pytest.raises(ToolError):
        domain_intel("")


def test_whitespace_only_domain_is_rejected():
    with pytest.raises(ToolError):
        domain_intel("   ")


@patch("imports_mcp.server._domain_intel")
def test_delegates_to_domain_intel_module(mock_domain_intel):
    mock_domain_intel.return_value = {"domain": "example.com", "rdap": {}, "cert": {}}

    result = domain_intel("  example.com  ")

    mock_domain_intel.assert_called_once_with("example.com")
    assert result == {"domain": "example.com", "rdap": {}, "cert": {}}
