"""Regression tests for the three Qodo findings on the normaliser (PR #6):

1. Multipart URLs silently omitted - only the HTML alternative was ever
   extracted, and a failed HTML parse returned nothing instead of falling
   back to plain text.
2. Sentence punctuation corrupted bare URLs (trailing '.', ',', '!', ')').
3. Non-web hrefs (mailto:, javascript:, fragments, relative paths) were
   reported as URLs even though url_reputation can't do anything with them.

Messages are built inline rather than from tools/fixtures/*.eml, which
don't exist yet on this branch (T-011).
"""

from __future__ import annotations

from imports_mcp.normaliser import parse_message

_HEADERS = (
    b"From: sender@example.com\r\n"
    b"To: victim@example.com\r\n"
    b"Subject: test\r\n"
    b"Date: Mon, 24 Aug 2026 10:00:00 +0000\r\n"
    b"Authentication-Results: mx.example.com; spf=pass\r\n"
    b"MIME-Version: 1.0\r\n"
)


def _single_part_eml(content_type: str, body: str) -> bytes:
    return _HEADERS + f'Content-Type: {content_type}; charset="utf-8"\r\n\r\n{body}'.encode()


def _multipart_alternative_eml(plain_body: str, html_body: str) -> bytes:
    boundary = b"BOUND1"
    parts = (
        _HEADERS
        + b'Content-Type: multipart/alternative; boundary="BOUND1"\r\n\r\n'
        + b"--" + boundary + b"\r\n"
        + b'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        + plain_body.encode() + b"\r\n"
        + b"--" + boundary + b"\r\n"
        + b'Content-Type: text/html; charset="utf-8"\r\n\r\n'
        + html_body.encode() + b"\r\n"
        + b"--" + boundary + b"--\r\n"
    )
    return parts


def _urls(raw: bytes) -> list[dict[str, str]]:
    return parse_message(raw)["urls"]


# --- Finding 1: both multipart alternatives, dedup, fallback on failed HTML parse ---


def test_extracts_urls_from_both_html_and_plain_alternatives():
    raw = _multipart_alternative_eml(
        plain_body="Also see http://plain-only.example/path for details.",
        html_body='<html><body><a href="http://html-only.example/path">click</a></body></html>',
    )
    hrefs = {u["href"] for u in _urls(raw)}
    assert hrefs == {"http://plain-only.example/path", "http://html-only.example/path"}


def test_same_url_in_both_alternatives_is_deduplicated_keeping_html_anchor_text():
    raw = _multipart_alternative_eml(
        plain_body="Link: http://shared.example/page",
        html_body='<html><body><a href="http://shared.example/page">Trust Me</a></body></html>',
    )
    urls = _urls(raw)
    matching = [u for u in urls if u["href"] == "http://shared.example/page"]
    assert len(matching) == 1
    assert matching[0]["anchor_text"] == "Trust Me"


def test_falls_back_to_plain_text_when_html_part_fails_to_parse():
    raw = _multipart_alternative_eml(
        plain_body="Backup link http://plain-fallback.example/x",
        html_body="",  # empty body makes lxml.html.fromstring raise
    )
    hrefs = {u["href"] for u in _urls(raw)}
    assert "http://plain-fallback.example/x" in hrefs


# --- Finding 2: trailing sentence punctuation stripped, legitimate punctuation kept ---


def test_strips_trailing_period():
    raw = _single_part_eml("text/plain", "Visit http://example.com/page. Thanks.")
    assert _urls(raw)[0]["href"] == "http://example.com/page"


def test_strips_trailing_comma():
    raw = _single_part_eml("text/plain", "See http://example.com/page, it's great")
    assert _urls(raw)[0]["href"] == "http://example.com/page"


def test_strips_trailing_exclamation_mark():
    raw = _single_part_eml("text/plain", "Check this out http://example.com/page!")
    assert _urls(raw)[0]["href"] == "http://example.com/page"


def test_strips_sentence_wrapping_parenthesis():
    raw = _single_part_eml("text/plain", "(see http://example.com/page)")
    assert _urls(raw)[0]["href"] == "http://example.com/page"


def test_strips_wrapping_parenthesis_and_trailing_period_together():
    raw = _single_part_eml("text/plain", "(see http://example.com/page).")
    assert _urls(raw)[0]["href"] == "http://example.com/page"


def test_preserves_balanced_parentheses_that_are_part_of_the_url():
    raw = _single_part_eml(
        "text/plain", "Read http://en.wikipedia.org/wiki/Example_(disambiguation) now"
    )
    assert _urls(raw)[0]["href"] == "http://en.wikipedia.org/wiki/Example_(disambiguation)"


def test_preserves_balanced_parentheses_with_trailing_sentence_period():
    raw = _single_part_eml(
        "text/plain", "See http://en.wikipedia.org/wiki/Example_(disambiguation)."
    )
    assert _urls(raw)[0]["href"] == "http://en.wikipedia.org/wiki/Example_(disambiguation)"


def test_preserves_query_string():
    raw = _single_part_eml("text/plain", "Go to http://example.com/page?id=1&ref=2 please")
    assert _urls(raw)[0]["href"] == "http://example.com/page?id=1&ref=2"


# --- Finding 3: only absolute http(s) hrefs from HTML, everything else dropped ---


def test_ignores_mailto_link():
    raw = _single_part_eml("text/html", '<a href="mailto:someone@example.com">email us</a>')
    assert _urls(raw) == []


def test_ignores_javascript_link():
    raw = _single_part_eml("text/html", '<a href="javascript:void(0)">click</a>')
    assert _urls(raw) == []


def test_ignores_bare_fragment():
    raw = _single_part_eml("text/html", '<a href="#section2">jump</a>')
    assert _urls(raw) == []


def test_ignores_unresolved_relative_link():
    raw = _single_part_eml("text/html", '<a href="/login">login</a>')
    assert _urls(raw) == []


def test_keeps_absolute_http_and_https_links():
    raw = _single_part_eml(
        "text/html",
        '<a href="http://one.example/a">one</a> <a href="https://two.example/b">two</a>',
    )
    hrefs = {u["href"] for u in _urls(raw)}
    assert hrefs == {"http://one.example/a", "https://two.example/b"}


def test_mixed_valid_and_invalid_hrefs_keeps_only_valid_ones():
    raw = _single_part_eml(
        "text/html",
        '<a href="https://real.example/x">real</a> '
        '<a href="mailto:a@b.com">mail</a> '
        '<a href="#top">top</a> '
        '<a href="/relative">rel</a>',
    )
    hrefs = {u["href"] for u in _urls(raw)}
    assert hrefs == {"https://real.example/x"}
