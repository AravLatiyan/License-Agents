"""Unit tests for url_reputation (T-021) — mocked network, deterministic.

Real field names (query_status, threat, tags, url_status, date_added) were
confirmed live against the actual URLhaus API before writing this - see
PLAN.md's T-021 entry - but the suite itself doesn't depend on a live key
or network access.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import requests

from imports_mcp.url_reputation import MAX_RESPONSE_BYTES, NOT_LISTED_NOTE, url_reputation

LISTED_RESPONSE = {
    "query_status": "ok",
    "id": "3908074",
    "url": "http://223.151.72.214:44130/i",
    "url_status": "online",
    "date_added": "2026-08-25 13:29:18 UTC",
    "threat": "malware_download",
    "tags": ["32-bit", "arm", "elf", "mirai", "Mozi"],
}

NOT_LISTED_RESPONSE = {"query_status": "no_results"}


def _mock_response(status_code=200, json_data=None, raise_for_json=False):
    resp = Mock()
    resp.status_code = status_code
    if raise_for_json:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_data
    return resp


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_listed_url_returns_verdict(mock_post):
    mock_post.return_value = _mock_response(200, LISTED_RESPONSE)

    result = url_reputation("http://223.151.72.214:44130/i")

    assert result["available"] is True
    assert result["listed"] is True
    assert result["threat"] == "malware_download"
    assert "mirai" in result["tags"]
    assert result["url_status"] == "online"
    assert result["note"] is None


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_not_listed_url_is_weak_signal_not_a_clean_bill_of_health(mock_post):
    mock_post.return_value = _mock_response(200, NOT_LISTED_RESPONSE)

    result = url_reputation("https://example.com/")

    assert result["available"] is True
    assert result["listed"] is False
    assert result["note"] == NOT_LISTED_NOTE


@patch.dict("os.environ", {}, clear=True)
def test_missing_auth_key_is_unavailable_not_a_crash():
    result = url_reputation("https://example.com/")

    assert result["available"] is False
    assert "URLHAUS_AUTH_KEY" in result["note"]


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "bad-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_401_is_unavailable_not_a_crash(mock_post):
    mock_post.return_value = _mock_response(401)

    result = url_reputation("https://example.com/")

    assert result["available"] is False
    assert "401" in result["note"]


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_non_200_is_unavailable_not_a_crash(mock_post):
    mock_post.return_value = _mock_response(500)

    result = url_reputation("https://example.com/")

    assert result["available"] is False
    assert "500" in result["note"]


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_network_failure_is_unavailable_not_a_crash(mock_post):
    mock_post.side_effect = requests.exceptions.Timeout("timed out")

    result = url_reputation("https://example.com/")

    assert result["available"] is False
    assert "timed out" in result["note"]


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_invalid_json_is_unavailable_not_a_crash(mock_post):
    mock_post.return_value = _mock_response(200, raise_for_json=True)

    result = url_reputation("https://example.com/")

    assert result["available"] is False
    assert "JSON" in result["note"]


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_unexpected_query_status_is_unavailable_not_a_crash(mock_post):
    mock_post.return_value = _mock_response(200, {"query_status": "invalid_url"})

    result = url_reputation("not-a-url")

    assert result["available"] is False
    assert "invalid_url" in result["note"]


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_null_json_response_is_unavailable_not_a_crash(mock_post):
    # Valid JSON (a 200 + json.loads succeeds) but not a JSON *object* -
    # data.get(...) would raise AttributeError on this without a guard.
    mock_post.return_value = _mock_response(200, None)

    result = url_reputation("https://example.com/")

    assert result["available"] is False
    assert "not a JSON object" in result["note"]


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_list_json_response_is_unavailable_not_a_crash(mock_post):
    mock_post.return_value = _mock_response(200, ["unexpected", "array"])

    result = url_reputation("https://example.com/")

    assert result["available"] is False
    assert "not a JSON object" in result["note"]


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_small_result_is_not_marked_truncated(mock_post):
    mock_post.return_value = _mock_response(200, LISTED_RESPONSE)

    result = url_reputation("http://223.151.72.214:44130/i")

    assert result["truncated"] is False
    assert "omitted" not in result


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_oversized_tags_are_truncated_under_the_2kb_cap(mock_post):
    huge_response = {
        **LISTED_RESPONSE,
        "tags": [f"tag-{i}-{'x' * 40}" for i in range(200)],
    }
    mock_post.return_value = _mock_response(200, huge_response)

    result = url_reputation("http://223.151.72.214:44130/i")

    assert result["truncated"] is True
    assert result["omitted"]["tags"] > 0
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= MAX_RESPONSE_BYTES


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_oversized_threat_url_status_and_date_added_are_truncated_under_the_cap(mock_post):
    # Before the fix, only tags/note/url were ever shrunk - an oversized
    # threat/url_status/date_added left the response over budget forever,
    # and a one-character note/url plateaued the shrink loop instead of
    # terminating (Qodo findings #3 and #8 on PR #19).
    huge_response = {
        **LISTED_RESPONSE,
        "tags": [],
        "threat": "malware_download " + "x" * 4000,
        "url_status": "online " + "y" * 4000,
        "date_added": "2026-08-25 " + "z" * 4000,
    }
    mock_post.return_value = _mock_response(200, huge_response)

    result = url_reputation("http://223.151.72.214:44130/i")

    assert result["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= MAX_RESPONSE_BYTES


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_shrink_loop_terminates_when_every_field_is_oversized_at_once(mock_post):
    # The exact scenario the old max(1, len(value) - 200) logic could hang
    # on: once note/url each plateau at one leftover character, an
    # unbounded threat/url_status/date_added kept the response over budget
    # with no field left that the old code would ever shrink further.
    huge_response = {
        "query_status": "ok",
        "id": "1",
        "url": "http://" + "u" * 4000,
        "url_status": "a" * 4000,
        "date_added": "b" * 4000,
        "threat": "c" * 4000,
        "tags": [f"tag-{i}" for i in range(500)],
    }
    mock_post.return_value = _mock_response(200, huge_response)

    result = url_reputation("http://" + "u" * 4000)

    assert result["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= MAX_RESPONSE_BYTES


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_non_list_tags_degrades_to_unavailable_instead_of_crashing(mock_post):
    # A malformed-but-valid-JSON tags field (an int here) used to reach the
    # caller as a contract-invalid shape and crash _cap_response's
    # list(tags) call outright for a non-iterable scalar.
    mock_post.return_value = _mock_response(200, {**LISTED_RESPONSE, "tags": 123})

    result = url_reputation("http://223.151.72.214:44130/i")

    assert result["available"] is False
    assert result["tags"] == []
    assert "unexpected shape" in result["note"]


@patch.dict("os.environ", {"URLHAUS_AUTH_KEY": "test-key"})
@patch("imports_mcp.url_reputation.requests.post")
def test_tags_with_non_string_elements_degrades_to_unavailable(mock_post):
    mock_post.return_value = _mock_response(200, {**LISTED_RESPONSE, "tags": ["ok", 123]})

    result = url_reputation("http://223.151.72.214:44130/i")

    assert result["available"] is False
    assert "unexpected shape" in result["note"]
