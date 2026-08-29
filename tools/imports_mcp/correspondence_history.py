"""correspondence_history — prior contact via Mailpit's HTTP API (T-022).

Mailpit (the T-060 Range) has no IMAP support at all — only an HTTP API and
SMTP (confirmed against `range/mailpit-api.json`'s full `paths` object and
`range/docker-compose.yml`'s published ports, decided in PLAN.md §6,
2026-08-29). This queries Mailpit's HTTP API only, never IMAP, and never
introduces a separate mailbox service.

`GET /api/v1/messages` (not `/api/v1/search`) is used deliberately:
Mailpit's search-filter query grammar (`before:`, `after:`, `tag:`, ...) is
referenced only by an external doc link in the vendored spec, not fully
specified there — matching by hand against the documented `MessagesSummary`/
`MessageSummary` response shape avoids depending on unverified query syntax
entirely.

Paginated (Qodo, PR #63 review, "History stops after 1,000") — a single
capped request silently missed correspondence beyond the first page for any
mailbox larger than that. `_fetch_messages` now loops, advancing `start` by
however many messages the previous page actually returned, stopping once
the response's own documented `total` field (`MessagesSummary.total`,
"Total number of messages in mailbox") is reached, or a page comes back
empty (the fallback if `total` is missing/malformed) — never on "fewer than
requested," since the vendored spec never documents a maximum `limit`
Mailpit is guaranteed to honor, and assuming one would be exactly the kind
of unverified behavior this module avoids elsewhere. `_MAX_MESSAGES_FETCHED`
is a hard safety cap independent of `total`, so a pathological or hostile
`total` value can't turn this into an unbounded fetch loop.

Matches on `From` only, not `To`/`Cc`/`Bcc`/`ReplyTo` — this tool answers
"has this address/domain sent us mail before," the signal a suspicious
message's own claimed sender is checked against, not "have we ever emailed
them" (a different, unrelated question this tool doesn't try to answer). A
message has exactly one `From`, so this reads as one sender-domain per
message, never an ambiguous multi-sender case.

Dates come from Mailpit's own `Created` field (its real received time,
RFC3339Nano) — never from the fictional narrative dates hand-written into
`range/fixtures/*.json`'s `Received` header text, which Mailpit doesn't
parse or trust either. Compared as parsed, timezone-aware instants, not raw
strings (Qodo, PR #63 review, "Timestamp bounds sort incorrectly") — Go's
RFC3339Nano format trims trailing zeros from the fractional-seconds
component, so two valid timestamps within the same second can have
different string lengths (`.1Z` vs `.12Z`), and lexical comparison gets
that pair backwards (confirmed: `"...0.12Z" < "...0.1Z"` as plain strings,
even though .12s is chronologically later than .1s). The *emitted*
`first_seen`/`last_seen` values are still the original upstream strings,
never reformatted — only the comparison itself is timezone-aware.

No `truststore` injection here (unlike domain_intel.py/url_reputation.py):
Mailpit is a local, plain-HTTP-only service (`range/docker-compose.yml`
publishes `8025` with no TLS) — the local-TLS-inspection SSL issue those
modules work around doesn't apply to a plaintext local connection.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import requests

DEFAULT_MAILPIT_URL = "http://localhost:8025"
MAILPIT_TIMEOUT_SECONDS = 10

# Per-request page size, not a hard ceiling - _fetch_messages loops across
# as many pages as the mailbox actually has (Qodo, PR #63, "History stops
# after 1,000"). _MAX_MESSAGES_FETCHED is the real ceiling: independent of
# any single page's size, it bounds the total across every page combined,
# so a pathological or hostile `total` value can't turn this into an
# unbounded fetch loop against a demo-scale Range mailbox.
_MESSAGES_PAGE_SIZE = 500
_MAX_MESSAGES_FETCHED = 20000

MAX_RESPONSE_BYTES = 2000
_MAX_FIELD_CHARS = 200
_TRIMMABLE_STRING_FIELDS = ("first_seen", "last_seen", "address", "domain")


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
    """Returns every message in the mailbox (Qodo, PR #63, "History stops
    after 1,000" — this now paginates rather than reading a single capped
    page), or None on any failure — network error, non-200, invalid JSON,
    or a response that doesn't match the documented `MessagesSummary`
    shape on *any* page. A failure partway through returns None for the
    whole fetch rather than the partial result collected so far: a
    truncated-but-silent answer would be exactly the wrong kind of
    correctness bug this fix exists to close, so a mid-fetch failure
    degrades the same way a first-page failure always has. None is the
    caller's signal to degrade, never a raise: Mailpit being unreachable
    is exactly the kind of upstream failure every other `imports-mcp` tool
    already degrades through instead of crashing the mission's evidence
    gathering.
    """
    all_messages: list[dict[str, Any]] = []
    start = 0

    while True:
        try:
            resp = requests.get(
                f"{_mailpit_url()}/api/v1/messages",
                params={"start": start, "limit": _MESSAGES_PAGE_SIZE},
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

        page = data.get("messages")
        if not isinstance(page, list):
            return None

        if not page:
            break

        all_messages.extend(page)

        total = data.get("total")
        if isinstance(total, int) and len(all_messages) >= total:
            break
        if len(all_messages) >= _MAX_MESSAGES_FETCHED:
            break
        start += len(page)

    return all_messages


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


def _parse_created(value: str) -> datetime | None:
    """Parses Mailpit's RFC3339Nano `Created` timestamp into a
    timezone-aware, chronologically-comparable instant (Qodo, PR #63,
    "Timestamp bounds sort incorrectly" — plain string comparison is
    unsafe here; see the module docstring for the exact counter-example).
    Returns None for anything unparseable *or* without a timezone offset —
    a naive datetime can't be safely compared against an aware one, and
    Mailpit's real `Created` field is always timezone-aware, so a value
    without one is already malformed. The caller skips it, same as any
    other malformed field — it just never becomes a `first_seen`/
    `last_seen` candidate, the message can still count toward
    `prior_contact_count` regardless."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _shrink_string(value: str) -> str:
    """Strictly shrinks toward "" so a caller looping "shrink until it
    fits" always terminates - the exact non-termination class of bug Qodo
    caught in url_reputation's original cap (PR #19)."""
    if len(value) <= _MAX_FIELD_CHARS:
        return ""
    return value[:-_MAX_FIELD_CHARS]


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """Cap the serialized response at ~max_bytes (Rule 2880706), with an
    explicit `truncated` indicator, verified after every single trimming
    step rather than assumed (Qodo, PR #63, "`_cap_response` can exceed
    2KB" — the previous version only ever trimmed `address`/`domain`,
    leaving `first_seen`/`last_seen`/`domains_used` untouched even though
    all three ultimately come from Mailpit's own `Created`/`From` fields,
    which this module already treats as untrusted everywhere else). Two
    tiers, matching the same list-then-scalar shape every other tool in
    this package already uses: `domains_used` is trimmed as a list first
    (entries dropped from the end, tracked in `omitted`); then every
    remaining variable-length string field — `first_seen`, `last_seen`,
    `address`, `domain` — is shrunk toward `""` in turn. `prior_contact_count`
    is never touched — a caller branches on it directly, and it's a small
    int regardless of how large a real history grows. Once every list
    entry and every string field bottoms out, the remaining payload (fixed
    field names, an int, a bool, and a small `omitted` dict) is
    unconditionally small, so this is guaranteed to terminate at or under
    budget, not just attempt to."""
    capped = dict(result)
    capped["truncated"] = False
    if len(json.dumps(capped, ensure_ascii=False).encode("utf-8")) <= max_bytes:
        return capped

    omitted: dict[str, Any] = {}
    capped["truncated"] = True
    capped["omitted"] = omitted

    def fits() -> bool:
        return len(json.dumps(capped, ensure_ascii=False).encode("utf-8")) <= max_bytes

    domains_used = list(capped.get("domains_used") or [])
    capped["domains_used"] = domains_used
    while domains_used and not fits():
        domains_used.pop()
        omitted["domains_used"] = omitted.get("domains_used", 0) + 1
    if fits():
        return capped

    for field in _TRIMMABLE_STRING_FIELDS:
        value = capped.get(field)
        while isinstance(value, str) and value and not fits():
            value = _shrink_string(value)
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
    created_candidates: list[tuple[datetime, str]] = []

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
            parsed = _parse_created(created)
            if parsed is not None:
                created_candidates.append((parsed, created))

    result = {
        "address": address,
        "domain": domain,
        "prior_contact_count": matched_count,
        "first_seen": min(created_candidates, key=lambda c: c[0])[1] if created_candidates else None,
        "last_seen": max(created_candidates, key=lambda c: c[0])[1] if created_candidates else None,
        "domains_used": sorted(matched_domains),
    }
    return _cap_response(result)
