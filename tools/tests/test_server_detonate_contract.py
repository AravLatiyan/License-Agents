"""Contract tests for the detonate tool wiring (T-026).

Redirect/parsing behaviour is covered end to end in test_detonate.py
against a local fixture server — these only check that server.py's tool
wrapper validates its input and delegates correctly. Unlike domain_intel's
domain or notify_impersonated's address, `url` isn't pre-validated for
syntax here: detonate() itself already returns a structured
`{error: "refused non-http(s) scheme..."}` for a malformed URL instead of
raising, so a second validation layer in the wrapper would just duplicate
that check.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.server import detonate


def test_empty_url_is_rejected():
    with pytest.raises(ToolError):
        detonate("")


def test_whitespace_only_url_is_rejected():
    with pytest.raises(ToolError):
        detonate("   ")


@patch("imports_mcp.server._detonate")
def test_delegates_to_detonate_module_with_stripped_url(mock_detonate):
    mock_detonate.return_value = {"url": "https://example.com/", "redirect_chain": [], "error": "x"}

    detonate("  https://example.com/  ")

    mock_detonate.assert_called_once_with("https://example.com/")


@patch("imports_mcp.server._detonate")
def test_malformed_url_still_delegates_not_pre_rejected(mock_detonate):
    """A non-http(s) scheme is the detonate module's own job to report as
    a structured error, not the wrapper's to reject up front."""
    mock_detonate.return_value = {"url": "javascript:x", "redirect_chain": [], "error": "refused non-http(s) scheme: javascript"}

    result = detonate("javascript:x")

    mock_detonate.assert_called_once_with("javascript:x")
    assert result["error"]
