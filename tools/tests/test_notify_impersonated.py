"""Unit tests for notify_impersonated (T-031) — SMTP mocked, deterministic.

Nothing here opens a socket. `smtplib.SMTP` is patched in every test that
reaches the send path, so the normal suite never depends on a running
Mailpit (the opt-in live test lives in test_server_integration_live.py).
"""

from __future__ import annotations

import json
import smtplib
from unittest.mock import MagicMock, patch

import pytest

import imports_mcp.notify_impersonated as notify_module
from imports_mcp.notify_impersonated import (
    DEFAULT_SMTP_HOST,
    DEFAULT_SMTP_PORT,
    MAX_RESPONSE_BYTES,
    build_message,
    notify_impersonated,
)

ADDRESS = "a.morgan@northgate-trust.example"
EVIDENCE = "mission-001"


@pytest.fixture(autouse=True)
def _clear_smtp_env(monkeypatch):
    """SMTP_HOST/SMTP_PORT/ALLOW_EXTERNAL_SMTP may be set in a developer's .env
    (loaded at import). Clear them so every test measures the *code's* default,
    not the machine's."""
    for var in ("SMTP_HOST", "SMTP_PORT", "ALLOW_EXTERNAL_SMTP"):
        monkeypatch.delenv(var, raising=False)


def _mock_smtp():
    """Patch smtplib.SMTP and hand back the context-manager instance so a test
    can assert on what was actually sent."""
    smtp_instance = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = smtp_instance
    cm.__exit__.return_value = False
    return cm, smtp_instance


# --- the safety property: where does this tool send by default? ------------


def test_default_smtp_target_is_the_range_never_a_real_server():
    """The single most important assertion in this file. With no SMTP_HOST /
    SMTP_PORT configured, this tool must only ever be able to reach the local
    T-060 Mailpit range (range/docker-compose.yml publishes 1025:1025) —
    CLAUDE.md trap #6, "Range mail server only". If someone later changes
    these defaults to a real mail server, this test is the tripwire."""
    assert DEFAULT_SMTP_HOST == "localhost"
    assert DEFAULT_SMTP_PORT == 1025


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_send_connects_to_the_range_by_default(mock_smtp):
    """With no configuration, this tool can only ever reach a local Mailpit.

    Since T-073 it connects to the *already-validated loopback literal*, not
    to the name — handing `smtplib` the name would resolve DNS a second time
    and the second answer can differ from the one the guard approved. The
    reported `smtp_host` still shows the configured name.
    """
    import ipaddress

    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm

    result = notify_impersonated(ADDRESS, EVIDENCE)

    host, port = mock_smtp.call_args[0][0], mock_smtp.call_args[0][1]
    assert ipaddress.ip_address(host).is_loopback, f"connected to {host!r}, not loopback"
    assert port == DEFAULT_SMTP_PORT
    assert result["smtp_host"] == DEFAULT_SMTP_HOST


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_env_vars_override_host_and_port(mock_smtp, monkeypatch):
    """Rewritten for T-073. This test previously set `SMTP_HOST=mailpit.internal`
    — a name that is not the local Range — and asserted the tool dialled it
    anyway. That *was* the defect, written down as an expectation: an
    unguarded override is exactly how a model-supplied address gets real mail
    from a test run (CLAUDE.md trap #6).

    What the test was really for is still worth keeping: the env vars are read
    at call time and do reach `smtplib`. So it now overrides to a Range-valid
    host with a non-default port, and the refusal case has its own test in the
    guard section above.
    """
    import ipaddress

    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", "2525")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert ipaddress.ip_address(mock_smtp.call_args[0][0]).is_loopback
    assert mock_smtp.call_args[0][1] == 2525
    assert result["smtp_host"] == "127.0.0.1"


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_non_numeric_port_falls_back_to_the_range_port(mock_smtp, monkeypatch):
    """A malformed SMTP_PORT must not crash the tool mid-mission, and must not
    silently become port 0 or 25 (25 would be a real outbound MX port)."""
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_PORT", "not-a-port")

    notify_impersonated(ADDRESS, EVIDENCE)

    assert mock_smtp.call_args[0][1] == DEFAULT_SMTP_PORT


