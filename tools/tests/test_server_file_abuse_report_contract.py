"""Contract tests for the file_abuse_report tool wiring (T-033).

Send/degradation behaviour is covered in test_file_abuse_report.py with SMTP
and RDAP mocked — these only check that server.py's wrapper validates its
input and delegates correctly.

Validation matters at this boundary because the argument becomes an RDAP
request path: the same reason domain_intel validates it. A malformed domain
must be refused before any lookup, and therefore long before any mail.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.server import file_abuse_report

VALID = "northgate-trust-finance.example"


def test_empty_domain_is_rejected():
    with pytest.raises(ToolError):
        file_abuse_report("", "mission-001")


def test_whitespace_only_domain_is_rejected():
    with pytest.raises(ToolError):
        file_abuse_report("   ", "mission-001")


def test_empty_evidence_is_rejected():
    """Without a reference the registrar receives an unactionable report."""
    with pytest.raises(ToolError):
        file_abuse_report(VALID, "")


def test_whitespace_only_evidence_is_rejected():
    with pytest.raises(ToolError):
        file_abuse_report(VALID, "   ")


@pytest.mark.parametrize(
    "bad_domain",
    [
        "example.com/../../etc/passwd",  # path delimiter
        "example.com?evil=1",            # query delimiter
        "example.com#frag",              # fragment
        "exa mple.com",                  # embedded whitespace
        "-example.com",                  # leading hyphen label
        "example.com-",                  # trailing hyphen label
        "nodothost",                     # no dot at all
        "a" * 300 + ".com",              # exceeds MAX_DOMAIN_LENGTH
    ],
)
@patch("imports_mcp.server._file_abuse_report")
def test_malformed_domain_is_rejected_before_any_lookup(mock_send, bad_domain):
    """Asserting the delegate was never called is the point — a "/" or "?"
    reaching RDAP would change which request is actually made."""
    with pytest.raises(ToolError):
        file_abuse_report(bad_domain, "mission-001")
    mock_send.assert_not_called()


@patch("imports_mcp.server._file_abuse_report")
def test_newline_in_domain_is_rejected_before_any_lookup(mock_send):
    """Kept out of the parametrize list because .strip() removes trailing
    newlines — this checks an embedded one."""
    with pytest.raises(ToolError):
        file_abuse_report("example.com\nBcc: attacker@evil.example", "mission-001")
    mock_send.assert_not_called()


@patch("imports_mcp.server._file_abuse_report")
def test_valid_domain_delegates_with_stripped_arguments(mock_send):
    mock_send.return_value = {"sent": True}

    file_abuse_report(f"  {VALID}  ", "  mission-001  ")

    mock_send.assert_called_once_with(VALID, "mission-001")


@patch("imports_mcp.server._file_abuse_report")
def test_subdomains_are_accepted(mock_send):
    mock_send.return_value = {"sent": True}

    file_abuse_report("mail.northgate-trust-finance.example", "mission-001")

    mock_send.assert_called_once()


def test_tool_is_registered_under_the_gated_name():
    """harness/agent.json's require_approval_for_tools lists the literal name
    `file_abuse_report` (T-034). If this function were ever renamed, the gate
    would silently stop matching and an irreversible action would run
    ungated — the same failure mode the T-034 config test guards from the
    other side."""
    from imports_mcp import server

    assert hasattr(server, "file_abuse_report")
