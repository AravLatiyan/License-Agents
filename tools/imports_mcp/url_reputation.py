"""url_reputation — URLhaus exact-URL lookup (T-021).

URLhaus is malware-focused, not phishing-focused (CLAUDE.md trap #8):
"not listed" is weak evidence only, never a verdict on its own — this
module says so in the note field rather than trusting the caller to know
that. Every endpoint requires the Auth-Key header now, including reads,
confirmed live in T-003.

Also injects truststore at import time — same local TLS-inspection SSL
issue documented in domain_intel.py / PLAN.md §6-§7. Every networked tool
in this package needs this line.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
import truststore
from dotenv import load_dotenv

truststore.inject_into_ssl()
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

URLHAUS_TIMEOUT_SECONDS = 10
URLHAUS_URL_ENDPOINT = "https://urlhaus-api.abuse.ch/v1/url/"

NOT_LISTED_NOTE = "not listed in URLhaus — weak signal only, not a clean bill of health"

# Rule 2880706: MCP tool responses must stay under ~2KB and signal truncation.
# `tags` (URLhaus-supplied) is trimmed first, then `note`/`url` (which can
# embed an exception message or an attacker-influenced URL) are truncated as
# strings, until the serialized response fits.
MAX_RESPONSE_BYTES = 2000


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


# Every upstream-supplied scalar string, not just note/url - threat,
# url_status, and date_added are just as unbounded/attacker-influenced as
# note and url are (URLhaus returns them verbatim from whatever submitted
# the URL). Rule 2880706 covers the whole serialized response, not a
# hand-picked subset of its fields.
_TRIMMABLE_STRING_FIELDS = ("note", "url", "threat", "url_status", "date_added")


def _shrink_string(value: str) -> str:
    """Cuts one chunk off the end, strictly shrinking toward "" so a caller
    looping "shrink until it fits" always terminates - unlike slicing to a
    fixed length floor, this never plateaus at a single leftover character
    while the response is still over budget from some other field."""
    if len(value) <= 200:
        return ""
    return value[:-200]


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """Cap the serialized response at ~max_bytes, with an explicit indicator.

    Adds `truncated` (bool) and, only when something was cut, `omitted`
    (which fields were trimmed) — a caller can tell evidence was dropped
    rather than silently get a partial result. `tags` is emptied first,
    then every scalar string field is shrunk toward "" in turn; the final
    serialized size is verified after every step, never assumed to fit.
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

    tags = list(capped.get("tags") or [])
    capped["tags"] = tags
    while tags and not fits():
        tags.pop()
        omitted["tags"] = omitted.get("tags", 0) + 1
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


def _unavailable(url: str, note: str) -> dict[str, Any]:
    return {
        "url": url,
        "available": False,
        "listed": False,
        "threat": None,
        "tags": [],
        "url_status": None,
        "date_added": None,
        "note": note,
    }


def url_reputation(url: str) -> dict[str, Any]:
    """URLhaus verdict for one exact URL, never raises on the source being unreachable.

    Response is capped at ~2KB serialized (Rule 2880706); see `_cap_response`.
    """
    return _cap_response(_url_reputation_uncapped(url))


def _url_reputation_uncapped(url: str) -> dict[str, Any]:
    auth_key = os.environ.get("URLHAUS_AUTH_KEY")
    if not auth_key:
        return _unavailable(url, "URLHAUS_AUTH_KEY not configured")

    try:
        resp = requests.post(
            URLHAUS_URL_ENDPOINT,
            headers={"Auth-Key": auth_key},
            data={"url": url},
            timeout=URLHAUS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return _unavailable(url, f"URLhaus lookup failed: {exc}")

    if resp.status_code == 401:
        return _unavailable(url, "URLhaus rejected the Auth-Key (401)")
    if resp.status_code != 200:
        return _unavailable(url, f"URLhaus returned HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError:
        return _unavailable(url, "URLhaus response was not valid JSON")

    # A 200 with valid JSON doesn't guarantee a JSON *object* — URLhaus (or a
    # proxy/misconfiguration in front of it) could return null, an array, or
    # a bare string, and .get() below would raise on any of those.
    if not isinstance(data, dict):
        return _unavailable(url, f"URLhaus response was not a JSON object (got {type(data).__name__})")

    status = data.get("query_status")

    if status == "no_results":
        return {
            "url": url,
            "available": True,
            "listed": False,
            "threat": None,
            "tags": [],
            "url_status": None,
            "date_added": None,
            "note": NOT_LISTED_NOTE,
        }

    if status != "ok":
        return _unavailable(url, f"URLhaus query_status was {status!r}")

    tags = data.get("tags")
    if tags is None:
        tags = []
    elif not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        # A malformed-but-valid-JSON tags field (e.g. an int, a string, a
        # list of non-strings) would otherwise reach the caller as a
        # contract-invalid shape, and crash _cap_response's list(tags) call
        # outright for a non-iterable scalar - same class of "valid JSON,
        # wrong shape" guard domain_intel already applies to RDAP's events.
        return _unavailable(url, "URLhaus response had an unexpected shape: 'tags' was not a list of strings")

    return {
        "url": url,
        "available": True,
        "listed": True,
        "threat": data.get("threat"),
        "tags": tags,
        "url_status": data.get("url_status"),
        "date_added": data.get("date_added"),
        "note": None,
    }
