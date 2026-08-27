"""Live-network end-to-end tests, split out of test_server_integration.py
(Qodo PR #19 finding: "Live test remains flaky").

Real RDAP/crt.sh and URLhaus calls, over the real Streamable HTTP transport
- proves the whole path is wired, not just that the underlying Python
functions are correct (already covered, mocked, in test_domain_intel.py /
test_url_reputation.py). Both tests are opt-in and skip by default so a
plain `pytest` run (CI, a clean clone, a judge's machine) never depends on
an external service being fast and reachable right now.

This file has its own server subprocess (see _server_fixtures.py's
module-scoped `running_server`, keyed per importing module) rather than
sharing one with test_server_integration.py's always-on deterministic
tests - PLAN.md §7 records a reproducible httpx.ReadTimeout on a *later*
test once a real network call has gone through a shared subprocess, so a
stall here can no longer touch the tests that actually run by default.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
import pytest

from tests._server_fixtures import TOOLS_DIR, call_tool, running_server

__all__ = ["running_server"]  # re-exported so pytest can collect it as a fixture

# Mirrors imports_mcp.url_reputation's own load_dotenv call, so this check
# reflects whatever's actually configured (env var or .env), not just
# whatever happens to already be exported in this shell.
load_dotenv(TOOLS_DIR.parent / ".env")
URLHAUS_AUTH_KEY_CONFIGURED = bool(os.environ.get("URLHAUS_AUTH_KEY"))

# domain_intel has no auth key to gate on (RDAP/crt.sh are unauthenticated),
# but its real network calls have reproducibly caused a shared module-scoped
# server subprocess to time out on a later test once a real call has gone
# through it (PLAN.md §7) - opt in explicitly rather than have every default
# `pytest` run depend on RDAP/crt.sh being fast and reachable right now.
RUN_LIVE_DOMAIN_INTEL_TESTS = os.environ.get("RUN_LIVE_DOMAIN_INTEL_TESTS") == "1"


@pytest.mark.skipif(
    not RUN_LIVE_DOMAIN_INTEL_TESTS,
    reason="real RDAP/crt.sh calls have reproducibly caused a shared server subprocess to hit "
    "httpx.ReadTimeout on a later test (PLAN.md §7) - opt in explicitly with "
    "RUN_LIVE_DOMAIN_INTEL_TESTS=1; the deterministic behavior is already covered by the "
    "mocked tests in test_domain_intel.py",
)
def test_domain_intel_reachable_over_streamable_http(running_server):
    """Real RDAP/crt.sh calls, not mocked - proves the whole path is wired,
    not just the HTTP transport. Deliberately asserts on structure only
    (domain echoed back, both sections present), never on live content: a
    volatile upstream value (registrar name, RDAP/crt.sh being reachable at
    all) would make this test only as reliable as those services, exactly
    the flakiness domain_intel's own graceful-degradation contract exists
    to route around - is_error stays False either way, which is what this
    test is actually here to prove."""
    tools, result = call_tool(running_server, "domain_intel", {"domain": "google.com"})

    assert "domain_intel" in [t.name for t in tools.tools]
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["domain"] == "google.com"
    assert "available" in payload["rdap"]
    assert "available" in payload["cert"]


@pytest.mark.skipif(
    not URLHAUS_AUTH_KEY_CONFIGURED,
    reason="requires URLHAUS_AUTH_KEY (env var or .env) for a live URLhaus call - "
    "deterministic behavior is already covered by the mocked tests in test_url_reputation.py",
)
def test_url_reputation_reachable_over_streamable_http(running_server):
    """Real URLhaus call, not mocked - gated on URLHAUS_AUTH_KEY so the
    default suite (CI, a clean clone, a judge's machine without the secret)
    never fails on a missing config. Structural assertion only: URLhaus's
    verdict for this URL is external, mutable state (it could get listed
    someday) - not something a test should pin an exact string to."""
    tools, result = call_tool(running_server, "url_reputation", {"url": "https://example.com/"})

    assert "url_reputation" in [t.name for t in tools.tools]
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["url"] == "https://example.com/"
    assert isinstance(payload["available"], bool)
    assert isinstance(payload["listed"], bool)
    assert isinstance(payload["tags"], list)
