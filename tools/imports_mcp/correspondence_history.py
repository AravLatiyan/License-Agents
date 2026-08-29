"""correspondence_history — prior contact via Mailpit's HTTP API (T-022).

Mailpit (the T-060 Range) has no IMAP support at all — only an HTTP API and
SMTP (confirmed against `range/mailpit-api.json`'s full `paths` object and
`range/docker-compose.yml`'s published ports, decided in PLAN.md §6,
2026-08-29). This queries Mailpit's HTTP API only, never IMAP, and never
introduces a separate mailbox service.

`GET /api/v1/messages?limit=` (not `/api/v1/search`) is used deliberately:
Mailpit's search-filter query grammar (`before:`, `after:`, `tag:`, ...) is
referenced only by an external doc link in the vendored spec, not fully
specified there — matching by hand against the documented `MessagesSummary`/
`MessageSummary` response shape avoids depending on unverified query syntax
entirely. `limit` is set generously (`_MESSAGES_FETCH_LIMIT`) since the
Range's own mailbox is demo-scale, not a real production inbox.

Matches on `From` only, not `To`/`Cc`/`Bcc`/`ReplyTo` — this tool answers
"has this address/domain sent us mail before," the signal a suspicious
message's own claimed sender is checked against, not "have we ever emailed
them" (a different, unrelated question this tool doesn't try to answer). A
message has exactly one `From`, so this reads as one sender-domain per
message, never an ambiguous multi-sender case.

Dates come from Mailpit's own `Created` field (its real received time,
RFC3339Nano, already lexicographically sortable as a string) — never from
the fictional narrative dates hand-written into `range/fixtures/*.json`'s
`Received` header text, which Mailpit doesn't parse or trust either.

No `truststore` injection here (unlike domain_intel.py/url_reputation.py):
Mailpit is a local, plain-HTTP-only service (`range/docker-compose.yml`
publishes `8025` with no TLS) — the local-TLS-inspection SSL issue those
modules work around doesn't apply to a plaintext local connection.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

DEFAULT_MAILPIT_URL = "http://localhost:8025"
MAILPIT_TIMEOUT_SECONDS = 10
_MESSAGES_FETCH_LIMIT = 1000

MAX_RESPONSE_BYTES = 2000
_MAX_FIELD_CHARS = 200


def _mailpit_url() -> str:
    """Resolved at call time, not import time, so a test (or a deployment)
    can set it without re-importing the module — same pattern `_smtp.py`'s
    `smtp_target()` and `domain_intel.py`'s `_crtsh_cache_db_path()` already
    use. Falls back to the Range's default on any blank value, not just a
    missing one — `.env.example` ships every var blank, and
    `os.environ.get(k, default)` would otherwise return `""` as-is rather
    than defaulting (the exact `SMTP_HOST` bug Qodo caught on PR #29)."""
    return os.environ.get("MAILPIT_URL", "").strip() or DEFAULT_MAILPIT_URL


def _empty_result(address: str, domain: str) -> dict[str, Any]:
    return {
        "address": address,
        "domain": domain,
        "prior_contact_count": 0,
        "first_seen": None,
        "last_seen": None,
        "domains_used": [],
    }


def _fetch_messages() -> list[dict[str, Any]] | None:
    """Returns the mailbox's messages (newest-first, per Mailpit's own
    documented ordering), or None on any failure — network error, non-200,
    invalid JSON, or a response that doesn't match the documented
    `MessagesSummary` shape. None is the caller's signal to degrade, never
    a raise: Mailpit being unreachable is exactly the kind of upstream
    failure every other `imports-mcp` tool already degrades through
    instead of crashing the mission's evidence gathering.
    """
    try:
        resp = requests.get(
            f"{_mailpit_url()}/api/v1/messages",
            params={"start": 0, "limit": _MESSAGES_FETCH_LIMIT},
            timeout=MAILPIT_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    if not isinstance(data, dict):
        return None

    messages = data.get("messages")
    if not isinstance(messages, list):
        return None

    return messages


def _sender_address_and_domain(message: dict[str, Any]) -> tuple[str, str] | None:
    """Extracts (address, domain) from one MessageSummary's `From` field,
    lowercased for case-insensitive matching — email addresses are
    case-insensitive in the domain part per RFC 5321, and the local part is
    conventionally treated the same way in practice. Returns None for any
    message whose shape doesn't match the documented `Address` struct
    (`{Address, Name}`) — a technically-valid-JSON-but-wrong-shape message
    is skipped, not allowed to crash the whole history computation, the
    same "one malformed item doesn't abort the rest" contract domain_intel's
    RDAP-entities loop and detonate's form-extraction already hold."""
    from_field = message.get("From")
    if not isinstance(from_field, dict):
        return None
    address = from_field.get("Address")
    if not isinstance(address, str) or "@" not in address:
        return None
    address = address.strip().lower()
    domain = address.rsplit("@", 1)[-1]
    if not domain:
        return None
    return address, domain


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """Cap the serialized response at ~max_bytes (Rule 2880706), with an
    explicit `truncated` indicator. `domains_used` is deliberately *not* a
    trim target here, unlike every other tool's list fields: the matching
    rule in `correspondence_history()` can only ever add `domain` itself or
    `address`'s own domain to that set — two short strings at most, by
    construction, never a genuinely long list a real history could grow.
    `address`/`domain` (caller-supplied, echoed back) are the only fields
    actually capable of blowing the budget — the MCP wrapper (`server.py`)
    already bounds their length before this function ever runs, but this
    module is tested and usable independently of that wrapper, so the same
    defense exists here too, matching domain_intel.py's own "stays testable
    with any string a caller passes it directly" precedent.
    `prior_contact_count`/`first_seen`/`last_seen` are never touched — a
    caller branches on those directly. Mirrors the same
    strictly-shrinking-toward-`""` pattern url_reputation's fix established
    (PR #19), reused here from the start."""
    capped = dict(result)
    capped["truncated"] = False
    if len(json.dumps(capped, ensure_ascii=False).encode("utf-8")) <= max_bytes:
        return capped

    omitted: dict[str, Any] = {}
    capped["truncated"] = True
    capped["omitted"] = omitted

    def fits() -> bool:
        return len(json.dumps(capped, ensure_ascii=False).encode("utf-8")) <= max_bytes

    for field in ("address", "domain"):
        value = capped.get(field)
        while isinstance(value, str) and value and not fits():
            value = value[:-_MAX_FIELD_CHARS] if len(value) > _MAX_FIELD_CHARS else ""
            capped[field] = value
            omitted[field] = True
        if fits():
            return capped

    return capped


def correspondence_history(address: str, domain: str) -> dict[str, Any]:
    """Prior contact for `address`/`domain`, queried from Mailpit's own
    mailbox (the Range's captured mail, T-060) — never raises on Mailpit
    being unreachable or returning something unexpected; degrades to the
    same zero-history shape a genuine "never heard from them" answer would
    have, since `CorrespondenceHistory` (`contracts/events.ts`) has no
    `available`/`error` field to signal "unknown" separately from
    "confirmed none" (documented decision, PLAN.md §6).

    A message counts as prior contact if its `From` address exactly equals
    `address`, or if its `From` address's domain exactly equals `domain` —
    both supplied parameters are independent match criteria (an OR), not
    assumed to already correspond to each other. `domains_used` is the
    distinct, sorted set of `From` domains among every matched message —
    normally just `[domain]`, but can include a second domain if `address`
    and `domain` don't actually correspond to the same identity (whichever
    matched pulls its own real domain in, not an invented one).
    """
    address_lower = address.strip().lower()
    domain_lower = domain.strip().lower()

    messages = _fetch_messages()
    if messages is None:
        return _cap_response(_empty_result(address, domain))

    matched_count = 0
    matched_domains: set[str] = set()
    created_dates: list[str] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        sender = _sender_address_and_domain(message)
        if sender is None:
            continue
        sender_address, sender_domain = sender
        if sender_address != address_lower and sender_domain != domain_lower:
            continue

        matched_count += 1
        matched_domains.add(sender_domain)
        created = message.get("Created")
        if isinstance(created, str) and created:
            created_dates.append(created)

    result = {
        "address": address,
        "domain": domain,
        "prior_contact_count": matched_count,
        "first_seen": min(created_dates) if created_dates else None,
        "last_seen": max(created_dates) if created_dates else None,
        "domains_used": sorted(matched_domains),
    }
    return _cap_response(result)