# --- the Range guard: never mail a real third party from a test run (T-073) --
#
# The defect this section was written against: notify_impersonated resolved
# SMTP_HOST/SMTP_PORT and handed them straight to smtplib with no loopback
# check and no ALLOW_EXTERNAL_SMTP opt-in — the guard its sibling
# file_abuse_report has carried since T-033. `.env.example` documented the
# opt-in as applying to both tools; only one of them enforced it. This tool
# mails a *model-supplied* address, so an SMTP_HOST pointing at a real relay
# would have put real mail in a real stranger's inbox from a test run
# (CLAUDE.md trap #6, "Range mail server only").


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_refuses_to_send_to_a_non_range_smtp_host(mock_smtp, monkeypatch):
    """The single most important test here. The recipient address is chosen by
    the model; a non-loopback SMTP destination must refuse, not deliver.

    A *structured* refusal, never an exception: this tool sits behind a
    TrueForge licence gate, and raising after a human has granted the licence
    turns a refused send into a broken turn."""
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "smtp.real-mail-provider.example")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["sent"] is False
    assert result["available"] is False
    assert "refused" in result["note"]
    assert result["smtp_host"] == "smtp.real-mail-provider.example"
    mock_smtp.assert_not_called(), "must not even open a connection"


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_explicit_opt_in_allows_an_external_host(mock_smtp, monkeypatch):
    """The opt-in exists so the guard is a safety default, not a dead end —
    but it must be deliberate and explicit. Mirrors file_abuse_report."""
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "smtp.real-mail-provider.example")
    monkeypatch.setenv("ALLOW_EXTERNAL_SMTP", "1")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["sent"] is True
    mock_smtp.assert_called_once()
    assert mock_smtp.call_args[0][0] == "smtp.real-mail-provider.example"


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "TRUE", " "])
@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_only_an_exact_1_enables_the_opt_in(mock_smtp, monkeypatch, value):
    """Anything truthy-looking but not exactly "1" must NOT enable sending."""
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "smtp.real-mail-provider.example")
    monkeypatch.setenv("ALLOW_EXTERNAL_SMTP", value)

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["sent"] is False
    mock_smtp.assert_not_called()


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_unresolvable_host_is_treated_as_unsafe_not_assumed_local(mock_smtp, monkeypatch):
    """A host we cannot prove is loopback must not be assumed safe."""
    monkeypatch.setenv("SMTP_HOST", "no-such-host.invalid")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["sent"] is False
    mock_smtp.assert_not_called()


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_connects_to_validated_literal_not_the_rebindable_name(mock_smtp, monkeypatch):
    """Same reasoning as file_abuse_report's PR #40 finding #2: validating the
    name and then handing the *name* to smtplib resolves DNS twice, and a
    hostile resolver can swap in a routable address between the two answers.
    Connecting to the already-validated loopback literal closes that window.
    The reported `smtp_host` still shows the configured name, which is what an
    operator recognises."""
    import ipaddress

    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "localhost")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    connected = mock_smtp.call_args[0][0]
    assert connected != "localhost", "must not hand smtplib a re-resolvable name"
    assert ipaddress.ip_address(connected).is_loopback
    assert result["smtp_host"] == "localhost"


# --- regressions for Qodo's PR #29 findings #1 and #2 ----------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_blank_smtp_host_falls_back_to_the_range(mock_smtp, monkeypatch, blank):
    """Regression, Qodo PR #29 finding #1. `.env.example` ships `SMTP_HOST=`,
    which python-dotenv loads as a set-but-empty "" — and `os.environ.get(k,
    default)` returns that as-is rather than defaulting. `smtplib.SMTP` only
    connects `if host:`, so a blank host silently made every notification a
    no-op. Anyone following the documented setup path got a tool that never
    delivered. Set-but-empty is tested here, NOT deleted: the original
    fixture deleted the var, which is why the bug survived review.

    Asserts the *connection* is loopback rather than literally "localhost":
    since T-073 the tool dials the validated literal, not the name."""
    import ipaddress

    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", blank)

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert ipaddress.ip_address(mock_smtp.call_args[0][0]).is_loopback
    assert result["smtp_host"] == DEFAULT_SMTP_HOST
    assert result["sent"] is True, "a blank host must fall back to the Range, not no-op"


@pytest.mark.parametrize("bad_port", ["0", "-1", "65536", "99999", "not-a-port", "  "])
@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_unusable_port_never_reaches_smtplib(mock_smtp, monkeypatch, bad_port):
    """Regression, Qodo PR #29 finding #2. `smtplib.SMTP.connect` does
    `if not port: port = self.default_port`, and `default_port` is 25 — the
    real outbound MX port. So `SMTP_PORT=0` escaped the 1025 Mailpit default
    entirely. Out-of-range values are now rejected too, not merely parsed."""
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_PORT", bad_port)

    notify_impersonated(ADDRESS, EVIDENCE)

    used_port = mock_smtp.call_args[0][1]
    assert used_port == DEFAULT_SMTP_PORT
    assert used_port != 25, "must never fall through to smtplib's default SMTP port"
    assert used_port != 0, "port 0 is what makes smtplib choose 25"


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_failure_result_reports_the_host_actually_used_not_the_raw_env(mock_smtp, monkeypatch):
    """The failure path used to re-read SMTP_HOST instead of the resolved
    target, so a blank var would report "" as the host it dialled — a host it
    never dialled. Reporting must match what was actually attempted."""
    monkeypatch.setenv("SMTP_HOST", "")
    mock_smtp.side_effect = ConnectionRefusedError("refused")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["sent"] is False
    assert result["smtp_host"] == DEFAULT_SMTP_HOST


