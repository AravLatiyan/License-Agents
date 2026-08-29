"""Contract tests for the detonate tool wiring (T-026).

Redirect/parsing behaviour is covered end to end in test_detonate.py
against a local fixture server — these only check that server.py's tool
wrapper validates its input and delegates correctly. Unlike domain_intel's
domain or notify_impersonated's address, `url` isn't pre-validated for
syntax here: detonate() itself already returns a structured
`{error: "refused non-http(s) scheme..."}` for a malformed URL instead of
raising, so a second validation layer in the wrapper would just duplicate
that check.

The regression tests at the end of this file (Qodo's PR #37 review — the
original 6 findings, plus 5 more from its re-review after the DNS-pinning
fix) belong with test_detonate.py's own local-fixture-server suite by
subject, but that file lives on a separate stacked PR (#38, not yet
merged) — kept here instead of forking a same-named file that would
collide with it, and flagged in PLAN.md for whoever merges both to
consider consolidating.
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, Mock, patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.detonate import _pin_dns_resolution, _PrivateNetworkTarget, _resolve_pinned_address
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


# --- Finding #3 (DNS rebinding / TOCTOU) and #5 (private-target bypass hardening) ---


def test_pinned_dns_resolution_ignores_a_changed_answer_mid_flight():
    """Finding #3: once an address is pinned, every getaddrinfo() call for
    that hostname inside the block must keep returning the pinned address,
    even if the *real* resolver would now answer differently - this is
    exactly what stops a DNS-rebinding attacker from getting a different
    answer between validation and connection. 203.0.113.5 is TEST-NET-3
    (RFC 5737) - reserved, never actually resolved or connected to."""
    with _pin_dns_resolution("pinned.example", "203.0.113.5", socket.AF_INET):
        infos = socket.getaddrinfo("pinned.example", 443)
        assert infos[0][4][0] == "203.0.113.5"

        # A different hostname is never affected by another host's pin.
        with pytest.raises(socket.gaierror):
            socket.getaddrinfo("pinned.invalid-unrelated.example", 443)

    # Outside the block the pin no longer applies - the same hostname now
    # falls through to the real resolver, which raises for this
    # non-resolvable test name, proving nothing leaked past the context
    # manager's exit.
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("pinned.example", 443)


def test_resolve_pinned_address_raises_for_a_private_resolved_address(monkeypatch):
    """A hostname that resolves to a private address must be refused even
    though the hostname string itself isn't a literal private IP."""

    def fake_getaddrinfo(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(_PrivateNetworkTarget) as excinfo:
        _resolve_pinned_address("rebinding.example")
    assert excinfo.value.address == "10.0.0.5"


def test_resolve_pinned_address_returns_pin_for_a_public_resolved_address(monkeypatch):
    def fake_getaddrinfo(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    address, family = _resolve_pinned_address("public.example")
    assert address == "8.8.8.8"
    assert family == socket.AF_INET


@patch("imports_mcp.detonate._get_without_proxy_trust")
@patch("imports_mcp.detonate._resolve_pinned_address")
def test_detonate_pins_the_connection_during_the_real_request(mock_resolve, mock_get):
    """Wiring test: detonate() must actually activate the pin during the
    real request, not just have the primitive available unused. 8.8.8.8
    is a well-known public address, chosen only because it's unambiguous
    - the request itself is mocked so no real connection is attempted
    either way. Patches _get_without_proxy_trust (not requests.get)
    since that's what detonate() actually calls now (Qodo finding,
    "Proxies bypass DNS pinning") - requests.get is no longer called
    directly."""
    mock_resolve.return_value = ("8.8.8.8", socket.AF_INET)
    seen: dict[str, str] = {}

    def fake_get(*args, **kwargs):
        infos = socket.getaddrinfo("public.example", 443)
        seen["address"] = infos[0][4][0]
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/plain"}
        response.iter_content = lambda chunk_size: iter([b"ok"])
        response.encoding = "utf-8"
        return response

    mock_get.side_effect = fake_get

    _detonate_module("http://public.example/")

    assert seen["address"] == "8.8.8.8"


def test_private_target_bypass_requires_the_explicit_env_var_too(monkeypatch):
    """Finding #5: allow_private_network_targets=True alone must not be
    enough to reach a local target. conftest.py's autouse fixture sets
    IMPORTS_MCP_ALLOW_TEST_TARGETS for every other test in this suite; this
    one explicitly unsets it to prove the parameter alone doesn't bypass
    anything without it."""
    monkeypatch.delenv("IMPORTS_MCP_ALLOW_TEST_TARGETS", raising=False)

    result = _detonate_module("http://127.0.0.1:1/", allow_private_network_targets=True)

    assert "refused private/internal network target" in result["error"]


def test_private_target_bypass_works_with_the_env_var_set():
    """Sanity check the other direction - with the env var set (the
    conftest.py default for this whole suite), the bypass still functions,
    proving finding #5's hardening didn't quietly break normal test usage."""
    result = _detonate_module("http://127.0.0.1:1/", allow_private_network_targets=True)

    # Port 1 refuses the connection (nothing listens there) - a real
    # network-layer error, not the private-target refusal, proves the
    # bypass was actually honored.
    assert "refused private/internal network target" not in (result.get("error") or "")


# --- Qodo PR #37 re-review (after the DNS-pinning fix): 3 new findings ---


def test_idna_hostname_canonicalizes_to_the_ascii_form_requests_uses():
    """"IDNs bypass DNS pinning": _idna_hostname must produce exactly the
    ASCII/punycode string Requests' own PreparedRequest.prepare_url
    produces internally (host.encode('idna')) - any divergence between
    the two would mean the pin key and the hostname actually resolved at
    connection time don't match. 例え.テスト ("example.test" in
    Japanese) is a standard IDN worked example, not a real domain."""
    from imports_mcp.detonate import _idna_hostname

    unicode_host = "例え.テスト"
    expected = unicode_host.encode("idna").decode("ascii")

    assert _idna_hostname(unicode_host) == expected
    assert expected.isascii()
    # Already-ASCII hosts pass through unchanged - Requests' own encoding
    # is a no-op for them too, so the pin key can't shift for ordinary URLs.
    assert _idna_hostname("example.com") == "example.com"


@patch("imports_mcp.detonate._get_without_proxy_trust")
@patch("imports_mcp.detonate._resolve_pinned_address")
def test_detonate_pins_an_idn_host_despite_the_unicode_ascii_mismatch(mock_resolve, mock_get):
    """"IDNs bypass DNS pinning": detonate() used to pin under the raw
    Unicode hostname from urlparse, but Requests IDNA-encodes a non-ASCII
    host before the real connection - so the pin key and the hostname
    actually resolved at connection time diverged, and the real request
    fell through to a second, unpinned lookup. This mocks
    _get_without_proxy_trust to do what Requests itself really does
    internally (IDNA-encode the host, then call socket.getaddrinfo on
    that encoded form) and proves it still lands on the pinned address -
    it would instead hit the *real* resolver (raising gaierror for this
    non-existent test name) before the fix, since the pin's Unicode key
    would never match."""
    mock_resolve.return_value = ("8.8.8.8", socket.AF_INET)
    seen: dict[str, str] = {}

    def fake_get(*args, **kwargs):
        idna_host = "例え.テスト".encode("idna").decode("ascii")
        infos = socket.getaddrinfo(idna_host, 443)
        seen["address"] = infos[0][4][0]
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/plain"}
        response.iter_content = lambda chunk_size: iter([b"ok"])
        response.encoding = "utf-8"
        return response

    mock_get.side_effect = fake_get

    _detonate_module("http://例え.テスト/")

    assert seen["address"] == "8.8.8.8"


def test_invalid_form_port_is_reported_as_action_invalid_not_a_raise():
    """"Invalid form ports raise": _normalize_origin reads parsed.port,
    which raises ValueError for an out-of-range port like :99999 - after
    the surrounding malformed-action guard had already exited normally
    (urlparse itself doesn't validate the port eagerly). One hostile form
    must not escape detonate()'s never-raise contract or abort analysis
    of the page's other forms."""
    from imports_mcp.detonate import _extract_forms

    html = (
        '<html><body>'
        '<form method="POST" action="https://example.com:99999/collect">'
        '<input type="password" name="p"></form>'
        '<form method="POST" action="https://example.com/ok">'
        '<input type="text" name="q"></form>'
        '</body></html>'
    )
    forms = _extract_forms(html, "https://example.com/login")

    assert len(forms) == 2
    assert forms[0]["action_invalid"] is True
    assert forms[0]["action_origin"] is None
    assert forms[0]["cross_domain"] is None
    # The second, well-formed form is still reported - one bad port
    # doesn't abort the rest of the page's analysis.
    assert forms[1].get("action_invalid") is None
    assert forms[1]["action_origin"] == "https://example.com"


def test_get_without_proxy_trust_disables_environment_proxy_trust():
    """"Proxies bypass DNS pinning": Requests honors HTTP_PROXY/
    HTTPS_PROXY/ALL_PROXY by default, letting a proxy resolve the target
    independently of _pin_dns_resolution. _get_without_proxy_trust must
    set trust_env=False on the Session it uses for the real request."""
    from imports_mcp.detonate import _get_without_proxy_trust

    response = Mock()
    session = MagicMock()
    session.get.return_value = response
    session.__enter__.return_value = session

    with patch("imports_mcp.detonate.requests.Session", return_value=session):
        result = _get_without_proxy_trust("https://example.com/", timeout=5, stream=True)

    assert session.trust_env is False
    session.get.assert_called_once_with("https://example.com/", timeout=5, stream=True)
    assert result is response
