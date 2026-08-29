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


@pytest.mark.parametrize(
    "bad_domain",
    [
        "example.com/../../etc/passwd",  # path delimiter
        "example.com?evil=1",  # query delimiter
        "example.com#frag",  # fragment delimiter
        "exa mple.com",  # embedded whitespace
        "-example.com",  # leading hyphen label
        "example.com-",  # trailing hyphen label
        "nodothost",  # no dot at all
        "a" * 300 + ".com",  # exceeds MAX_DOMAIN_LENGTH
    ],
)
def test_syntactically_invalid_domain_is_rejected_before_any_lookup(bad_domain):
    # A "/", "?", or "#" reaching _rdap_lookup unvalidated would change
    # which RDAP path/query actually gets requested (Qodo finding #10 on
    # PR #19) - reject at the tool boundary, before _domain_intel ever runs.
    with pytest.raises(ToolError):
        domain_intel(bad_domain)


@patch("imports_mcp.server._domain_intel")
def test_valid_domain_with_hyphens_and_multiple_labels_is_accepted(mock_domain_intel):
    mock_domain_intel.return_value = {"domain": "sub.my-domain.example.com", "rdap": {}, "cert": {}}

    domain_intel("sub.my-domain.example.com")

    mock_domain_intel.assert_called_once_with("sub.my-domain.example.com")


@patch("imports_mcp.server._domain_intel")
def test_delegates_to_domain_intel_module(mock_domain_intel):
    mock_domain_intel.return_value = {"domain": "example.com", "rdap": {}, "cert": {}}

    result = domain_intel("  example.com  ")

    mock_domain_intel.assert_called_once_with("example.com")
    assert result == {"domain": "example.com", "rdap": {}, "cert": {}}
