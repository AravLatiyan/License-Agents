"""Unit tests for correspondence_history (T-022) — mocked network,
deterministic. Never touches a real Mailpit instance; see
test_server_integration_live.py for the opt-in live counterpart other
Mailpit-backed tools already use.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import requests

from imports_mcp.correspondence_history import MAX_RESPONSE_BYTES, correspondence_history


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


def _messages_response(messages):
    return {"messages": messages, "messages_count": len(messages), "total": len(messages)}


@patch("imports_mcp.correspondence_history.requests.get")
def test_no_prior_contact_returns_zero_history(mock_get):
    mock_get.return_value = _mock_response(200, _messages_response([_message("someone@else.example")]))

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["address"] == "ceo@northgate-trust.example"
    assert result["domain"] == "northgate-trust.example"
    assert result["prior_contact_count"] == 0
    assert result["first_seen"] is None
    assert result["last_seen"] is None
    assert result["domains_used"] == []


@patch("imports_mcp.correspondence_history.requests.get")
def test_matches_by_exact_address(mock_get):
    mock_get.return_value = _mock_response(
        200, _messages_response([_message("ceo@northgate-trust.example")])
    )

    result = correspondence_history("ceo@northgate-trust.example", "some-other-domain.example")

    assert result["prior_contact_count"] == 1
    assert result["domains_used"] == ["northgate-trust.example"]


@patch("imports_mcp.correspondence_history.requests.get")
def test_matches_by_domain_even_when_address_differs(mock_get):
    mock_get.return_value = _mock_response(
        200, _messages_response([_message("billing@northgate-trust.example")])
    )

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 1
    assert result["domains_used"] == ["northgate-trust.example"]


@patch("imports_mcp.correspondence_history.requests.get")
def test_matching_is_case_insensitive(mock_get):
    mock_get.return_value = _mock_response(
        200, _messages_response([_message("CEO@Northgate-Trust.example")])
    )

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 1


@patch("imports_mcp.correspondence_history.requests.get")
def test_multiple_matching_messages_are_all_counted_with_correct_date_ordering(mock_get):
    mock_get.return_value = _mock_response(
        200,
        _messages_response(
            [
                _message("ceo@northgate-trust.example", created="2026-08-20T10:00:00.000000Z"),
                _message("ceo@northgate-trust.example", created="2023-02-11T08:15:00.000000Z"),
                _message("ceo@northgate-trust.example", created="2026-08-25T12:30:00.000000Z"),
                _message("unrelated@else.example", created="2026-08-26T00:00:00.000000Z"),
            ]
        ),
    )

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 3
    assert result["first_seen"] == "2023-02-11T08:15:00.000000Z"
    assert result["last_seen"] == "2026-08-25T12:30:00.000000Z"


@patch("imports_mcp.correspondence_history.requests.get")
def test_domains_used_covers_every_distinct_matched_sender_domain(mock_get):
    # address and domain deliberately don't correspond to the same identity -
    # one match comes from the exact-address branch (a different domain than
    # the domain param), the other from the domain branch - domains_used
    # must reflect both real domains actually seen, not just echo the input.
    mock_get.return_value = _mock_response(
        200,
        _messages_response(
            [
                _message("ceo@northgate-trust.example"),
                _message("billing@meridian-courier.example"),
            ]
        ),
    )

    result = correspondence_history("ceo@northgate-trust.example", "meridian-courier.example")

    assert result["prior_contact_count"] == 2
    assert result["domains_used"] == ["meridian-courier.example", "northgate-trust.example"]


@patch("imports_mcp.correspondence_history.requests.get")
def test_message_missing_created_still_counts_but_is_excluded_from_date_range(mock_get):
    mock_get.return_value = _mock_response(
        200,
        _messages_response(
            [
                {"From": {"Address": "ceo@northgate-trust.example"}},  # no Created at all
                _message("ceo@northgate-trust.example", created="2026-08-20T10:00:00.000000Z"),
            ]
        ),
    )

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 2
    assert result["first_seen"] == "2026-08-20T10:00:00.000000Z"
    assert result["last_seen"] == "2026-08-20T10:00:00.000000Z"


@patch("imports_mcp.correspondence_history.requests.get")
def test_malformed_message_entries_are_skipped_not_crashing(mock_get):
    mock_get.return_value = _mock_response(
        200,
        _messages_response(
            [
                "not a dict",
                {"From": "not a dict either"},
                {"From": {"Address": 12345}},  # not a string
                {"From": {"Address": "no-at-sign"}},  # no @
                {"From": {}},  # missing Address entirely
                _message("ceo@northgate-trust.example"),  # the one real match
            ]
        ),
    )

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 1


@patch("imports_mcp.correspondence_history.requests.get")
def test_network_failure_degrades_to_zero_history_not_a_crash(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout("timed out")

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 0
    assert result["first_seen"] is None
    assert result["domains_used"] == []


@patch("imports_mcp.correspondence_history.requests.get")
def test_non_200_degrades_to_zero_history(mock_get):
    mock_get.return_value = _mock_response(500)

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 0


@patch("imports_mcp.correspondence_history.requests.get")
def test_invalid_json_degrades_to_zero_history(mock_get):
    mock_get.return_value = _mock_response(200, raise_for_json=True)

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 0


@patch("imports_mcp.correspondence_history.requests.get")
def test_non_dict_json_response_degrades_to_zero_history(mock_get):
    mock_get.return_value = _mock_response(200, ["unexpected", "array"])

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 0


@patch("imports_mcp.correspondence_history.requests.get")
def test_messages_field_not_a_list_degrades_to_zero_history(mock_get):
    mock_get.return_value = _mock_response(200, {"messages": "not-a-list"})

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 0


@patch("imports_mcp.correspondence_history.requests.get")
def test_missing_messages_field_degrades_to_zero_history(mock_get):
    mock_get.return_value = _mock_response(200, {"messages_count": 0})

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["prior_contact_count"] == 0


@patch.dict("os.environ", {"MAILPIT_URL": "http://mailpit-test-host:9999"})
@patch("imports_mcp.correspondence_history.requests.get")
def test_mailpit_url_env_var_is_used(mock_get):
    mock_get.return_value = _mock_response(200, _messages_response([]))

    correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    called_url = mock_get.call_args[0][0]
    assert called_url == "http://mailpit-test-host:9999/api/v1/messages"


@patch.dict("os.environ", {"MAILPIT_URL": ""})
@patch("imports_mcp.correspondence_history.requests.get")
def test_blank_mailpit_url_env_var_falls_back_to_the_range_default(mock_get):
    # .env.example ships MAILPIT_URL= (blank) - os.environ.get(k, default)
    # would return "" as-is rather than defaulting, the exact SMTP_HOST bug
    # Qodo caught on PR #29 (_smtp.py's smtp_target()).
    mock_get.return_value = _mock_response(200, _messages_response([]))

    correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    called_url = mock_get.call_args[0][0]
    assert called_url == "http://localhost:8025/api/v1/messages"


@patch("imports_mcp.correspondence_history.requests.get")
def test_small_result_is_not_marked_truncated(mock_get):
    mock_get.return_value = _mock_response(200, _messages_response([]))

    result = correspondence_history("ceo@northgate-trust.example", "northgate-trust.example")

    assert result["truncated"] is False
    assert "omitted" not in result


@patch("imports_mcp.correspondence_history.requests.get")
def test_oversized_address_and_domain_are_truncated_under_the_2kb_cap(mock_get):
    # domains_used can only ever hold `domain` or address's own domain (at
    # most 2 short strings, by construction of the matching rule) - the
    # only fields actually capable of blowing the budget are the
    # caller-echoed address/domain themselves. The MCP wrapper normally
    # bounds their length before this module ever runs, but the module is
    # tested independently of that wrapper, same as domain_intel.py.
    mock_get.return_value = _mock_response(200, _messages_response([]))
    huge_address = "a" * 4000 + "@example.com"
    huge_domain = "b" * 4000 + ".example.com"

    result = correspondence_history(huge_address, huge_domain)

    assert result["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= MAX_RESPONSE_BYTES
