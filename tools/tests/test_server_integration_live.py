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

# notify_impersonated (T-031) needs the T-060 Range running
# (`docker compose up` in range/: Mailpit on 1025 SMTP + 8025 HTTP). Opt in
# explicitly — the default suite must never require Docker to be running.
RUN_LIVE_MAILPIT_TESTS = os.environ.get("RUN_LIVE_MAILPIT_TESTS") == "1"
# .strip() or default, not .get(k, default) - a blank MAILPIT_URL= (what
# .env.example ships) is a *set* env var, so .get()'s default never applies
# and this would silently resolve to "" (Qodo, PR #64 review, "Blank
# mailpit url breaks live test") - the same fallback semantics
# correspondence_history._mailpit_url() already uses, and the exact
# SMTP_HOST bug class Qodo caught on PR #29.
MAILPIT_HTTP = os.environ.get("MAILPIT_URL", "").strip() or "http://localhost:8025"


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


@pytest.mark.skipif(
    not RUN_LIVE_MAILPIT_TESTS,
    reason="needs the T-060 Range running (`docker compose up` in range/) for a real SMTP "
    "delivery - opt in with RUN_LIVE_MAILPIT_TESTS=1; the deterministic behaviour is already "
    "covered by the mocked tests in test_notify_impersonated.py",
)
def test_notify_impersonated_delivers_into_mailpit(running_server):
    """Real SMTP send through the real transport, then confirm via Mailpit's
    own HTTP API that the message actually landed (T-031).

    Safe by construction: the recipient is a `.example` address (RFC 2606,
    unregistrable) and the tool only ever connects to the configured
    SMTP_HOST, which defaults to the local Range - no real MX is resolved.
    """
    import urllib.request

    address = "a.morgan@northgate-trust.example"
    evidence = "mission-live-check"

    tools, result = call_tool(
        running_server, "notify_impersonated", {"address": address, "evidence": evidence}
    )

    assert "notify_impersonated" in [t.name for t in tools.tools]
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["sent"] is True
    assert payload["address"] == address

    # Confirm delivery independently rather than trusting the tool's own
    # return value - search Mailpit for the message it should have received.
    with urllib.request.urlopen(f"{MAILPIT_HTTP}/api/v1/messages", timeout=10) as response:
        inbox = json.loads(response.read())
    subjects = [m.get("Subject", "") for m in inbox.get("messages", [])]
    assert any("impersonating you" in s for s in subjects), (
        f"no impersonation notice found in Mailpit; subjects seen: {subjects[:5]}"
    )


@pytest.mark.skipif(
    not RUN_LIVE_MAILPIT_TESTS,
    reason="needs the T-060 Range running (`docker compose up` in range/) to seed a real "
    "message and query it back over Mailpit's HTTP API - opt in with RUN_LIVE_MAILPIT_TESTS=1; "
    "the deterministic matching/degradation behaviour is already covered by the mocked tests "
    "in test_correspondence_history.py",
)
def test_correspondence_history_finds_a_message_seeded_directly_into_mailpit(running_server):
    """Seeds one message straight into Mailpit via its own HTTP API (T-022) -
    the same /api/v1/send endpoint range/seed.sh uses, no IMAP anywhere -
    then confirms correspondence_history actually finds it back, proving
    the real Mailpit integration end to end, not just the mocked unit tests.
    """
    import urllib.request

    # A domain/address seen nowhere else - not shared with any range/fixtures/
    # sender (northgate-trust*/meridian-courier*/universal-imports* are all
    # already heavily seeded by seed.sh, T-060). correspondence_history
    # matches on address-OR-domain, so reusing one of those would let this
    # test's assertions pass on pre-existing fixture mail alone, proving
    # nothing about the seed call this test actually makes (Qodo, PR #64
    # review, "Seed lookup matches stale mail").
    address = "seed-proof@t022-live-check.example"
    domain = "t022-live-check.example"
    send_body = json.dumps(
        {
            "From": {"Email": address, "Name": "Live Check"},
            "To": [{"Email": "employee@universal-imports.example"}],
            "Subject": "correspondence_history live-check seed",
            "Text": "seeded directly for test_correspondence_history_finds_a_message_seeded_directly_into_mailpit",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{MAILPIT_HTTP}/api/v1/send",
        data=send_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10):
        pass

    tools, result = call_tool(
        running_server, "correspondence_history", {"address": address, "domain": domain}
    )

    assert "correspondence_history" in [t.name for t in tools.tools]
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["prior_contact_count"] >= 1
    assert payload["domains_used"] == [domain]
    assert payload["first_seen"] is not None
    assert payload["last_seen"] is not None


# NOTE (T-033, Qodo PR #40 finding #3): there is deliberately NO live
# file_abuse_report test here. Calling that tool over the wire performs a real
# RDAP lookup against the production rdap.org service, which is third-party
# infrastructure this suite has no business querying on every opt-in run — and
# the test could never have demonstrated a delivery anyway, because a reserved
# .example domain publishes no abuse contact, so its own assertion was
# `sent: False`. It cost a production API call to prove nothing. The tool's
# behaviour is fully covered by the mocked tests in test_file_abuse_report.py,
# which mock RDAP and SMTP both.
