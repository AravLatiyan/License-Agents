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
    """URLhaus verdict for one exact URL, never raises on the source being unreachable."""
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

    return {
        "url": url,
        "available": True,
        "listed": True,
        "threat": data.get("threat"),
        "tags": data.get("tags") or [],
        "url_status": data.get("url_status"),
        "date_added": data.get("date_added"),
        "note": None,
    }
