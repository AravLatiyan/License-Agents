"""Contract tests for the url_reputation tool wiring (T-021).

Network/verdict logic is already covered end to end in
test_url_reputation.py with a mocked requests.post - these tests only
check that server.py's tool wrapper validates input and delegates.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.server import url_reputation


def test_empty_url_is_rejected():
    with pytest.raises(ToolError):
        url_reputation("")


def test_whitespace_only_url_is_rejected():
    with pytest.raises(ToolError):
        url_reputation("   ")


@patch("imports_mcp.server._url_reputation")
def test_delegates_to_url_reputation_module(mock_url_reputation):
    mock_url_reputation.return_value = {"url": "https://example.com/", "available": True, "listed": False}

    result = url_reputation("  https://example.com/  ")

    mock_url_reputation.assert_called_once_with("https://example.com/")
    assert result == {"url": "https://example.com/", "available": True, "listed": False}
