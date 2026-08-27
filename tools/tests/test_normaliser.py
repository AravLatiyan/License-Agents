"""Regression tests for the three Qodo findings on the normaliser (PR #6),
plus PR #19's integration-review findings:

1. Multipart URLs silently omitted - only the HTML alternative was ever
   extracted, and a failed HTML parse returned nothing instead of falling
   back to plain text.
2. Sentence punctuation corrupted bare URLs (trailing '.', ',', '!', ')').
3. Non-web hrefs (mailto:, javascript:, fragments, relative paths) were
   reported as URLs even though url_reputation can't do anything with them.
4. (PR #19) from/reply_to/return_path were nested address objects and
   authentication_results was a list, not the flat scalar shape the shared
   ParsedMessage contract and Cockpit's runtime validator require;
   message_id and top-level display_name were missing entirely.
5. (PR #19) get_body() only returns the single best-preference part per
   content type, silently skipping any secondary/nested multipart/
   alternative group (e.g. a forwarded message embedded as its own part).

Messages are built inline rather than from tools/fixtures/*.eml, which
don't exist yet on this branch (T-011).
"""

from __future__ import annotations

from imports_mcp.normaliser import parse_message

_HEADERS = (
    b"From: Sender Name <sender@example.com>\r\n"
    b"To: victim@example.com\r\n"
    b"Subject: test\r\n"
    b"Date: Mon, 24 Aug 2026 10:00:00 +0000\r\n"
    b"Message-ID: <fixed-id@example.com>\r\n"
    b"Authentication-Results: mx.example.com; spf=pass\r\n"
    b"MIME-Version: 1.0\r\n"
)


def _single_part_eml(content_type: str, body: str) -> bytes:
    return _HEADERS + f'Content-Type: {content_type}; charset="utf-8"\r\n\r\n{body}'.encode()


def _eml_with_headers(headers: bytes, content_type: str = "text/plain", body: str = "hi") -> bytes:
    """Same shape as _single_part_eml, but with a caller-supplied header
    block instead of the shared _HEADERS default - for tests that need to
    add/omit specific headers (Reply-To, Return-Path, a second
    Authentication-Results, ...) without fragile find-and-replace on bytes."""
    return headers + f'Content-Type: {content_type}; charset="utf-8"\r\n\r\n{body}'.encode()


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


# --- PR #19 finding 1: flat contract-matching shape, not nested/list fields ---


def test_from_reply_to_return_path_are_plain_address_strings():
    headers = (
        b"From: Sender Name <sender@example.com>\r\n"
        b"Reply-To: replyto@example.com\r\n"
        b"Return-Path: <bounce@example.com>\r\n"
        b"Subject: test\r\n"
        b"MIME-Version: 1.0\r\n"
    )
    result = parse_message(_eml_with_headers(headers))

    assert result["from"] == "sender@example.com"
    assert result["reply_to"] == "replyto@example.com"
    assert result["return_path"] == "bounce@example.com"
    assert result["display_name"] == "Sender Name"


def test_missing_reply_to_and_return_path_are_null_not_empty_dicts():
    result = parse_message(_single_part_eml("text/plain", "hi"))

    assert result["reply_to"] is None
    assert result["return_path"] is None


def test_from_header_with_no_display_name_leaves_display_name_null():
    headers = b"From: bare@example.com\r\nSubject: test\r\nMIME-Version: 1.0\r\n"
    result = parse_message(_eml_with_headers(headers))

    assert result["from"] == "bare@example.com"
    assert result["display_name"] is None


def test_message_id_is_extracted():
    result = parse_message(_single_part_eml("text/plain", "hi"))
    assert result["message_id"] == "<fixed-id@example.com>"


def test_missing_message_id_is_an_empty_string_not_missing():
    headers = b"From: sender@example.com\r\nSubject: test\r\nMIME-Version: 1.0\r\n"
    result = parse_message(_eml_with_headers(headers))
    assert result["message_id"] == ""


def test_authentication_results_is_a_single_joined_string_not_a_list():
    headers = _HEADERS + b"Authentication-Results: mx2.example.com; dkim=pass\r\n"
    result = parse_message(_eml_with_headers(headers))

    assert isinstance(result["authentication_results"], str)
    assert "spf=pass" in result["authentication_results"]
    assert "dkim=pass" in result["authentication_results"]


# --- PR #19 finding 5: every leaf part in the tree, not just get_body()'s pick ---


def _nested_multipart_alternative_eml(outer_plain: str, outer_html: str, inner_plain: str, inner_html: str) -> bytes:
    """multipart/mixed containing a text part plus an *embedded* rfc822
    message whose own body is itself a nested multipart/alternative - the
    shape get_body(preferencelist=...) only returns one part for, since it
    picks a single best part per content type at the top level."""
    outer = b"BOUND_OUTER"
    inner = b"BOUND_INNER"
    embedded_message = (
        b"From: forwarder@example.com\r\n"
        b"Subject: fwd\r\n"
        b'Content-Type: multipart/alternative; boundary="BOUND_INNER"\r\n\r\n'
        + b"--" + inner + b"\r\n"
        + b'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        + inner_plain.encode() + b"\r\n"
        + b"--" + inner + b"\r\n"
        + b'Content-Type: text/html; charset="utf-8"\r\n\r\n'
        + inner_html.encode() + b"\r\n"
        + b"--" + inner + b"--\r\n"
    )
    return (
        _HEADERS
        + b'Content-Type: multipart/mixed; boundary="BOUND_OUTER"\r\n\r\n'
        + b"--" + outer + b"\r\n"
        + b'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        + outer_plain.encode() + b"\r\n"
        + b"--" + outer + b"\r\n"
        + b'Content-Type: text/html; charset="utf-8"\r\n\r\n'
        + outer_html.encode() + b"\r\n"
        + b"--" + outer + b"\r\n"
        + b'Content-Type: message/rfc822\r\n\r\n'
        + embedded_message
        + b"\r\n--" + outer + b"--\r\n"
    )


def test_urls_from_a_nested_embedded_message_are_not_skipped():
    raw = _nested_multipart_alternative_eml(
        outer_plain="Outer plain http://outer-plain.example/x",
        outer_html='<a href="http://outer-html.example/x">outer</a>',
        inner_plain="Inner plain http://inner-plain.example/x",
        inner_html='<a href="http://inner-html.example/x">inner</a>',
    )
    hrefs = {u["href"] for u in _urls(raw)}
    assert hrefs == {
        "http://outer-plain.example/x",
        "http://outer-html.example/x",
        "http://inner-plain.example/x",
        "http://inner-html.example/x",
    }