# --- the happy path --------------------------------------------------------


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_successful_send_returns_structured_result(mock_smtp):
    cm, smtp_instance = _mock_smtp()
    mock_smtp.return_value = cm

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["sent"] is True
    assert result["available"] is True
    assert result["address"] == ADDRESS
    assert result["evidence"] == EVIDENCE
    assert result["truncated"] is False
    smtp_instance.send_message.assert_called_once()


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_message_is_addressed_correctly_and_carries_the_evidence_reference(mock_smtp):
    cm, smtp_instance = _mock_smtp()
    mock_smtp.return_value = cm

    notify_impersonated(ADDRESS, EVIDENCE)

    sent = smtp_instance.send_message.call_args[0][0]
    assert sent["To"] == ADDRESS
    assert sent["From"] == notify_module.NOTIFY_FROM
    assert EVIDENCE in sent.get_content()


def test_message_is_plain_text_only_no_html_no_remote_images():
    """CLAUDE.md: never render remote images. A notification warning someone
    they're impersonated must not itself carry a tracking pixel or HTML."""
    message = build_message(ADDRESS, EVIDENCE)

    assert message.get_content_type() == "text/plain"
    body = message.get_content()
    assert "<img" not in body.lower()
    assert "http://" not in body and "https://" not in body


def test_sender_domain_is_reserved_and_unregistrable():
    """§13 rule 5 / T-062: fictional brands only. `.example` is RFC 2606
    reserved, so this sender can never collide with a real domain."""
    assert notify_module.NOTIFY_FROM.endswith(".example")


# --- degradation, not exceptions -------------------------------------------


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_connection_refused_degrades_instead_of_raising(mock_smtp):
    mock_smtp.side_effect = ConnectionRefusedError("connection refused")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["sent"] is False
    assert result["available"] is False
    assert "connection refused" in result["note"]


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_smtp_protocol_error_degrades_instead_of_raising(mock_smtp):
    cm, smtp_instance = _mock_smtp()
    smtp_instance.send_message.side_effect = smtplib.SMTPRecipientsRefused({})
    mock_smtp.return_value = cm

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["sent"] is False
    assert result["available"] is False


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_timeout_degrades_instead_of_raising(mock_smtp):
    mock_smtp.side_effect = TimeoutError("timed out")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["sent"] is False
    assert "timed out" in result["note"]


# --- response-size cap (Rule 2880706) --------------------------------------


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_normal_response_is_not_truncated(mock_smtp):
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["truncated"] is False
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_oversized_evidence_is_truncated_and_flagged(mock_smtp):
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    huge_evidence = "e" * 10_000

    result = notify_impersonated(ADDRESS, huge_evidence)

    assert result["truncated"] is True
    assert len(result["evidence"]) < len(huge_evidence)
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES
    # Structured fields a caller branches on survive truncation.
    assert result["sent"] is True


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_oversized_failure_note_is_truncated_and_flagged(mock_smtp):
    mock_smtp.side_effect = ConnectionRefusedError("x" * 10_000)

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["truncated"] is True
    assert result["sent"] is False
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_oversized_smtp_host_is_truncated_and_flagged(mock_smtp, monkeypatch):
    """Regression, Qodo PR #29 finding #3. `smtp_host` is environment-
    controlled and appears in both the success and failure responses, but was
    missing from the trim list — so a long SMTP_HOST returned ~9KB while
    still reporting truncated: True, i.e. claiming a cap it hadn't applied.
    Same omission url_reputation had on PR #19.

    Needs the T-073 opt-in: a 10,000-character host is not the Range, so
    without ALLOW_EXTERNAL_SMTP=1 the guard refuses and this stops exercising
    the *success* response it was written to cap."""
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "h" * 10_000)
    monkeypatch.setenv("ALLOW_EXTERNAL_SMTP", "1")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["truncated"] is True
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES
    assert len(result["smtp_host"]) < 10_000
    assert result["sent"] is True  # structured fields survive truncation


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_oversized_smtp_host_on_the_failure_path_is_also_capped(mock_smtp, monkeypatch):
    """The opt-in is set for the same reason as the test above: without it the
    T-073 guard refuses before `smtplib` is ever reached, and this would
    silently become a second copy of the refusal test instead of covering the
    SMTP-exception path it is named for."""
    monkeypatch.setenv("SMTP_HOST", "h" * 10_000)
    monkeypatch.setenv("ALLOW_EXTERNAL_SMTP", "1")
    mock_smtp.side_effect = ConnectionRefusedError("refused")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert result["truncated"] is True
    assert result["sent"] is False
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES
