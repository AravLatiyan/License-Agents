"""Regression tests for Qodo's PR #63 re-review of `correspondence_history`
(T-022): pagination, timestamp comparison, and the 2KB response cap.

These belong with `test_correspondence_history.py` by subject, but that
file lives on the stacked PR #64, already open — a same-named or merged-in
file here would collide with it once both land. Kept as its own file
instead, mirroring the same split T-026's PR #37 used for its own Qodo-fix
regression tests (`test_server_detonate_contract.py`, not `test_detonate.py`
on the stacked PR #38) — flagged for whoever merges both PRs to consider
consolidating.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import requests

from imports_mcp.correspondence_history import (
    MAX_RESPONSE_BYTES,
    _parse_created,
    correspondence_history,
)


def _mock_response(status_code=200, json_data=None, raise_for_json=False):
    resp = Mock()
    resp.status_code = status_code
    if raise_for_json:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_data
    return resp


def _message(address, created="2026-08-20T10:00:00.000000Z"):
    return {"From": {"Address": address, "Name": ""}, "Created": created}


def _page(messages, total):
    return {"messages": messages, "messages_count": len(messages), "total": total}


# --- Finding #1: "History stops after 1,000" — pagination ---


@patch("imports_mcp.correspondence_history._MESSAGES_PAGE_SIZE", 3)
@patch("imports_mcp.correspondence_history.requests.get")
def test_a_match_beyond_the_first_page_is_still_found(mock_get):
    # Page 1: 3 unrelated messages, doesn't include the match. Page 2: the
    # one matching message, total=4 tells the loop it's done after this.
    page1 = _page([_message(f"nobody{i}@else.example") for i in range(3)], total=4)
    page2 = _page([_message("ceo@northgate-trust.example")], total=4)
    mock_get.side_effect = [_mock_response(200, page1), _mock_response(200, page2)]

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 1
    assert mock_get.call_count == 2


@patch("imports_mcp.correspondence_history._MESSAGES_PAGE_SIZE", 3)
@patch("imports_mcp.correspondence_history.requests.get")
def test_pagination_requests_successive_start_offsets(mock_get):
    page1 = _page([_message(f"nobody{i}@else.example") for i in range(3)], total=5)
    page2 = _page([_message(f"nobody{i}@else.example") for i in range(2)], total=5)
    mock_get.side_effect = [_mock_response(200, page1), _mock_response(200, page2)]

    correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    starts = [call.kwargs["params"]["start"] for call in mock_get.call_args_list]
    assert starts == [0, 3]


@patch("imports_mcp.correspondence_history._MESSAGES_PAGE_SIZE", 3)
@patch("imports_mcp.correspondence_history.requests.get")
def test_pagination_stops_on_an_empty_page_when_total_is_unreliable(mock_get):
    # total is deliberately wrong (claims far more exist than ever arrive) -
    # the empty-page fallback must still terminate correctly, not hang.
    page1 = _page([_message(f"nobody{i}@else.example") for i in range(3)], total=999)
    page2 = _page([], total=999)
    mock_get.side_effect = [_mock_response(200, page1), _mock_response(200, page2)]

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 0
    assert mock_get.call_count == 2


@patch("imports_mcp.correspondence_history._MAX_MESSAGES_FETCHED", 10)
@patch("imports_mcp.correspondence_history._MESSAGES_PAGE_SIZE", 3)
@patch("imports_mcp.correspondence_history.requests.get")
def test_pagination_stops_at_the_safety_cap_instead_of_hanging(mock_get):
    # Every page is full, non-empty, and total always claims more remain -
    # without a hard cap independent of total, this would never terminate.
    def always_full_page(*args, **kwargs):
        return _mock_response(200, _page([_message(f"x{i}@else.example") for i in range(3)], total=999999))

    mock_get.side_effect = always_full_page

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    # Capped at 10 messages / 3 per page = exactly 4 calls (starts 0,3,6,9;
    # after the 4th, 12 collected >= 10, the cap fires).
    assert mock_get.call_count == 4
    assert result["prior_contact_count"] == 0  # none of the fetched messages match


@patch("imports_mcp.correspondence_history._MESSAGES_PAGE_SIZE", 3)
@patch("imports_mcp.correspondence_history.requests.get")
def test_a_later_page_failing_degrades_the_whole_call_to_zero_history(mock_get):
    # Page 1 succeeds and implies more pages exist; page 2 fails outright -
    # the partial page-1-only result must not be returned as if complete.
    page1 = _page([_message("ceo@northgate-trust.example")] + [_message(f"x{i}@e.example") for i in range(2)], total=10)
    mock_get.side_effect = [_mock_response(200, page1), requests.exceptions.Timeout("timed out")]

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 0
    assert result["first_seen"] is None


@patch("imports_mcp.correspondence_history.requests.get")
def test_empty_mailbox_makes_exactly_one_request(mock_get):
    mock_get.return_value = _mock_response(200, _page([], total=0))

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 0
    assert mock_get.call_count == 1


# --- Finding #2: "Timestamp bounds sort incorrectly" ---


def test_parse_created_handles_variable_fractional_precision():
    # Go's RFC3339Nano trims trailing zeros from the fractional component,
    # so ".1Z" (100ms) and ".12Z" (120ms) are both real, valid outputs -
    # .12Z is chronologically LATER despite being lexically SMALLER
    # ("...0.12Z" < "...0.1Z" as plain strings, since '2' < 'Z' in ASCII).
    earlier = _parse_created("2026-08-20T10:00:00.1Z")
    later = _parse_created("2026-08-20T10:00:00.12Z")
    assert earlier is not None and later is not None
    assert earlier < later


def test_parse_created_compares_across_differing_utc_offsets():
    # 10:00 UTC vs 09:00-02:00 (== 11:00 UTC) - the second is later despite
    # its raw string sorting lexically *before* the first ("09" < "10").
    a = _parse_created("2026-08-20T10:00:00+00:00")
    b = _parse_created("2026-08-20T09:00:00-02:00")
    assert a is not None and b is not None
    assert b > a


def test_parse_created_rejects_a_naive_timestamp_without_a_timezone():
    assert _parse_created("2026-08-20T10:00:00") is None


def test_parse_created_rejects_unparseable_values():
    assert _parse_created("not-a-date") is None
    assert _parse_created("") is None


@patch("imports_mcp.correspondence_history.requests.get")
def test_first_and_last_seen_are_chronologically_correct_not_lexically(mock_get):
    # Three messages whose Created values are chronologically ordered
    # earliest-to-latest but would sort *wrong* as plain strings: the
    # fractional-precision case is the deciding one (.12Z before .1Z
    # lexically, though .12Z is later).
    messages = [
        _message("ceo@northgate-trust.example", created="2026-08-20T10:00:00.12Z"),  # actually 3rd
        _message("ceo@northgate-trust.example", created="2026-08-19T23:59:59Z"),  # actually 1st
        _message("ceo@northgate-trust.example", created="2026-08-20T10:00:00.1Z"),  # actually 2nd
    ]
    mock_get.return_value = _mock_response(200, _page(messages, total=3))

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["first_seen"] == "2026-08-19T23:59:59Z"
    assert result["last_seen"] == "2026-08-20T10:00:00.12Z"


@patch("imports_mcp.correspondence_history.requests.get")
def test_a_matched_message_with_an_unparseable_created_still_counts(mock_get):
    messages = [
        {"From": {"Address": "ceo@northgate-trust.example"}, "Created": "not-a-real-timestamp"},
        _message("ceo@northgate-trust.example", created="2026-08-20T10:00:00Z"),
    ]
    mock_get.return_value = _mock_response(200, _page(messages, total=2))

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 2
    assert result["first_seen"] == "2026-08-20T10:00:00Z"
    assert result["last_seen"] == "2026-08-20T10:00:00Z"


# --- Finding #3: "_cap_response can exceed 2KB" ---


@patch("imports_mcp.correspondence_history.requests.get")
def test_an_oversized_created_value_in_first_seen_last_seen_is_truncated_under_the_cap(mock_get):
    # A syntactically-valid-but-absurdly-long fractional-seconds string
    # parses successfully (verified directly against datetime.fromisoformat
    # before writing this test) and would previously have reached
    # first_seen/last_seen completely untouched by the old cap, which only
    # ever trimmed address/domain.
    huge_created = "2026-08-20T10:00:00." + "1" * 4000 + "Z"
    mock_get.return_value = _mock_response(200, _page([_message("ceo@northgate-trust.example", created=huge_created)], total=1))

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= MAX_RESPONSE_BYTES
    # The structured field is never dropped, just the oversized strings.
    assert result["prior_contact_count"] == 1


@patch("imports_mcp.correspondence_history.requests.get")
def test_domains_used_list_is_trimmed_then_still_oversized_address_and_domain_are_shrunk(mock_get):
    # Two independently-matching domains (address-exact + domain-exact),
    # each one itself absurdly long. domains_used entries are removed
    # wholesale (the list-trim tier, same as url_reputation's `tags`) -
    # since address/domain themselves are also huge here, removing every
    # domains_used entry alone still isn't enough, so the string-shrink
    # tier then has to trim address/domain too. Both tiers exercised in
    # one test, in the order the function actually applies them.
    huge_domain_1 = "a" * 3000 + ".example"
    huge_domain_2 = "b" * 3000 + ".example"
    messages = [
        _message(f"target@{huge_domain_1}"),
        _message(f"other@{huge_domain_2}"),
    ]
    mock_get.return_value = _mock_response(200, _page(messages, total=2))

    result = correspondence_history(f"target@{huge_domain_1}", huge_domain_2)

    assert result["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= MAX_RESPONSE_BYTES
    assert result["prior_contact_count"] == 2
