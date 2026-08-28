"""Unit tests for file_abuse_report (T-033) — SMTP and RDAP both mocked.

Nothing here opens a socket or touches a real registry. The recipient in a
real run is a genuine registrar abuse mailbox, so these tests are also the
proof that CLAUDE.md trap #6 ("never fire a real abuse report at a real
registrar during testing") cannot be violated by accident.
"""

from __future__ import annotations

import json
import smtplib
from unittest.mock import MagicMock, patch

import pytest

import imports_mcp.file_abuse_report as far
from imports_mcp.file_abuse_report import (
    DEFAULT_SMTP_HOST,
    DEFAULT_SMTP_PORT,
    MAX_RESPONSE_BYTES,
    build_message,
    file_abuse_report,
)

DOMAIN = "northgate-trust-finance.example"
EVIDENCE = "mission-001"
ABUSE = "abuse@registrar.example"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """SMTP_* / ALLOW_EXTERNAL_SMTP may be set in a developer's .env (loaded at
    import). Clear them so each test measures the code's default, not the
    machine's."""
    for var in ("SMTP_HOST", "SMTP_PORT", "ALLOW_EXTERNAL_SMTP"):
        monkeypatch.delenv(var, raising=False)


def _mock_smtp():
    smtp_instance = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = smtp_instance
    cm.__exit__.return_value = False
    return cm, smtp_instance


def _intel(abuse_contact=ABUSE, available=True, note=None):
    """Shape mirrors the merged domain_intel(): nested rdap/cert sections plus
    the flat top-level mirrors added in PR #19."""
    return {
        "domain": DOMAIN,
        "rdap": {
            "available": available,
            "registrar": "Example Registrar",
            "registration_date": "2026-08-01T00:00:00Z",
            "abuse_contact": abuse_contact,
            "note": note,
        },
        "cert": {"available": True, "earliest_seen": None, "age_days": None, "note": None},
        "abuse_contact": abuse_contact,
        "truncated": False,
    }


# --- happy path ------------------------------------------------------------


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_successful_report_is_sent_to_the_rdap_abuse_contact(mock_intel, mock_smtp):
    mock_intel.return_value = _intel()
    cm, smtp_instance = _mock_smtp()
    mock_smtp.return_value = cm

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is True
    assert result["available"] is True
    assert result["abuse_contact"] == ABUSE
    assert result["domain"] == DOMAIN
    assert result["truncated"] is False
    sent = smtp_instance.send_message.call_args[0][0]
    assert sent["To"] == ABUSE
    assert DOMAIN in sent["Subject"]
    assert EVIDENCE in sent.get_content()


@patch("imports_mcp.file_abuse_report._domain_intel")
def test_abuse_contact_comes_from_rdap_not_from_the_caller(mock_intel):
    """The signature takes a domain, never an address — the recipient must be
    whatever RDAP published, so a model cannot choose who gets mailed."""
    mock_intel.return_value = _intel(abuse_contact="someone-else@registry.example")
    cm, smtp_instance = _mock_smtp()
    with patch("imports_mcp.file_abuse_report.smtplib.SMTP", return_value=cm):
        result = file_abuse_report(DOMAIN, EVIDENCE)
    assert result["abuse_contact"] == "someone-else@registry.example"
    mock_intel.assert_called_once_with(DOMAIN)


def test_report_is_plain_text_only_no_html_no_remote_images():
    message = build_message(DOMAIN, EVIDENCE, ABUSE)
    assert message.get_content_type() == "text/plain"
    body = message.get_content()
    assert "<img" not in body.lower()
    assert "http://" not in body and "https://" not in body


# --- the safety guard: never mail a real registrar from a test run ---------


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_default_destination_is_the_range(mock_intel, mock_smtp):
    """With no configuration, this tool can only ever reach a local Mailpit."""
    mock_intel.return_value = _intel()
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm

    file_abuse_report(DOMAIN, EVIDENCE)

    assert (mock_smtp.call_args[0][0], mock_smtp.call_args[0][1]) == (
        DEFAULT_SMTP_HOST,
        DEFAULT_SMTP_PORT,
    )


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_refuses_to_send_to_a_non_range_smtp_host(mock_intel, mock_smtp, monkeypatch):
    """The single most important test here. The recipient is a real
    registrar's abuse mailbox; CLAUDE.md trap #6 forbids mailing one during
    testing. A non-loopback SMTP destination must refuse, not deliver."""
    mock_intel.return_value = _intel()
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "smtp.real-registrar.example")

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is False
    assert "refused" in result["note"]
    mock_smtp.assert_not_called(), "must not even open a connection"


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_explicit_opt_in_allows_an_external_host(mock_intel, mock_smtp, monkeypatch):
    """The opt-in exists so the guard is a safety default, not a dead end —
    but it must be deliberate and explicit."""
    mock_intel.return_value = _intel()
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "smtp.real-registrar.example")
    monkeypatch.setenv("ALLOW_EXTERNAL_SMTP", "1")

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is True
    mock_smtp.assert_called_once()


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "TRUE", " "])
@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_only_an_exact_1_enables_the_opt_in(mock_intel, mock_smtp, monkeypatch, value):
    """Anything truthy-looking but not exactly "1" must NOT enable sending."""
    mock_intel.return_value = _intel()
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "smtp.real-registrar.example")
    monkeypatch.setenv("ALLOW_EXTERNAL_SMTP", value)

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is False
    mock_smtp.assert_not_called()


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_loopback_ip_counts_as_the_range(mock_intel, mock_smtp, monkeypatch):
    mock_intel.return_value = _intel()
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is True


