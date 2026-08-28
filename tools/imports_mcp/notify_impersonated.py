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
Pointing `SMTP_HOST` at a real mail server is what would make this reach a
real person — CLAUDE.md trap #6 ("Range mail server only") applies to this
tool for the same reason it applies to `file_abuse_report`.

Unlike domain_intel/url_reputation this module makes no HTTPS call, so it
does not need the truststore injection those two carry.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

SMTP_TIMEOUT_SECONDS = 10

# The T-060 range (range/docker-compose.yml publishes 1025:1025, no auth).
# These defaults are a safety property, not a convenience: with no .env and
# no exported vars, this tool can only ever reach a local Mailpit. See
# test_notify_impersonated.py, which asserts these values directly.
DEFAULT_SMTP_HOST = "localhost"
DEFAULT_SMTP_PORT = 1025

# Fictional sender — §13 rule 5 / T-062: fictional brands only, never a real
# domain we don't control. `.example` is reserved by RFC 2606 and can never
# be registered, so this address cannot collide with anyone real.
NOTIFY_FROM = "counter-intelligence@universal-imports.example"

# Deliberately stricter than RFC 5322: one @, no whitespace, no routing or
# header-injection characters, a dot in the domain. A tool that emails
# whoever it is told to, off the back of model-generated arguments, should
# reject anything it cannot recognise rather than try to be permissive.
_ADDRESS_RE = re.compile(r"^[^\s@,;:<>\"\\]+@[^\s@,;:<>\"\\]+\.[^\s@,;:<>\"\\]+$")
MAX_ADDRESS_LENGTH = 254  # RFC 5321 §4.5.3.1.3

# Rule 2880706: MCP tool responses stay under ~2KB and signal truncation.
# `note` and `evidence` are the unbounded fields here — `note` can carry an
# smtplib exception message, `evidence` is caller/model-supplied.
MAX_RESPONSE_BYTES = 2000
# Every caller- or environment-controlled scalar, not a hand-picked subset:
# `smtp_host` comes from SMTP_HOST and is as unbounded as the rest, so
# leaving it out let a long host blow the cap while still reporting
# truncated: True (Qodo, PR #29). Same omission url_reputation had on
# PR #19 — the rule covers the whole serialized response.
_TRIMMABLE_STRING_FIELDS = ("note", "evidence", "address", "smtp_host")


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _shrink_string(value: str) -> str:
    """Cuts one chunk off the end, strictly shrinking toward "" so a caller
    looping "shrink until it fits" always terminates — same helper shape as
    url_reputation.py, which had a real non-termination bug when it plateaued
    at a fixed floor instead (§4, PR #19 finding 3+8)."""
    if len(value) <= 200:
        return ""
    return value[:-200]


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """Cap the serialized response at ~max_bytes with an explicit indicator.

    Mirrors url_reputation's `_cap_response`: adds `truncated`, and only when
    something was actually cut, `omitted`. Structured fields (`sent`,
    `available`) are never dropped — those are what a caller branches on.
    Size is re-checked after every step, never assumed.
    """
    capped = dict(result)
    capped["truncated"] = False
    if _serialized_size(capped) <= max_bytes:
        return capped

    omitted: dict[str, Any] = {}
    capped["truncated"] = True
    capped["omitted"] = omitted

    def fits() -> bool:
        return _serialized_size(capped) <= max_bytes

    for field in _TRIMMABLE_STRING_FIELDS:
        value = capped.get(field)
        while isinstance(value, str) and value and not fits():
            value = _shrink_string(value)
            capped[field] = value
            omitted[field] = True
        if fits():
            return capped

    return capped


def _failed(address: str, evidence: str, host: str, note: str) -> dict[str, Any]:
    """Degrade the same way every other imports-mcp tool does: a structured
    `sent: False` plus a note, never an exception. The gate has already been
    granted by a human at this point, so a transport failure is information
    the mission needs back — not a crash that loses the whole turn.

    Takes the already-resolved `host` rather than re-reading SMTP_HOST: the
    env var can be blank or whitespace (see `_smtp_target`), so re-reading it
    here would report a host the tool never actually dialled.
    """
    return {
        "address": address,
        "evidence": evidence,
        "sent": False,
        "available": False,
        "smtp_host": host,
        "note": note,
    }


def _smtp_target() -> tuple[str, int]:
    """Resolve host/port at call time, not import time, so a test (or a
    deployment) can set them without re-importing the module.

    Both halves fall back to the Range on *any* unusable value, not just a
    missing one. Two ways that mattered, both found by Qodo on PR #29:

    - A blank host. `.env.example` ships `SMTP_HOST=` (so the key is
      documented), and python-dotenv loads that as `""` — a set-but-empty
      value, which `os.environ.get(k, default)` returns as-is rather than
      defaulting. `smtplib.SMTP` only connects `if host:`, so `""` silently
      turned every notification into a no-op with `sent: False`. Anyone
      copying `.env.example` — the documented setup path — got a tool that
      never delivered.

    - A port of 0 (or out of range). `smtplib.SMTP.connect` does
      `if not port: port = self.default_port`, and `default_port` is **25**
      — the real outbound MX port. So `SMTP_PORT=0` quietly escaped the
      1025 Mailpit default. Ports are now range-checked, not merely parsed:
      0, negatives, and anything above 65535 fall back to the Range.
    """
    host = os.environ.get("SMTP_HOST", "").strip() or DEFAULT_SMTP_HOST

    raw_port = os.environ.get("SMTP_PORT", "").strip()
    try:
        port = int(raw_port) if raw_port else DEFAULT_SMTP_PORT
    except ValueError:
        port = DEFAULT_SMTP_PORT
    if not 1 <= port <= 65535:
        # Never hand smtplib a falsy or nonsensical port — see above.
        port = DEFAULT_SMTP_PORT
    return host, port


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
