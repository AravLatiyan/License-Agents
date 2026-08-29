"""Contract tests for the correspondence_history tool wiring (T-022).

Matching/degradation logic is covered end to end in
test_correspondence_history.py with a mocked requests.get - these only
check that server.py's tool wrapper validates its two inputs and
delegates correctly. Reuses the same address/domain validators
notify_impersonated/domain_intel already established (server.py's
_ADDRESS_RE/MAX_ADDRESS_LENGTH, _DOMAIN_RE/MAX_DOMAIN_LENGTH) rather than
inventing new ones.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.server import correspondence_history

VALID_ADDRESS = "ceo@northgate-trust.example"
VALID_DOMAIN = "northgate-trust.example"


def test_empty_address_is_rejected():
    with pytest.raises(ToolError):
        correspondence_history("", VALID_DOMAIN)


def test_whitespace_only_address_is_rejected():
    with pytest.raises(ToolError):
        correspondence_history("   ", VALID_DOMAIN)


def test_empty_domain_is_rejected():
    with pytest.raises(ToolError):
        correspondence_history(VALID_ADDRESS, "")


def test_whitespace_only_domain_is_rejected():
    with pytest.raises(ToolError):
        correspondence_history(VALID_ADDRESS, "   ")


@pytest.mark.parametrize(
    "bad_address",
    [
        "no-at-sign.example",
        "two@@at.example",
        "no-dot-in-domain@localhost",
        "a@b.example, c@d.example",
        "a" * 250 + "@x.example",
    ],
)
@patch("imports_mcp.server._correspondence_history")
def test_malformed_address_is_rejected_before_any_lookup(mock_history, bad_address):
    with pytest.raises(ToolError):
        correspondence_history(bad_address, VALID_DOMAIN)
    mock_history.assert_not_called()


@pytest.mark.parametrize(
    "bad_domain",
    [
        "example.com/../../etc/passwd",
        "example.com?evil=1",
        "exa mple.com",
        "nodothost",
        "a" * 300 + ".com",
    ],
)
@patch("imports_mcp.server._correspondence_history")
def test_syntactically_invalid_domain_is_rejected_before_any_lookup(mock_history, bad_domain):
    with pytest.raises(ToolError):
        correspondence_history(VALID_ADDRESS, bad_domain)
    mock_history.assert_not_called()


@patch("imports_mcp.server._correspondence_history")
def test_delegates_with_stripped_arguments(mock_history):
    mock_history.return_value = {
        "address": VALID_ADDRESS,
        "domain": VALID_DOMAIN,
        "prior_contact_count": 0,
        "first_seen": None,
        "last_seen": None,
        "domains_used": [],
    }

    result = correspondence_history(f"  {VALID_ADDRESS}  ", f"  {VALID_DOMAIN}  ")

    mock_history.assert_called_once_with(VALID_ADDRESS, VALID_DOMAIN)
    assert result["prior_contact_count"] == 0
