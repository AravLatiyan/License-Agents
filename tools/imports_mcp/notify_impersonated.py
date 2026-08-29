"""notify_impersonated — tell the impersonated party, over SMTP (T-031).

One of the four **gated** actions (§10 tool table, CLAUDE.md "four
sequential per-tool-call gates"). `harness/agent.json` already marks this
tool `require_approval_for_tools` (T-034), so TrueForge pauses the call for
a human licence decision before this module ever runs. Nothing here checks
for approval itself — that is the harness's job, and re-implementing it
would be exactly the "don't rebuild what the harness already does" mistake.

**This sends real mail, so it is deliberately Range-only by default.**
`SMTP_HOST`/`SMTP_PORT` default to the T-060 Mailpit range
(`localhost:1025`, published in `range/docker-compose.yml`, no auth). We
never resolve the recipient's MX: `smtplib` connects to the configured host
and the recipient address is only an envelope field, so a fictional address
like `a.morgan@northgate-trust.example` goes to Mailpit and stops there.

The SMTP plumbing (target resolution, address validation, response capping)
lives in `_smtp.py`, shared with file_abuse_report (T-033) — extracted, not
copied, so the port-0/blank-host guards cannot drift between the two. The
names re-exported below are kept because this module's public surface is
imported by `server.py` and its test suite.

Unlike domain_intel/url_reputation this module makes no HTTPS call, so it
does not need the truststore injection those two carry.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from imports_mcp._smtp import (
    DEFAULT_SMTP_HOST,
    DEFAULT_SMTP_PORT,
    MAX_ADDRESS_LENGTH,
    MAX_RESPONSE_BYTES,
    NOTIFY_FROM,
    SMTP_TIMEOUT_SECONDS,
    _ADDRESS_RE,
    cap_response,
    serialized_size,
    shrink_string,
    smtp_target,
)

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

__all__ = [
    "DEFAULT_SMTP_HOST",
    "DEFAULT_SMTP_PORT",
    "MAX_ADDRESS_LENGTH",
    "MAX_RESPONSE_BYTES",
    "NOTIFY_FROM",
    "SMTP_TIMEOUT_SECONDS",
    "build_message",
    "notify_impersonated",
]

# Every caller- or environment-controlled scalar, not a hand-picked subset:
# `smtp_host` comes from SMTP_HOST and is as unbounded as the rest (Qodo,
# PR #29).
_TRIMMABLE_STRING_FIELDS = ("note", "evidence", "address", "smtp_host")

# Thin aliases so this module's existing internal surface (and its tests)
# keep working after the helpers moved into _smtp.py.
_serialized_size = serialized_size
_shrink_string = shrink_string
_smtp_target = smtp_target


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    return cap_response(result, _TRIMMABLE_STRING_FIELDS, max_bytes)


def _failed(address: str, evidence: str, host: str, note: str) -> dict[str, Any]:
    """Degrade the same way every other imports-mcp tool does: a structured
    `sent: False` plus a note, never an exception. The gate has already been
    granted by a human at this point, so a transport failure is information
    the mission needs back — not a crash that loses the whole turn.

    Takes the already-resolved `host` rather than re-reading SMTP_HOST: the
    env var can be blank or whitespace (see `_smtp.smtp_target`), so
    re-reading it here would report a host the tool never actually dialled.
    """
    return {
        "address": address,
        "evidence": evidence,
        "sent": False,
        "available": False,
        "smtp_host": host,
        "note": note,
    }


def build_message(address: str, evidence: str) -> EmailMessage:
    """The notification itself. Plain text only — never HTML, and never a
    remote image (CLAUDE.md: "never render remote images"), so nothing in
    this mail can phone home or track the recipient we are trying to protect.
    """
    message = EmailMessage()
    message["From"] = NOTIFY_FROM
    message["To"] = address
    message["Subject"] = "Someone is impersonating you in email"
    message.set_content(
        "This is an automated notification from UNIVERSAL IMPORTS.\n\n"
        "We analysed a suspicious message that appears to impersonate you or "
        "your organisation. You are not the sender and no action is required "
        "of you — this is a courtesy notice so you can warn colleagues who "
        "may receive a similar message.\n\n"
        f"Our reference for the analysed message: {evidence}\n\n"
        "We will never ask you for a password, a payment, or a code in reply "
        "to this notice. Treat any message that does as a further attempt.\n"
    )
    return message


def notify_impersonated(address: str, evidence: str) -> dict[str, Any]:
    """Email the impersonated party that they are being impersonated.

    Gated: TrueForge holds this call for human approval before it runs
    (T-034). Never raises on a transport failure — returns `sent: False`
    with a note instead, same degradation contract as the read-only tools.
    """
    host, port = _smtp_target()
    message = build_message(address, evidence)

    try:
        with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        # OSError covers connection-refused/DNS/timeout; SMTPException covers
        # protocol-level rejections. Either way the mission gets a result,
        # not a lost turn.
        return _cap_response(
            _failed(address, evidence, host, f"SMTP send failed via {host}:{port}: {exc}")
        )

    return _cap_response(
        {
            "address": address,
            "evidence": evidence,
            "sent": True,
            "available": True,
            "smtp_host": host,
            "note": f"notification delivered to {host}:{port}",
        }
    )
