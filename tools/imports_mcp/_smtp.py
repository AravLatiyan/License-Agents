"""Shared SMTP + response-shaping helpers for the gated action tools.

Extracted from notify_impersonated.py (T-031) when file_abuse_report (T-033)
needed the same machinery. Deliberately extracted rather than copied: the
port-0 guard below exists because `smtplib` maps port 0 to **25**, the real
outbound MX port (Qodo, PR #29). Two copies of a safety guard drift; one
does not.

Nothing here knows about approvals. TrueForge gates these tools via
`require_approval_for_tools` in harness/agent.json (T-034) and pauses the
call before any of this runs — re-implementing that check in-tool would be
the "don't rebuild what the harness already does" mistake (CLAUDE.md).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import threading
from typing import Any, Iterable

SMTP_TIMEOUT_SECONDS = 10

# Bounds the *name resolution* that happens before any socket exists.
# `socket.setdefaulttimeout()` does NOT cover this: it governs operations on a
# socket, while `getaddrinfo` is a blocking call into the platform resolver
# made before one is created. So SMTP_TIMEOUT_SECONDS never applies to it, and
# a stalled resolver could hang `file_abuse_report` indefinitely (Qodo, found
# during O3's T-041 review of PR #58). Deliberately shorter than the SMTP
# timeout: resolving the Range should be near-instant, and the whole point is
# to give up early and refuse rather than wait.
DNS_TIMEOUT_SECONDS = 5

# Thread-name prefix for the bounded resolver's workers. Named so a test can
# find the worker and assert it is a daemon.
_DNS_WORKER_PREFIX = "smtp-dns-resolve"

# The T-060 range (range/docker-compose.yml publishes 1025:1025, no auth).
# These defaults are a safety property, not a convenience: with no .env and
# no exported vars, these tools can only ever reach a local Mailpit.
DEFAULT_SMTP_HOST = "localhost"
DEFAULT_SMTP_PORT = 1025

# Fictional sender — §13 rule 5 / T-062: fictional brands only. `.example` is
# reserved by RFC 2606 and can never be registered, so this address cannot
# collide with anyone real.
NOTIFY_FROM = "counter-intelligence@universal-imports.example"

# Deliberately stricter than RFC 5322: one @, no whitespace, no routing or
# header-injection characters, a dot in the domain. These tools mail whoever
# they are told to, off model-generated or registry-supplied arguments, so
# they reject anything unrecognised rather than trying to be permissive.
_ADDRESS_RE = re.compile(r"^[^\s@,;:<>\"\\]+@[^\s@,;:<>\"\\]+\.[^\s@,;:<>\"\\]+$")
MAX_ADDRESS_LENGTH = 254  # RFC 5321 §4.5.3.1.3

# Rule 2880706: MCP tool responses stay under ~2KB and signal truncation.
MAX_RESPONSE_BYTES = 2000

# Deliberate, documented opt-in for sending outside the Range. Off by default.
# Only `file_abuse_report` enforces this (see `is_range_destination`) — its
# recipient is a *real registrar's* abuse mailbox straight from RDAP, which is
# exactly what CLAUDE.md trap #6 forbids mailing during testing.
ALLOW_EXTERNAL_SMTP_ENV = "ALLOW_EXTERNAL_SMTP"


def serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def shrink_string(value: str) -> str:
    """Cuts one chunk off the end, strictly shrinking toward "" so a caller
    looping "shrink until it fits" always terminates — url_reputation had a
    real non-termination bug when it plateaued at a fixed floor instead
    (PR #19 finding 3+8)."""
    if len(value) <= 200:
        return ""
    return value[:-200]


def cap_response(
    result: dict[str, Any],
    trimmable_fields: Iterable[str],
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> dict[str, Any]:
    """Cap the serialized response at ~max_bytes with an explicit indicator.

    Adds `truncated`, and only when something was actually cut, `omitted`.
    Structured fields (`sent`, `available`) are never dropped — those are what
    a caller branches on. Size is re-checked after every step, never assumed.

    `trimmable_fields` must include every caller- or environment-controlled
    scalar, not a hand-picked subset: omitting one let a long SMTP_HOST blow
    the cap while still reporting truncated: True (Qodo, PR #29).
    """
    capped = dict(result)
    capped["truncated"] = False
    if serialized_size(capped) <= max_bytes:
        return capped

    omitted: dict[str, Any] = {}
    capped["truncated"] = True
    capped["omitted"] = omitted

    def fits() -> bool:
        return serialized_size(capped) <= max_bytes

    for field in trimmable_fields:
        value = capped.get(field)
        while isinstance(value, str) and value and not fits():
            value = shrink_string(value)
            capped[field] = value
            omitted[field] = True
        if fits():
            return capped

    return capped


def is_valid_address(address: Any) -> bool:
    """One address, no header-injection or routing characters, length-bounded.

    Takes `Any`, not `str`, on purpose: callers feed this third-party data.
    RDAP hands back whatever the registry published, and a non-string there
    (a list, a dict, a number) used to raise TypeError out of `re.match` and
    break the "this tool never raises" contract (Qodo, PR #40).
    """
    if not isinstance(address, str):
        return False
    return bool(address) and len(address) <= MAX_ADDRESS_LENGTH and bool(_ADDRESS_RE.match(address))


def smtp_target() -> tuple[str, int]:
    """Resolve host/port at call time, not import time, so a test (or a
    deployment) can set them without re-importing the module.

    Both halves fall back to the Range on *any* unusable value, not just a
    missing one. Two ways that mattered, both found by Qodo on PR #29:

    - A blank host. `.env.example` ships `SMTP_HOST=`, python-dotenv loads
      that as `""`, and `os.environ.get(k, default)` returns it as-is rather
      than defaulting. `smtplib.SMTP` only connects `if host:`, so `""`
      silently turned every send into a no-op.
    - A port of 0 (or out of range). `smtplib.SMTP.connect` does
      `if not port: port = self.default_port`, and `default_port` is **25** —
      the real outbound MX port. Ports are range-checked, not merely parsed.
    """
    host = os.environ.get("SMTP_HOST", "").strip() or DEFAULT_SMTP_HOST

    raw_port = os.environ.get("SMTP_PORT", "").strip()
    try:
        port = int(raw_port) if raw_port else DEFAULT_SMTP_PORT
    except ValueError:
        port = DEFAULT_SMTP_PORT
    if not 1 <= port <= 65535:
        port = DEFAULT_SMTP_PORT
    return host, port


def external_smtp_allowed() -> bool:
    """The deliberate opt-in. Anything other than an explicit "1" is off."""
    return os.environ.get(ALLOW_EXTERNAL_SMTP_ENV, "").strip() == "1"


def _getaddrinfo_bounded(host: str, timeout_seconds: float) -> list | None:
    """`socket.getaddrinfo(host, None)` with a bounded wait for the *caller*.

    Returns the address list, or **None** on timeout, resolver error, or an
    empty answer — one indistinguishable "could not resolve this" outcome, so
    every failure mode reaches the same fail-closed path in the caller.

    Why a thread rather than a socket timeout: `getaddrinfo` is a blocking
    call into the platform resolver, made before any socket exists, so
    `socket.setdefaulttimeout()` does not bound it. There is no portable way
    to cancel an in-flight lookup either, so the worker is left to finish on
    its own and marked **daemon** — it can never keep the process alive, and
    the caller stops waiting at the deadline regardless.

    This deliberately calls `socket.getaddrinfo` through the module-level name
    rather than caching it, so `detonate.py`'s import-time DNS-pinning wrapper
    stays in effect. That wrapper keys its pin on `threading.local()`, and
    this worker is a fresh thread that never sets one, so the lookup falls
    through to the real resolver exactly as it does today — no pin is read,
    set, or cleared here, and `detonate`'s thread-local semantics are
    untouched.
    """
    result: dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["infos"] = socket.getaddrinfo(host, None)
        except Exception:
            # Any resolver failure is just "could not resolve" to the caller;
            # it must never escape this thread. socket.gaierror and
            # UnicodeError are both covered here (OSError/ValueError subclasses).
            result["error"] = True

    worker = threading.Thread(
        target=_worker, name=f"{_DNS_WORKER_PREFIX}-{host}", daemon=True
    )
    worker.start()
    worker.join(timeout_seconds)

    if worker.is_alive():
        # Still resolving past the deadline. Abandon it (daemon, so it cannot
        # block shutdown) and fail closed.
        return None
    if "error" in result:
        return None
    return result.get("infos") or None


def resolve_range_target(host: str) -> str | None:
    """Resolve `host` and return a loopback IP **literal** to connect to, or
    None if it is not provably the local Range.

    Returning the literal (rather than a bool) is the point: checking the
    name and then handing the *name* to `smtplib` resolves DNS twice, and the
    second answer can differ from the first — classic DNS rebinding, and the
    caller would connect somewhere the guard never approved (Qodo, PR #40).
    Connecting to the already-validated address closes that window.

    Resolves the *SMTP host* only, never an MX record for the recipient.
    Resolution failure is NOT-Range: a host we cannot prove is local must not
    be assumed safe. That now includes a resolver that simply never answers —
    the lookup is bounded by `DNS_TIMEOUT_SECONDS` and a timeout fails closed
    down this same path, rather than hanging the gated tool forever.
    """
    infos = _getaddrinfo_bounded(host, DNS_TIMEOUT_SECONDS)
    if not infos:
        return None

    validated: str | None = None
    for info in infos:
        address = info[4][0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return None
        if not parsed.is_loopback:
            # Every answer must be loopback: a name resolving to both a
            # loopback and a routable address must not be treated as local.
            return None
        if validated is None:
            validated = address
    return validated


def is_range_destination(host: str) -> bool:
    """Convenience wrapper for callers that only need the yes/no."""
    return resolve_range_target(host) is not None
