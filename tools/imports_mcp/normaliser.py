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
_TRAILING_SENTENCE_PUNCT = ".,;:!?'\""


def _strip_trailing_punctuation(url: str) -> str:
    """Drop sentence punctuation a bare-URL regex match picks up, without
    mangling a URL that legitimately ends in a closing paren (e.g. a
    Wikipedia article path). A trailing ")" is ambiguous - it either closes
    a paren that's part of the URL or one from the surrounding sentence
    ("(see http://example.com)") - so only the excess (unmatched) closing
    parens get stripped; a balanced trailing ")" is left alone.
    """
    excess_close_parens = url.count(")") - url.count("(")
    while url:
        if url[-1] in _TRAILING_SENTENCE_PUNCT:
            url = url[:-1]
        elif url[-1] == ")" and excess_close_parens > 0:
            url = url[:-1]
            excess_close_parens -= 1
        else:
            break
    return url


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
        # Only absolute http(s) links are useful to url_reputation - mailto:,
        # javascript:, bare fragments, and relative paths (we have no base
        # URL to resolve them against) all get dropped here, not downstream.
        if not href or not href.lower().startswith(("http://", "https://")):
            continue
        anchor_text = (anchor.text_content() or "").strip()
        urls.append({"href": href, "anchor_text": anchor_text})
    return urls


def _urls_from_plain_text(text: str) -> list[dict[str, str]]:
    return [
        {"href": _strip_trailing_punctuation(m.group(0)), "anchor_text": ""}
        for m in _BARE_URL_RE.finditer(text)
    ]


def _dedupe_urls(urls: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep first occurrence per href. HTML is extracted before plain text,
    so when the same link appears in both multipart alternatives, the
    HTML version (with real anchor text) wins over the bare-URL match."""
    seen: set[str] = set()
    deduped = []
    for url in urls:
        if url["href"] in seen:
            continue
        seen.add(url["href"])
        deduped.append(url)
    return deduped


def _extract_urls(msg: EmailMessage) -> list[dict[str, str]]:
    """Every URL from every body alternative, not just the first one found.

    multipart/alternative parts aren't guaranteed to carry the same links -
    a phishing message can put one URL in the HTML version a client renders
    and a different one in the plain-text fallback. Extracting from HTML
    alone (or stopping if HTML parsing fails) would silently miss those.
    """
    html_part = msg.get_body(preferencelist=("html",))
    plain_part = msg.get_body(preferencelist=("plain",))

    urls: list[dict[str, str]] = []
    if html_part is not None:
        urls.extend(_urls_from_html(_decode_text(html_part)))
    if plain_part is not None:
        urls.extend(_urls_from_plain_text(_decode_text(plain_part)))
    return _dedupe_urls(urls)


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
