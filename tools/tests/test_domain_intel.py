"""Unit tests for domain_intel (T-020) — mocked network, deterministic.

crt.sh was down (502) for the entire time this feature was built (see
PLAN.md §7), so the suite can't depend on it being reachable. Every branch
is exercised with a mocked requests.get instead; live behavior was verified
manually against google.com and logged in PLAN.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
import requests

import imports_mcp.domain_intel as domain_intel_module
from imports_mcp.domain_intel import domain_intel

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
