"""RFC822 message normaliser — T-010.

Turns a raw .eml into a small structured dict: envelope identity, the raw
Authentication-Results / Received headers (never re-verified, just read —
see CLAUDE.md trap #2), every URL with its anchor text, and attachment
hashes. No network calls here; that's domain_intel/url_reputation's job.
"""

from __future__ import annotations

import hashlib
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from typing import Any

from lxml import html as lxml_html

_BARE_URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _decode_text(part: EmailMessage) -> str:
    try:
        return part.get_content()
    except (UnicodeDecodeError, LookupError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("latin-1", errors="replace")


def _parse_address(header_value: str | None) -> dict[str, str] | None:
    if not header_value:
        return None
    display_name, address = parseaddr(header_value)
    return {"display_name": display_name, "address": address}


def _urls_from_html(text: str) -> list[dict[str, str]]:
    urls: list[dict[str, str]] = []
    try:
        tree = lxml_html.fromstring(text)
    except Exception:
        return urls
    for anchor in tree.iter("a"):
        href = anchor.get("href")
        if not href:
            continue
        anchor_text = (anchor.text_content() or "").strip()
        urls.append({"href": href, "anchor_text": anchor_text})
    return urls


def _urls_from_plain_text(text: str) -> list[dict[str, str]]:
    return [{"href": m.group(0), "anchor_text": ""} for m in _BARE_URL_RE.finditer(text)]


def _extract_urls(msg: EmailMessage) -> list[dict[str, str]]:
    html_part = msg.get_body(preferencelist=("html",))
    plain_part = msg.get_body(preferencelist=("plain",))

    if html_part is not None:
        return _urls_from_html(_decode_text(html_part))
    if plain_part is not None:
        return _urls_from_plain_text(_decode_text(plain_part))
    return []


def _extract_attachments(msg: EmailMessage) -> list[dict[str, Any]]:
    attachments = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        attachments.append(
            {
                "filename": part.get_filename() or "(unnamed)",
                "content_type": part.get_content_type(),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        )
    return attachments


def parse_message(raw: bytes) -> dict[str, Any]:
    """Parse a raw RFC822 message into a small structured dict."""
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)

    return {
        "from": _parse_address(msg.get("From")),
        "reply_to": _parse_address(msg.get("Reply-To")),
        "return_path": _parse_address(msg.get("Return-Path")),
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "authentication_results": msg.get_all("Authentication-Results", []),
        "received_chain": msg.get_all("Received", []),
        "urls": _extract_urls(msg),
        "attachments": _extract_attachments(msg),
    }


def parse_message_from_path(path: str) -> dict[str, Any]:
    with open(path, "rb") as f:
        return parse_message(f.read())


if __name__ == "__main__":
    import json
    import sys

    for eml_path in sys.argv[1:]:
        print(f"--- {eml_path} ---")
        print(json.dumps(parse_message_from_path(eml_path), indent=2))
