"""Unit tests for domain_intel (T-020) — mocked network, deterministic.

crt.sh was down (502) for the entire time this feature was built (see
PLAN.md §7), so the suite can't depend on it being reachable. Every branch
is exercised with a mocked requests.get instead; live behavior was verified
manually against google.com and logged in PLAN.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
import requests

import imports_mcp.domain_intel as domain_intel_module
from imports_mcp.domain_intel import MAX_RESPONSE_BYTES, domain_intel

# Certificate ages must be computed relative to "now", not a hardcoded date,
# or this test starts failing the day after it's written.
_NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clear_crtsh_cache():
    """The cache is module-level and persists across tests; several tests
    below reuse the same domain name, so a hit from an earlier test would
    otherwise silently mask what this test is actually checking."""
    domain_intel_module._crtsh_cache.clear()
    yield
    domain_intel_module._crtsh_cache.clear()


def _days_ago(n: int) -> str:
    return (_NOW - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%S")

RDAP_SUCCESS = {
    "events": [
        {"eventAction": "registration", "eventDate": "1997-09-15T04:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2028-09-14T04:00:00Z"},
    ],
    "entities": [
        {
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "MarkMonitor Inc."]]],
            "entities": [
                {
                    "roles": ["abuse"],
                    "vcardArray": [
                        "vcard",
                        [["fn", {}, "text", ""], ["email", {}, "text", "abusecomplaints@markmonitor.com"]],
                    ],
                }
            ],
        }
    ],
}

CRTSH_SUCCESS = [
    {"id": 1, "not_before": _days_ago(1), "not_after": "2099-01-01T00:00:00"},
    {"id": 2, "not_before": _days_ago(5), "not_after": "2099-01-01T00:00:00"},
]


def _mock_response(status_code=200, json_data=None, raise_for_json=False):
    resp = Mock()
    resp.status_code = status_code
    if raise_for_json:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_data
    return resp


@patch("imports_mcp.domain_intel.requests.get")
def test_rdap_and_crtsh_success(mock_get):
    mock_get.side_effect = [
        _mock_response(200, RDAP_SUCCESS),
        _mock_response(200, CRTSH_SUCCESS),
    ]
    result = domain_intel("example.com")

    assert result["rdap"]["available"] is True
    assert result["rdap"]["registrar"] == "MarkMonitor Inc."
    assert result["rdap"]["registration_date"] == "1997-09-15T04:00:00Z"
    assert result["rdap"]["abuse_contact"] == "abusecomplaints@markmonitor.com"
    assert result["rdap"]["note"] is None

    assert result["cert"]["available"] is True
    assert result["cert"]["earliest_seen"] == _days_ago(5) + "+00:00"
    assert result["cert"]["age_days"] == 5
    assert result["cert"]["note"] is None


@patch("imports_mcp.domain_intel.requests.get")
def test_rdap_registration_date_not_published(mock_get):
    data = {"events": [], "entities": []}
    mock_get.side_effect = [_mock_response(200, data), _mock_response(502)]
    result = domain_intel("redacted.example")

    assert result["rdap"]["available"] is True
    assert result["rdap"]["registration_date"] is None
    assert result["rdap"]["note"] == "registration date not published"


@patch("imports_mcp.domain_intel.requests.get")
def test_rdap_domain_not_found(mock_get):
    mock_get.side_effect = [_mock_response(404), _mock_response(502)]
    result = domain_intel("nope.example")

    assert result["rdap"]["available"] is False
    assert result["rdap"]["note"] == "domain not found in RDAP"


@patch("imports_mcp.domain_intel.requests.get")
def test_rdap_network_failure_degrades_gracefully(mock_get):
    mock_get.side_effect = [requests.exceptions.Timeout("timed out"), _mock_response(502)]
    result = domain_intel("slow.example")

    assert result["rdap"]["available"] is False
    assert "timed out" in result["rdap"]["note"]


@patch("imports_mcp.domain_intel.requests.get")
def test_crtsh_502_degrades_gracefully_and_rdap_still_returned(mock_get):
    mock_get.side_effect = [_mock_response(200, RDAP_SUCCESS), _mock_response(502)]
    result = domain_intel("example.com")

    assert result["rdap"]["available"] is True
    assert result["cert"]["available"] is False
    assert result["cert"]["note"] == "crt.sh returned HTTP 502"


@patch("imports_mcp.domain_intel.requests.get")
def test_crtsh_empty_result_set(mock_get):
    mock_get.side_effect = [_mock_response(200, RDAP_SUCCESS), _mock_response(200, [])]
    result = domain_intel("example.com")

    assert result["cert"]["available"] is True
    assert result["cert"]["age_days"] is None
    assert result["cert"]["note"] == "no certificates logged for this domain"


@patch("imports_mcp.domain_intel.requests.get")
def test_crtsh_success_is_cached_across_calls(mock_get):
    mock_get.side_effect = [
        _mock_response(200, RDAP_SUCCESS),
        _mock_response(200, CRTSH_SUCCESS),
        _mock_response(200, RDAP_SUCCESS),
    ]
    domain_intel("cache-me.example")
    domain_intel("cache-me.example")

    # 2 RDAP calls (never cached) + 1 crt.sh call (cached after the first)
    assert mock_get.call_count == 3


@patch("imports_mcp.domain_intel.requests.get")
def test_crtsh_transient_failure_is_not_cached(mock_get):
    mock_get.side_effect = [
        _mock_response(200, RDAP_SUCCESS),
        requests.exceptions.Timeout("timed out"),
        _mock_response(200, RDAP_SUCCESS),
        _mock_response(200, CRTSH_SUCCESS),
    ]
    first = domain_intel("retry-me.example")
    second = domain_intel("retry-me.example")

    assert first["cert"]["available"] is False
    assert second["cert"]["available"] is True
    assert mock_get.call_count == 4


# --- crt.sh cache TTL: fresh entries are reused, expired ones are re-fetched ---


@patch("imports_mcp.domain_intel.time.time")
@patch("imports_mcp.domain_intel.requests.get")
def test_crtsh_cache_hit_within_ttl_does_not_refetch(mock_get, mock_time):
    mock_get.side_effect = [
        _mock_response(200, RDAP_SUCCESS),
        _mock_response(200, CRTSH_SUCCESS),
        _mock_response(200, RDAP_SUCCESS),
    ]
    mock_time.return_value = 1_000_000.0
    domain_intel("ttl-fresh.example")

    mock_time.return_value = 1_000_000.0 + domain_intel_module.CRTSH_CACHE_TTL_SECONDS - 1
    domain_intel("ttl-fresh.example")

    # 2 RDAP calls (never cached) + 1 crt.sh call (still fresh, cache hit)
    assert mock_get.call_count == 3


@patch("imports_mcp.domain_intel.time.time")
@patch("imports_mcp.domain_intel.requests.get")
def test_crtsh_cache_expires_after_ttl_and_refetches(mock_get, mock_time):
    mock_get.side_effect = [
        _mock_response(200, RDAP_SUCCESS),
        _mock_response(200, CRTSH_SUCCESS),
        _mock_response(200, RDAP_SUCCESS),
        _mock_response(200, CRTSH_SUCCESS),
    ]
    mock_time.return_value = 1_000_000.0
    domain_intel("ttl-expired.example")

    mock_time.return_value = 1_000_000.0 + domain_intel_module.CRTSH_CACHE_TTL_SECONDS + 1
    domain_intel("ttl-expired.example")

    # 2 RDAP calls + 2 crt.sh calls - the cached entry expired, so it refetched
    assert mock_get.call_count == 4


# --- ~2KB response cap: structured fields kept, free-text fields shortened ---


def _response_size(result: dict) -> int:
    return len(json.dumps(result).encode("utf-8"))


@patch("imports_mcp.domain_intel.requests.get")
def test_normal_response_is_not_truncated(mock_get):
    mock_get.side_effect = [_mock_response(200, RDAP_SUCCESS), _mock_response(200, CRTSH_SUCCESS)]
    result = domain_intel("example.com")

    assert result["truncated"] is False
    assert _response_size(result) <= MAX_RESPONSE_BYTES


@patch("imports_mcp.domain_intel.requests.get")
def test_oversized_caller_domain_is_truncated_with_flag(mock_get):
    mock_get.side_effect = [_mock_response(200, RDAP_SUCCESS), _mock_response(200, CRTSH_SUCCESS)]
    huge_domain = "a" * 5000 + ".example"

    result = domain_intel(huge_domain)

    assert result["truncated"] is True
    assert len(result["domain"]) < len(huge_domain)
    assert _response_size(result) <= MAX_RESPONSE_BYTES


@patch("imports_mcp.domain_intel.requests.get")
def test_oversized_upstream_field_is_truncated_with_flag(mock_get):
    bloated_rdap = {**RDAP_SUCCESS}
    bloated_rdap["entities"] = [
        {
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["fn", {}, "text", "X" * 5000]]],
        }
    ]
    mock_get.side_effect = [_mock_response(200, bloated_rdap), _mock_response(200, CRTSH_SUCCESS)]

    result = domain_intel("example.com")

    assert result["truncated"] is True
    assert len(result["rdap"]["registrar"]) < 5000
    assert _response_size(result) <= MAX_RESPONSE_BYTES


# --- malformed-but-valid JSON: degrade gracefully, keep sources independent ---


@patch("imports_mcp.domain_intel.requests.get")
def test_rdap_non_dict_top_level_degrades_without_raising(mock_get):
    mock_get.side_effect = [_mock_response(200, ["not", "a", "dict"]), _mock_response(200, CRTSH_SUCCESS)]

    result = domain_intel("example.com")

    assert result["rdap"]["available"] is False
    assert "unexpected" in result["rdap"]["note"] or "not a JSON object" in result["rdap"]["note"]
    assert result["cert"]["available"] is True  # crt.sh still ran independently


@patch("imports_mcp.domain_intel.requests.get")
def test_rdap_non_iterable_events_degrades_without_raising(mock_get):
    # An int isn't iterable at all (unlike a string, which would just
    # iterate to individual characters and get filtered out harmlessly) -
    # this is what actually needs the except boundary to avoid a TypeError.
    malformed = {"events": 42, "entities": []}
    mock_get.side_effect = [_mock_response(200, malformed), _mock_response(200, CRTSH_SUCCESS)]

    result = domain_intel("example.com")

    assert result["rdap"]["available"] is False
    assert result["cert"]["available"] is True


@patch("imports_mcp.domain_intel.requests.get")
def test_rdap_non_list_events_value_degrades_instead_of_marked_available(mock_get):
    # A string IS iterable (iterates to characters), so without an explicit
    # isinstance(events, list) check this used to sail past the isinstance
    # dict filter, find no dict-shaped event, and come back available=True
    # with "not published" - reporting a malformed response as a domain with
    # no registration event on file. events is now strictly required to be
    # a list, so this is caught before any iteration happens.
    malformed = {"events": "not-a-list", "entities": []}
    mock_get.side_effect = [_mock_response(200, malformed), _mock_response(200, CRTSH_SUCCESS)]

    result = domain_intel("example.com")

    assert result["rdap"]["available"] is False
    assert "events" in result["rdap"]["note"]
    assert result["cert"]["available"] is True  # crt.sh still ran independently


@patch("imports_mcp.domain_intel.requests.get")
def test_rdap_non_dict_entity_in_entities_is_skipped_not_raised(mock_get):
    malformed = {"events": [], "entities": ["not-a-dict", 42, None]}
    mock_get.side_effect = [_mock_response(200, malformed), _mock_response(200, CRTSH_SUCCESS)]

    result = domain_intel("example.com")

    assert result["rdap"]["available"] is True
    assert result["rdap"]["registrar"] is None
    assert result["cert"]["available"] is True


@patch("imports_mcp.domain_intel.requests.get")
def test_crtsh_non_list_top_level_degrades_without_raising(mock_get):
    mock_get.side_effect = [_mock_response(200, RDAP_SUCCESS), _mock_response(200, {"not": "a list"})]

    result = domain_intel("example.com")

    assert result["cert"]["available"] is False
    assert result["cert"]["note"] == "crt.sh response was not a JSON array"
    assert result["rdap"]["available"] is True  # RDAP still returned independently


@patch("imports_mcp.domain_intel.requests.get")
def test_crtsh_non_dict_entries_are_skipped_not_raised(mock_get):
    mixed_entries = ["not-a-dict", CRTSH_SUCCESS[0], 42, None]
    mock_get.side_effect = [_mock_response(200, RDAP_SUCCESS), _mock_response(200, mixed_entries)]

    result = domain_intel("example.com")

    assert result["cert"]["available"] is True
    assert result["cert"]["age_days"] is not None


# --- JSON decode failures: each source's own decode error, independently ---


@patch("imports_mcp.domain_intel.requests.get")
def test_rdap_json_decode_failure_degrades_and_crtsh_still_returns(mock_get):
    mock_get.side_effect = [
        _mock_response(200, raise_for_json=True),
        _mock_response(200, CRTSH_SUCCESS),
    ]

    result = domain_intel("example.com")

    assert result["rdap"]["available"] is False
    assert result["rdap"]["note"] == "RDAP response was not valid JSON"
    assert result["cert"]["available"] is True  # crt.sh still ran independently


@patch("imports_mcp.domain_intel.requests.get")
def test_crtsh_json_decode_failure_degrades_and_rdap_still_returns(mock_get):
    mock_get.side_effect = [
        _mock_response(200, RDAP_SUCCESS),
        _mock_response(200, raise_for_json=True),
    ]

    result = domain_intel("example.com")

    assert result["cert"]["available"] is False
    assert result["cert"]["note"] == "crt.sh response was not valid JSON"
    assert result["rdap"]["available"] is True  # RDAP still returned independently