@patch("imports_mcp.file_abuse_report._domain_intel")
def test_unresolvable_host_is_treated_as_unsafe_not_assumed_local(mock_intel, monkeypatch):
    """A host we cannot prove is loopback must not be assumed safe."""
    mock_intel.return_value = _intel()
    monkeypatch.setenv("SMTP_HOST", "no-such-host.invalid")

    with patch("imports_mcp.file_abuse_report.smtplib.SMTP") as mock_smtp:
        result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is False
    mock_smtp.assert_not_called()


# --- RDAP-side degradation, never exceptions -------------------------------


@patch("imports_mcp.file_abuse_report._domain_intel")
def test_missing_abuse_contact_degrades_gracefully(mock_intel):
    """GDPR redacts abuse contacts and many ccTLDs publish partial RDAP —
    §12/§13: "not published" is a valid finding, not a crash."""
    mock_intel.return_value = _intel(abuse_contact=None)

    with patch("imports_mcp.file_abuse_report.smtplib.SMTP") as mock_smtp:
        result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is False
    assert result["available"] is False
    assert result["abuse_contact"] is None
    assert "no abuse contact published" in result["note"]
    mock_smtp.assert_not_called()


@patch("imports_mcp.file_abuse_report._domain_intel")
def test_rdap_unavailable_degrades_gracefully(mock_intel):
    mock_intel.return_value = _intel(available=False, note="RDAP returned HTTP 503")

    with patch("imports_mcp.file_abuse_report.smtplib.SMTP") as mock_smtp:
        result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is False
    assert "RDAP unavailable" in result["note"]
    mock_smtp.assert_not_called()


@patch("imports_mcp.file_abuse_report._domain_intel")
def test_domain_intel_raising_is_contained(mock_intel):
    """domain_intel documents that it never raises, but this tool must not
    lose the whole turn if that contract is ever broken."""
    mock_intel.side_effect = RuntimeError("unexpected")

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is False
    assert "RDAP lookup failed" in result["note"]


@pytest.mark.parametrize(
    "bad_contact",
    [
        "not-an-address",
        "abuse@registrar.example, attacker@evil.example",
        "abuse@registrar.example\nBcc: attacker@evil.example",
        "abuse@registrar.example;x@y.example",
        "<abuse@registrar.example>",
        "a" * 250 + "@x.example",
    ],
)
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_malformed_rdap_abuse_contact_is_refused(mock_intel, bad_contact):
    """RDAP is third-party data. A registry field carrying a newline or a
    second address would inject headers or a hidden recipient, so it is
    validated exactly as strictly as a model-supplied address."""
    mock_intel.return_value = _intel(abuse_contact=bad_contact)

    with patch("imports_mcp.file_abuse_report.smtplib.SMTP") as mock_smtp:
        result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is False
    assert "not a usable email address" in result["note"]
    mock_smtp.assert_not_called()


# --- SMTP-side degradation -------------------------------------------------


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_connection_refused_degrades_instead_of_raising(mock_intel, mock_smtp):
    mock_intel.return_value = _intel()
    mock_smtp.side_effect = ConnectionRefusedError("connection refused")

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is False
    assert "connection refused" in result["note"]


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_smtp_protocol_error_degrades_instead_of_raising(mock_intel, mock_smtp):
    mock_intel.return_value = _intel()
    cm, smtp_instance = _mock_smtp()
    smtp_instance.send_message.side_effect = smtplib.SMTPRecipientsRefused({})
    mock_smtp.return_value = cm

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["sent"] is False


# --- response-size cap (Rule 2880706) --------------------------------------


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_normal_response_is_not_truncated(mock_intel, mock_smtp):
    mock_intel.return_value = _intel()
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["truncated"] is False
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_oversized_evidence_is_truncated_and_flagged(mock_intel, mock_smtp):
    mock_intel.return_value = _intel()
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm

    result = file_abuse_report(DOMAIN, "e" * 10_000)

    assert result["truncated"] is True
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES
    assert result["sent"] is True


@patch("imports_mcp.file_abuse_report.smtplib.SMTP")
@patch("imports_mcp.file_abuse_report._domain_intel")
def test_oversized_smtp_host_is_capped(mock_intel, mock_smtp, monkeypatch):
    """smtp_host is environment-controlled; it must be inside the cap, not
    outside it (the exact omission Qodo caught on PR #29)."""
    mock_intel.return_value = _intel()
    cm, _ = _mock_smtp()
    mock_smtp.return_value = cm
    monkeypatch.setenv("SMTP_HOST", "h" * 10_000)

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["truncated"] is True
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES


@patch("imports_mcp.file_abuse_report._domain_intel")
def test_oversized_rdap_note_is_capped(mock_intel):
    """The failure note can embed a registry-supplied string."""
    mock_intel.return_value = _intel(available=False, note="x" * 10_000)

    result = file_abuse_report(DOMAIN, EVIDENCE)

    assert result["truncated"] is True
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES


# --- architecture -----------------------------------------------------------


def test_module_never_implements_its_own_approval_check():
    """T-034 gates this tool at the harness. A second, in-tool approval check
    would be the "don't rebuild what the harness already does" mistake — and
    worse, could diverge from the real gate."""
    source = __import__("inspect").getsource(far)
    code_lines = [
        line for line in source.splitlines()
        if not line.strip().startswith("#") and "approval is never checked" not in line.lower()
    ]
    code = "\n".join(code_lines)
    assert "def approve" not in code
    assert "require_approval" not in code.replace("require_approval_for_tools", "")
