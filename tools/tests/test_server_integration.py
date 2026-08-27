"""End-to-end tests (T-012, T-020): real Streamable HTTP transport, real
MCP client — deterministic only, no live network calls.

Spins tools/imports_mcp/server.py as a subprocess on a dedicated test port
and connects with the official MCP client. This is what actually proves
the T-004 transport decision works, not just that the underlying Python
functions are correct - those are already covered without paying for a
server in test_server_contract.py and test_domain_intel.py.

Live-network tests (real RDAP/crt.sh/URLhaus calls) live in
test_server_integration_live.py instead, with their own separate server
subprocess (see _server_fixtures.py) - PLAN.md §7 records a reproducible
httpx.ReadTimeout on a *later* test sharing a subprocess with a real
network call, so this file's always-on tests never share one with that.
"""

from __future__ import annotations

from tests._server_fixtures import call_tool, running_server

__all__ = ["running_server"]  # re-exported so pytest can collect it as a fixture


def _call_parse_message(url: str, fixture: str):
    return call_tool(url, "parse_message", {"fixture": fixture})


def test_parse_message_reachable_over_streamable_http(running_server):
    tools, result = _call_parse_message(running_server, "03-legitimate.eml")

    assert "parse_message" in [t.name for t in tools.tools]
    assert not result.is_error
    assert result.content
    assert "priya.nair@universal-imports.example" in result.content[0].text


def test_unknown_fixture_returns_error_over_the_wire(running_server):
    _, result = _call_parse_message(running_server, "nope.eml")
    assert result.is_error
    assert "Unknown fixture" in result.content[0].text


def test_domain_intel_empty_domain_returns_error_over_the_wire(running_server):
    _, result = call_tool(running_server, "domain_intel", {"domain": ""})
    assert result.is_error


def test_url_reputation_empty_url_returns_error_over_the_wire(running_server):
    _, result = call_tool(running_server, "url_reputation", {"url": ""})
    assert result.is_error
