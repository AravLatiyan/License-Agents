"""Contract tests for the notify_impersonated tool wiring (T-031).

Send/degradation behaviour is covered end to end in
test_notify_impersonated.py with smtplib mocked — these only check that
server.py's tool wrapper validates its input and delegates correctly.

The validation matters more here than for the read-only tools: this one
sends mail to whatever address it is handed, off model-generated arguments,
and it is one of the four gated actions (T-034). A malformed address must be
refused at the tool boundary, before any SMTP connection is opened.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.server import notify_impersonated

VALID = "a.morgan@northgate-trust.example"


def test_empty_address_is_rejected():
    with pytest.raises(ToolError):
        notify_impersonated("", "mission-001")


def test_whitespace_only_address_is_rejected():
    with pytest.raises(ToolError):
        notify_impersonated("   ", "mission-001")


def test_empty_evidence_is_rejected():
    """Without a reference the recipient gets an unactionable notice."""
    with pytest.raises(ToolError):
        notify_impersonated(VALID, "")


def test_whitespace_only_evidence_is_rejected():
    with pytest.raises(ToolError):
        notify_impersonated(VALID, "   ")


@pytest.mark.parametrize(
    "bad_address",
    [
        "no-at-sign.example",           # no @
        "two@@at.example",              # malformed
        "no-dot-in-domain@localhost",   # no dot in domain
        "spaced address@x.example",     # embedded whitespace
        "a@b.example, c@d.example",     # second recipient smuggled in
        "a@b.example;c@d.example",      # ditto, different separator
        "victim@x.example>",            # angle bracket
        '"quoted"@x.example',           # quote character
        "a\\b@x.example",               # backslash
        "a" * 250 + "@x.example",       # exceeds MAX_ADDRESS_LENGTH
    ],
)
@patch("imports_mcp.server._notify_impersonated")
def test_malformed_address_is_rejected_before_any_smtp_connection(mock_send, bad_address):
    """Header-injection and multi-recipient shapes must never reach the send
    path — asserting the delegate was never called is the point of the test,
    not just that it raised."""
    with pytest.raises(ToolError):
        notify_impersonated(bad_address, "mission-001")
    mock_send.assert_not_called()


@patch("imports_mcp.server._notify_impersonated")
def test_newline_in_address_is_rejected_before_any_smtp_connection(mock_send):
    """Kept out of the parametrize list because .strip() removes trailing
    newlines — this checks an embedded one, the real injection shape."""
    with pytest.raises(ToolError):
        notify_impersonated("victim@x.example\nBcc: attacker@evil.example", "mission-001")
    mock_send.assert_not_called()


@patch("imports_mcp.server._notify_impersonated")
def test_valid_address_delegates_with_stripped_arguments(mock_send):
    mock_send.return_value = {"sent": True}

    notify_impersonated(f"  {VALID}  ", "  mission-001  ")

    mock_send.assert_called_once_with(VALID, "mission-001")


@patch("imports_mcp.server._notify_impersonated")
def test_subdomain_and_plus_addressing_are_accepted(mock_send):
    mock_send.return_value = {"sent": True}

    notify_impersonated("alex.morgan+phish@mail.northgate-trust.example", "mission-001")

    mock_send.assert_called_once()
