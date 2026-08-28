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
    """SMTP_HOST/SMTP_PORT may be set in a developer's .env (loaded at import).
    Clear them so every test measures the *code's* default, not the machine's."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)


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
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm

    notify_impersonated(ADDRESS, EVIDENCE)

    host, port = mock_smtp.call_args[0][0], mock_smtp.call_args[0][1]
    assert (host, port) == ("localhost", 1025)


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_env_vars_override_host_and_port(mock_smtp, monkeypatch):
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "mailpit.internal")
    monkeypatch.setenv("SMTP_PORT", "2525")

    result = notify_impersonated(ADDRESS, EVIDENCE)

    assert (mock_smtp.call_args[0][0], mock_smtp.call_args[0][1]) == ("mailpit.internal", 2525)
    assert result["smtp_host"] == "mailpit.internal"


@patch("imports_mcp.notify_impersonated.smtplib.SMTP")
def test_non_numeric_port_falls_back_to_the_range_port(mock_smtp, monkeypatch):
    """A malformed SMTP_PORT must not crash the tool mid-mission, and must not
    silently become port 0 or 25 (25 would be a real outbound MX port)."""
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_PORT", "not-a-port")

    notify_impersonated(ADDRESS, EVIDENCE)

    assert mock_smtp.call_args[0][1] == DEFAULT_SMTP_PORT


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
