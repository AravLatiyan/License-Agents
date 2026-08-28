"""detonate — text-mode detonation (T-026).

Python port of `harness/detonate.js` (T-014)'s logic, not a new design:
follow redirects manually, parse the final HTML with a real parser (never
regex, CLAUDE.md trap #5), and flag forms that ask for a password and post
to a different origin than the page they're on. No screenshot — that's the
chromium-in-Daytona path, which T-035 found genuinely blocked (no Daytona
key, no snapshot/warm-pool mechanism, "the sandbox job" undefined) — this
tool's own scope was never that path (§10's tool table already places
`detonate(url)` in this Python MCP surface, same as every other tool here).

Every failure mode (bad URL, DNS/connection failure, timeout, malformed
redirect location, oversized body) returns the same {url, redirect_chain,
error} shape instead of raising — the target is untrusted and frequently
unreachable, and a dead phishing URL is a routine result, not a tool
failure, matching every other tool in this package's degrade-not-raise
convention.

Also injects truststore at import time — same local TLS-inspection SSL
issue documented in domain_intel.py / PLAN.md §6-§7. Every networked tool
in this package needs this line.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import truststore
from lxml import html as lxml_html

truststore.inject_into_ssl()

MAX_REDIRECT_HOPS = 10
REQUEST_TIMEOUT_SECONDS = 5
MAX_BODY_BYTES = 2 * 1024 * 1024  # bound attacker-controlled response size before buffering/parsing
MAX_RESPONSE_BYTES = 2000

_TRIMMABLE_STRING_FIELDS = ("summary", "final_url", "url", "error")


def _shrink_string(value: str) -> str:
    """Strictly shrinks toward "" so a caller looping "shrink until it
    fits" always terminates - the exact non-termination class of bug Qodo
    caught in url_reputation's original cap (PR #19)."""
    if len(value) <= 200:
        return ""
    return value[:-200]


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """Cap the serialized response at ~max_bytes (Rule 2880706), with an
    explicit `truncated` indicator and, once true, `omitted` (which fields
    were trimmed). `forms` and `redirect_chain` are emptied first (a page
    can carry many of either); if that alone isn't enough, the scalar
    string fields are shrunk toward "" next. Final size is verified after
    every step, mirroring server.py's own `_cap_response`.
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

    for field in ("forms", "redirect_chain"):
        items = list(capped.get(field) or [])
        capped[field] = items
        while items and not fits():
            items.pop()
            omitted[field] = omitted.get(field, 0) + 1
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


def _is_private_target(hostname: str) -> str | None:
    """Resolves the *address*, not just the hostname string, so a domain
    that resolves to an internal IP (DNS rebinding) is caught too, not
    only literal http://127.0.0.1-style URLs. Returns the offending
    address, or None if every resolved address is public.

    Rule 2880752 (SSRF guard): stdlib `ipaddress.is_private` covers
    loopback/RFC1918/link-local/reserved space for both IPv4 and IPv6 in
    one check, rather than hand-rolling the range list detonate.js does -
    same guarantee, less code to keep in sync.
    """
    try:
        ipaddress.ip_address(hostname)
        candidates = [hostname]
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return None  # DNS failure surfaces later as a real fetch error, not here
        candidates = [info[4][0] for info in infos]

    for address in candidates:
        if ipaddress.ip_address(address).is_private:
            return address
    return None


def _describe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _read_body_with_limit(response: requests.Response, max_bytes: int) -> tuple[str, bool]:
    """Streams the body with a hard byte cap instead of `.text`, which
    buffers unbounded - an attacker-controlled server can otherwise
    exhaust memory with a fast, oversized response regardless of the
    request timeout."""
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > max_bytes:
            response.close()
            return "", True
        chunks.append(chunk)
    body = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace"), False
    except LookupError:
        return body.decode("utf-8", errors="replace"), False


def _extract_forms(html_text: str, page_url: str) -> list[dict[str, Any]]:
    """Untrusted HTML: one malformed form action must not prevent every
    other form on the page from being reported."""
    try:
        root = lxml_html.fromstring(html_text)
    except Exception:
        return []

    page_origin = _origin(page_url)
    forms: list[dict[str, Any]] = []

    for form in root.findall(".//form"):
        raw_action = form.get("action") or ""
        method = (form.get("method") or "GET").upper()
        # HTML's `type` attribute is an enumerated attribute, matched
        # case-insensitively per spec - type="PASSWORD" is a real password
        # field in every browser. An XPath string-equality check on the raw
        # attribute value would miss it (Qodo finding #2, PR #37 review).
        asks_password = any(
            (inp.get("type") or "").lower() == "password" for inp in form.findall(".//input")
        )

        try:
            action_url = urljoin(page_url, raw_action or page_url)
            parsed = urlparse(action_url)
        except ValueError:
            # urljoin/urlparse raise ValueError for some malformed inputs
            # (e.g. an unbalanced "[" in a bracketed-IPv6-style authority)
            # rather than returning a garbage-but-inert result the way they
            # usually do - one bad form's action must not abort every other
            # form on the page, so this is exactly the action_invalid path.
            parsed = None
        if parsed is not None and parsed.scheme and parsed.netloc:
            action_origin = _normalize_origin(parsed)
            forms.append(
                {
                    "action": action_url,
                    "action_origin": action_origin,
                    "method": method,
                    "cross_domain": action_origin != page_origin,
                    "asks_password": asks_password,
                }
            )
        else:
            forms.append(
                {
                    "action": raw_action,
                    "action_origin": None,
                    "method": method,
                    "cross_domain": None,
                    "asks_password": asks_password,
                    "action_invalid": True,
                }
            )

    return forms


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _normalize_origin(parsed) -> str:
    """Browser-normalized origin: lowercased scheme/host (urlparse already
    lowercases `.hostname`), default port stripped, credentials excluded.
    Comparing raw `scheme://netloc` treats https://example.com and
    https://example.com:443 as different origins even though they're the
    same one - a real false-positive risk for the cross-domain check this
    feeds (Qodo finding #4, PR #37 review)."""
    port = parsed.port
    if port is not None and port == _DEFAULT_PORTS.get(parsed.scheme):
        port = None
    netloc = parsed.hostname or ""
    if port is not None:
        netloc = f"{netloc}:{port}"
    return f"{parsed.scheme}://{netloc}"


def _origin(url: str) -> str:
    return _normalize_origin(urlparse(url))


def detonate(
    start_url: str,
    allow_private_network_targets: bool = False,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    max_body_bytes: int = MAX_BODY_BYTES,
) -> dict[str, Any]:
    """Text-mode detonation of one URL. Never raises - every failure mode
    (bad URL, DNS/connection failure, timeout, malformed redirect, oversized
    body) returns {url, redirect_chain, error} instead.

    `allow_private_network_targets` exists only for this module's own test
    fixtures to opt back into a local target explicitly - never set it for
    a real detonation. `timeout_seconds`/`max_body_bytes` default to the
    module constants and only exist as parameters so tests can exercise the
    timeout/oversized-body paths without a 5-second wait or a 2MB fixture.
    """
    redirect_chain: list[dict[str, Any]] = []
    current_url = start_url

    for hop in range(MAX_REDIRECT_HOPS + 1):
        if hop == MAX_REDIRECT_HOPS:
            return _cap_response(
                {
                    "url": start_url,
                    "redirect_chain": redirect_chain,
                    "error": f"redirect chain exceeded {MAX_REDIRECT_HOPS} hops",
                }
            )

        try:
            parsed = urlparse(current_url)
            hostname = parsed.hostname
        except ValueError as exc:
            # urlparse/`.hostname` raise for some malformed inputs (e.g. an
            # unbalanced "[" in a bracketed-IPv6-style authority) instead of
            # returning an inert result - this is the very first parse of
            # start_url itself, so an unguarded call here was the one path
            # that could still escape the documented never-raise contract
            # (Qodo finding #1, PR #37 review).
            return _cap_response(
                {"url": start_url, "redirect_chain": redirect_chain, "error": f"malformed URL: {exc}"}
            )

        if parsed.scheme not in ("http", "https"):
            return _cap_response(
                {
                    "url": start_url,
                    "redirect_chain": redirect_chain,
                    "error": f"refused non-http(s) scheme: {parsed.scheme}",
                }
            )

        if not allow_private_network_targets:
            private_target = _is_private_target(hostname or "")
            if private_target:
                return _cap_response(
                    {
                        "url": start_url,
                        "redirect_chain": redirect_chain,
                        "error": (
                            f"refused private/internal network target: "
                            f"{hostname} resolves to {private_target}"
                        ),
                    }
                )

        try:
            response = requests.get(
                current_url,
                allow_redirects=False,
                timeout=timeout_seconds,
                stream=True,
            )
        except (requests.RequestException, ValueError) as exc:
            # requests builds Response.next internally even with
            # allow_redirects=False, which parses a malformed Location
            # header itself and raises a bare ValueError - not a
            # RequestException - straight out of requests.get().
            return _cap_response(
                {"url": start_url, "redirect_chain": redirect_chain, "error": _describe_error(exc)}
            )

        redirect_chain.append({"url": current_url, "status": response.status_code})

        location = response.headers.get("Location")
        if 300 <= response.status_code < 400 and location:
            response.close()
            try:
                current_url = urljoin(current_url, location)
            except ValueError as exc:
                # urljoin/urlparse raise for some malformed authorities (an
                # unbalanced "[") rather than returning an inert result.
                return _cap_response(
                    {
                        "url": start_url,
                        "redirect_chain": redirect_chain,
                        "error": f"malformed redirect Location: {exc}",
                    }
                )
            continue

        final_url = current_url
        content_type = (response.headers.get("Content-Type") or "").lower()
        is_html = "html" in content_type

        try:
            body, too_large = _read_body_with_limit(response, max_body_bytes)
        except requests.RequestException as exc:
            return _cap_response(
                {"url": start_url, "redirect_chain": redirect_chain, "error": _describe_error(exc)}
            )

        if too_large:
            return _cap_response(
                {
                    "url": start_url,
                    "redirect_chain": redirect_chain,
                    "error": f"response body exceeded {max_body_bytes} byte limit",
                }
            )

        if not is_html:
            return _cap_response(
                {
                    "url": start_url,
                    "redirect_chain": redirect_chain,
                    "final_url": final_url,
                    "forms": [],
                    "summary": (
                        f"Final response is not HTML (content-type: {content_type or 'unknown'}); "
                        "no forms to analyze."
                    ),
                }
            )

        forms = _extract_forms(body, final_url)
        suspicious = next((f for f in forms if f.get("asks_password") and f.get("cross_domain")), None)

        summary = (
            f"This page asks for a password and posts it to {suspicious['action_origin']}, "
            f"a different domain than {_origin(final_url)}."
            if suspicious
            else "No form on the final page asks for a password and posts cross-domain."
        )

        return _cap_response(
            {
                "url": start_url,
                "redirect_chain": redirect_chain,
                "final_url": final_url,
                "forms": forms,
                "summary": summary,
            }
        )

    # Unreachable: the loop always returns via one of the branches above.
    return _cap_response({"url": start_url, "redirect_chain": redirect_chain, "error": "unexpected loop exit"})
