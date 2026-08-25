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

import time
from datetime import datetime, timezone
from typing import Any

import requests
import truststore

truststore.inject_into_ssl()

RDAP_TIMEOUT_SECONDS = 10
CRTSH_TIMEOUT_SECONDS = 5
CRTSH_CACHE_TTL_SECONDS = 3600

# In-memory only — good enough for one Slice-2 mission run. T-045 upgrades
# this to SQLite so it survives a restart; don't duplicate that here.
_crtsh_cache: dict[str, dict[str, Any]] = {}


def _vcard_field(entity: dict[str, Any], field: str) -> str | None:
    vcard = entity.get("vcardArray")
    if not vcard or len(vcard) < 2:
        return None
    for item in vcard[1]:
        if item and item[0] == field and len(item) > 3 and item[3]:
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

    registration_date = next(
        (e.get("eventDate") for e in data.get("events", []) if e.get("eventAction") == "registration"),
        None,
    )

    registrar = None
    abuse_contact = None
    for entity in data.get("entities", []):
        roles = entity.get("roles", [])
        if "registrar" in roles:
            registrar = _vcard_field(entity, "fn")
            for sub in entity.get("entities", []):
                if "abuse" in sub.get("roles", []):
                    abuse_contact = _vcard_field(sub, "email")
        elif "abuse" in roles and abuse_contact is None:
            abuse_contact = _vcard_field(entity, "email")

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


def _crtsh_lookup(domain: str) -> dict[str, Any]:
    cached = _crtsh_cache.get(domain)
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

    if not entries:
        result = {**empty, "available": True, "note": "no certificates logged for this domain"}
        _crtsh_cache[domain] = result
        return result

    dates = [d for d in (_parse_crtsh_date(e.get("not_before")) for e in entries) if d is not None]
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

    _crtsh_cache[domain] = result
    return result


def domain_intel(domain: str) -> dict[str, Any]:
    """RDAP registration/abuse data + crt.sh cert age for a domain.

    Never raises because one source is down - each half degrades to
    available=False with a note instead.
    """
    return {
        "domain": domain,
        "rdap": _rdap_lookup(domain),
        "cert": _crtsh_lookup(domain),
    }
