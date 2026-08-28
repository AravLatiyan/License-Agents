"""file_abuse_report — report a malicious domain to its registrar (T-033).

The fourth **gated** action (§10 tool table). `harness/agent.json` already
marks this tool `require_approval_for_tools` (T-034), so TrueForge pauses
the call for a human licence decision before this module runs. Approval is
never checked here — that is the harness's job (CLAUDE.md, "don't rebuild
what the harness already does").

Takes a *domain*, not an address: the abuse mailbox is looked up from RDAP
via the already-merged `domain_intel` (T-020), matching §10's
`file_abuse_report(domain, evidence)` signature.

**Why this tool is guarded harder than notify_impersonated (T-031).**
T-031 mails a fictional `.example` recipient. This one mails whatever RDAP
returns — *a real registrar's real abuse mailbox*. CLAUDE.md trap #6 is
explicit: "Never fire a real abuse report at a real registrar during
testing. Range mail server only." So on top of the shared Range-by-default
SMTP target, this module refuses outright to send unless the resolved SMTP
host is loopback, unless ALLOW_EXTERNAL_SMTP=1 is deliberately set. The
recipient address never influences the host or port — it is only an
envelope field, and no MX is ever resolved.

A missing abuse contact is a normal outcome, not an error: GDPR redacts
them and many ccTLDs publish partial RDAP (§12/§13 — "not published" is a
valid finding, not a crash). That degrades to sent: False with a note.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from imports_mcp._smtp import (
    ALLOW_EXTERNAL_SMTP_ENV,
    DEFAULT_SMTP_HOST,
    DEFAULT_SMTP_PORT,
    MAX_RESPONSE_BYTES,
    NOTIFY_FROM,
    SMTP_TIMEOUT_SECONDS,
    cap_response,
    external_smtp_allowed,
    resolve_range_target,
    is_valid_address,
    smtp_target,
)
from imports_mcp.domain_intel import domain_intel as _domain_intel

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# Every caller-, registry-, or environment-controlled scalar. `abuse_contact`
# comes from RDAP and `smtp_host` from the environment; both are unbounded,
# and omitting one is exactly how a response blew the ~2KB cap while still
# reporting truncated: True (Qodo, PR #29).
_TRIMMABLE_STRING_FIELDS = ("note", "evidence", "domain", "abuse_contact", "smtp_host")


def _result(
    domain: str,
    evidence: str,
    host: str,
    *,
    sent: bool,
    available: bool,
    abuse_contact: str | None,
    note: str,
) -> dict[str, Any]:
    """One shape for every path, success or failure — a caller branches on
    `sent`/`available`, never on which keys happen to be present."""
    return {
        "domain": domain,
        "evidence": evidence,
        "abuse_contact": abuse_contact,
        "sent": sent,
        "available": available,
        "smtp_host": host,
        "note": note,
    }


def _lookup_abuse_contact(domain: str) -> tuple[str | None, str | None]:
    """Return (abuse_contact, failure_note). Reuses the merged domain_intel
    rather than re-implementing RDAP.

    domain_intel never raises — it degrades to available=False with its own
    note — so a down registry becomes a reportable outcome here too.
    """
    try:
        intel = _domain_intel(domain)
    except Exception as exc:  # defensive: domain_intel documents no raise
        return None, f"RDAP lookup failed for {domain}: {exc}"

    rdap = intel.get("rdap") or {}
    if not rdap.get("available"):
        return None, f"RDAP unavailable for {domain}: {rdap.get('note') or 'no detail given'}"

    contact = intel.get("abuse_contact") or rdap.get("abuse_contact")
    if not contact:
        # Normal and common: GDPR redaction, partial ccTLD RDAP (§12/§13).
        return None, f"no abuse contact published in RDAP for {domain}"
    return contact, None


def build_message(domain: str, evidence: str, abuse_contact: str) -> EmailMessage:
    """The report itself. Plain text only — no HTML, no remote images
    (CLAUDE.md), so the report cannot carry a tracker to the registrar."""
    message = EmailMessage()
    message["From"] = NOTIFY_FROM
    message["To"] = abuse_contact
    message["Subject"] = f"Abuse report: phishing infrastructure at {domain}"
    message.set_content(
        "This is an automated abuse report from UNIVERSAL IMPORTS.\n\n"
        f"The domain {domain} was observed in a message our analysis assessed "
        "as phishing. We are reporting it to the abuse contact published for "
        "the domain in RDAP.\n\n"
        f"Our reference for the analysed message: {evidence}\n\n"
        "This report is automated. Evidence for the assessment is available "
        "on request via the reference above.\n"
    )
    return message


def file_abuse_report(domain: str, evidence: str) -> dict[str, Any]:
    """Email an abuse report to the domain's RDAP-published abuse contact.

    Gated: TrueForge holds this call for human approval before it runs
    (T-034). Never raises — every failure path returns `sent: False` with a
    note, same degradation contract as the read-only tools.
    """
    host, port = smtp_target()

    # CLAUDE.md trap #6: never fire a real abuse report at a real registrar.
    # Checked BEFORE the RDAP lookup, not after: if we are not permitted to
    # send at all, there is no reason to query a third-party registry first.
    # `connect_host` is the already-validated loopback literal — connecting
    # to it rather than re-resolving `host` closes the DNS-rebinding window
    # between the check and the connection (Qodo, PR #40).
    connect_host = resolve_range_target(host)
    if connect_host is None:
        if not external_smtp_allowed():
            return cap_response(
                _result(
                    domain, evidence, host,
                    sent=False, available=False, abuse_contact=None,
                    note=(
                        f"refused: SMTP host {host!r} is not the local Range and "
                        f"{ALLOW_EXTERNAL_SMTP_ENV}=1 is not set — an abuse report to a real "
                        "registrar must never be sent from a test run (CLAUDE.md trap #6)"
                    ),
                ),
                _TRIMMABLE_STRING_FIELDS,
            )
        # Deliberate opt-in: dial the operator's host as given.
        connect_host = host

    abuse_contact, failure_note = _lookup_abuse_contact(domain)
    if failure_note is not None:
        return cap_response(
            _result(
                domain, evidence, host,
                sent=False, available=False, abuse_contact=None, note=failure_note,
            ),
            _TRIMMABLE_STRING_FIELDS,
        )

    # RDAP is third-party data. Validate it exactly as strictly as a
    # model-supplied address before it becomes an envelope recipient —
    # a registry field containing a newline or a second address would
    # otherwise inject headers or a hidden recipient.
    if not is_valid_address(abuse_contact):
        return cap_response(
            _result(
                domain, evidence, host,
                sent=False, available=False, abuse_contact=abuse_contact,
                note=f"RDAP abuse contact for {domain} is not a usable email address",
            ),
            _TRIMMABLE_STRING_FIELDS,
        )

    message = build_message(domain, evidence, abuse_contact)
    try:
        with smtplib.SMTP(connect_host, port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        return cap_response(
            _result(
                domain, evidence, host,
                sent=False, available=False, abuse_contact=abuse_contact,
                note=f"SMTP send failed via {host}:{port}: {exc}",
            ),
            _TRIMMABLE_STRING_FIELDS,
        )

    return cap_response(
        _result(
            domain, evidence, host,
            sent=True, available=True, abuse_contact=abuse_contact,
            note=f"abuse report delivered to {host}:{port}",
        ),
        _TRIMMABLE_STRING_FIELDS,
    )
