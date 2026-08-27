"""domain_intel — RDAP registration/abuse data + crt.sh cert age (T-020).

Both sources are read-only and unauthenticated (confirmed live in T-003).
Each is wrapped so a failure on one never blocks the other or crashes the
tool call — CLAUDE.md's traps say many ccTLDs have partial/no RDAP and GDPR
redacts abuse contacts ("not published" is a valid finding, not a crash),
and crt.sh is slow and 502s (5s timeout, cache hard, never block a
mission). crt.sh was in fact down (502) for the entire time this file was
written and tested — the fallback path below is exercised for real, not
hypothetically.

Also injects truststore at import time: on a machine where antivirus does
local TLS inspection (confirmed here — Norton generates its own root CA,
which Windows trusts but certifi's bundled CA list doesn't), requests
fails SSL verification even though curl and browsers work fine, because
certifi ships a fixed CA list instead of reading the OS trust store.
truststore makes the stdlib ssl module (and therefore requests) use the
OS store instead, which is the real fix — not disabling verification.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import requests
import truststore

truststore.inject_into_ssl()

RDAP_TIMEOUT_SECONDS = 10
CRTSH_TIMEOUT_SECONDS = 5
CRTSH_CACHE_TTL_SECONDS = 3600
MAX_RESPONSE_BYTES = 2048
_MAX_FIELD_CHARS = 200

# In-memory only — good enough for one Slice-2 mission run. T-045 upgrades
# this to SQLite so it survives a restart; don't duplicate that here.
# Value is (cached_at_epoch_seconds, result) so CRTSH_CACHE_TTL_SECONDS is
# actually enforced instead of caching forever.
_crtsh_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _vcard_field(entity: dict[str, Any], field: str) -> str | None:
    vcard = entity.get("vcardArray")
    if not isinstance(vcard, list) or len(vcard) < 2 or not isinstance(vcard[1], list):
        return None
    for item in vcard[1]:
        if isinstance(item, (list, tuple)) and len(item) > 3 and item[0] == field and item[3]:
            return item[3]
    return None


def _rdap_lookup(domain: str) -> dict[str, Any]:
    empty = {"available": False, "registrar": None, "registration_date": None, "abuse_contact": None}

    try:
        resp = requests.get(f"https://rdap.org/domain/{domain}", timeout=RDAP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return {**empty, "note": f"RDAP lookup failed: {exc}"}

    if resp.status_code == 404:
        return {**empty, "note": "domain not found in RDAP"}
    if resp.status_code != 200:
        return {**empty, "note": f"RDAP returned HTTP {resp.status_code}"}

    try:
        data = resp.json()
    except ValueError:
        return {**empty, "note": "RDAP response was not valid JSON"}

    if not isinstance(data, dict):
        return {**empty, "note": "RDAP response was not a JSON object"}

    # RDAP is a public registry format we don't control the shape of end to
    # end - a technically-valid-JSON response with an unexpected structure
    # (wrong types, missing nesting) must degrade the same as a network
    # failure, not raise and take crt.sh down with it.
    events = data.get("events", [])
    if not isinstance(events, list):
        # A string would silently iterate to individual characters here
        # (all filtered out by the isinstance(e, dict) check below) and come
        # back as available=True with "not published" - technically-valid
        # JSON with a malformed "events" field should itself count as a
        # malformed RDAP response, not a domain with no registration event.
        return {**empty, "note": "RDAP response had an unexpected shape: 'events' was not a list"}

    try:
        registration_date = next(
            (
                e.get("eventDate")
                for e in events
                if isinstance(e, dict) and e.get("eventAction") == "registration"
            ),
            None,
        )

        registrar = None
        abuse_contact = None
        for entity in data.get("entities", []) or []:
            if not isinstance(entity, dict):
                continue
            roles = entity.get("roles") or []
            if "registrar" in roles:
                registrar = _vcard_field(entity, "fn")
                for sub in entity.get("entities", []) or []:
                    if isinstance(sub, dict) and "abuse" in (sub.get("roles") or []):
                        abuse_contact = _vcard_field(sub, "email")
            elif "abuse" in roles and abuse_contact is None:
                abuse_contact = _vcard_field(entity, "email")
    except (AttributeError, TypeError) as exc:
        return {**empty, "note": f"RDAP response had an unexpected shape: {exc}"}

    return {
        "available": True,
        "registrar": registrar,
        "registration_date": registration_date,
        "abuse_contact": abuse_contact,
        "note": None if registration_date else "registration date not published",
    }


def _parse_crtsh_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.split(".")[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _crtsh_cache_get(domain: str) -> dict[str, Any] | None:
    cached = _crtsh_cache.get(domain)
    if cached is None:
        return None
    cached_at, result = cached
    if time.time() - cached_at >= CRTSH_CACHE_TTL_SECONDS:
        del _crtsh_cache[domain]
        return None
    return result


def _crtsh_lookup(domain: str) -> dict[str, Any]:
    cached = _crtsh_cache_get(domain)
    if cached is not None:
        return cached

    empty = {"available": False, "earliest_seen": None, "age_days": None}

    try:
        resp = requests.get(
            "https://crt.sh/", params={"q": domain, "output": "json"}, timeout=CRTSH_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        # Transient - don't cache, so a retry a minute from now can succeed.
        return {**empty, "note": f"crt.sh lookup failed: {exc}"}

    if resp.status_code != 200:
        return {**empty, "note": f"crt.sh returned HTTP {resp.status_code}"}

    try:
        entries = resp.json()
    except ValueError:
        return {**empty, "note": "crt.sh response was not valid JSON"}

    if not isinstance(entries, list):
        return {**empty, "note": "crt.sh response was not a JSON array"}

    if not entries:
        result = {**empty, "available": True, "note": "no certificates logged for this domain"}
        _crtsh_cache[domain] = (time.time(), result)
        return result

    dates = [
        d
        for d in (_parse_crtsh_date(e.get("not_before")) for e in entries if isinstance(e, dict))
        if d is not None
    ]
    if not dates:
        result = {**empty, "available": True, "note": "certificates logged but none had a parseable issue date"}
    else:
        earliest = min(dates)
        age_days = (datetime.now(timezone.utc) - earliest).days
        result = {
            "available": True,
            "earliest_seen": earliest.isoformat(),
            "age_days": age_days,
            "note": None,
        }

    _crtsh_cache[domain] = (time.time(), result)
    return result


def _truncate_str(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str) or len(value) <= max_chars:
        return value
    return value[:max_chars] + "…"


def _cap_response_size(result: dict[str, Any]) -> dict[str, Any]:
    """Enforce the ~2KB MCP response budget (CLAUDE.md: every tool response
    under ~2KB). Only free-text fields get shortened - structured fields
    (available/age_days/dates) are never dropped, since those are what a
    caller actually branches on. A caller-controlled domain or a malformed
    upstream field are the only realistic ways this budget gets threatened.

    `truncated` itself is part of the serialized response, so it has to be
    included *before* the very first size check - checking `result` alone
    and adding the key afterward can return a payload a few bytes over the
    declared limit while claiming truncated=False. The truncation branch
    then re-verifies the final size rather than assuming one round of
    field-truncation was always enough.
    """
    with_flag = {**result, "truncated": False}
    if len(json.dumps(with_flag).encode("utf-8")) <= MAX_RESPONSE_BYTES:
        return with_flag

    capped = dict(result)
    capped["domain"] = _truncate_str(result["domain"], _MAX_FIELD_CHARS)
    for section in ("rdap", "cert"):
        section_data = dict(result.get(section) or {})
        for field in ("registrar", "abuse_contact", "note", "earliest_seen", "registration_date"):
            if field in section_data:
                section_data[field] = _truncate_str(section_data[field], _MAX_FIELD_CHARS)
        capped[section] = section_data
    _resync_flat_mirrors(capped)
    capped["truncated"] = True

    if len(json.dumps(capped).encode("utf-8")) > MAX_RESPONSE_BYTES:
        # One round of truncation to _MAX_FIELD_CHARS wasn't enough - shrink
        # every free-text field further rather than return an over-budget
        # payload while still claiming truncated=True fixed it.
        capped["domain"] = _truncate_str(capped["domain"], 40)
        for section in ("rdap", "cert"):
            section_data = dict(capped.get(section) or {})
            for field in ("registrar", "abuse_contact", "note", "earliest_seen", "registration_date"):
                if field in section_data:
                    section_data[field] = _truncate_str(section_data[field], 40)
            capped[section] = section_data
        _resync_flat_mirrors(capped)

    return capped


def _resync_flat_mirrors(capped: dict[str, Any]) -> None:
    """Keep the top-level registration_date/registrar/abuse_contact/
    cert_issued_at mirrors (see domain_intel()) equal to whatever the
    rdap/cert sections hold *after* truncation - otherwise a truncated
    nested value and an untruncated flat mirror of the same field could
    disagree, and the flat mirror could itself carry the oversized string
    that made truncation necessary in the first place.
    """
    rdap_section = capped.get("rdap") or {}
    cert_section = capped.get("cert") or {}
    capped["registration_date"] = rdap_section.get("registration_date")
    capped["registrar"] = rdap_section.get("registrar")
    capped["abuse_contact"] = rdap_section.get("abuse_contact")
    capped["cert_issued_at"] = cert_section.get("earliest_seen")


def domain_intel(domain: str) -> dict[str, Any]:
    """RDAP registration/abuse data + crt.sh cert age for a domain.

    Never raises because one source is down - each half degrades to
    available=False with a note instead.

    Also mirrors registration_date/registrar/abuse_contact/cert_issued_at at
    the top level, alongside the nested rdap/cert sections (kept as-is - this
    module's own tests and harness/agent.json's T-023/T-024 instructions
    already depend on that nested shape by name). The flat mirrors exist so
    this satisfies contracts/events.ts's existing DomainIntel shape (Qodo PR
    #19 finding: without them, every top-level field Cockpit's isDomainIntel
    checks for is missing, so a live mission.evidence event carrying this
    tool's real output throws in assertMissionEvent). Not a new schema -
    the four field names and their source values both come straight from
    the already-existing contract and the already-existing rdap/cert
    lookups; cert_issued_at maps to cert.earliest_seen, the earliest
    certificate-transparency issuance date this module already computes.
    """
    rdap = _rdap_lookup(domain)
    cert = _crtsh_lookup(domain)
    result = {
        "domain": domain,
        "rdap": rdap,
        "cert": cert,
        "registration_date": rdap.get("registration_date"),
        "registrar": rdap.get("registrar"),
        "abuse_contact": rdap.get("abuse_contact"),
        "cert_issued_at": cert.get("earliest_seen"),
    }
    return _cap_response_size(result)
