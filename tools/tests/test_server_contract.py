"""Contract tests for the parse_message tool (T-012) against the 3 T-011 fixtures.

Calls the plain function directly - @mcp.tool() registers it but returns the
original callable unchanged, so no transport is needed here. The transport
itself is covered separately in test_server_integration.py.
"""

from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.server import FIXTURES_DIR, MAX_RESPONSE_BYTES, _cap_response, parse_message

CONTRACT_KEYS = (
    "from",
    "reply_to",
    "return_path",
    "subject",
    "date",
    "authentication_results",
    "received_chain",
    "urls",
    "attachments",
    "truncated",
)

FIXTURE_NAMES = sorted(p.name for p in FIXTURES_DIR.glob("*.eml"))


def test_exactly_three_fixtures_present():
    assert len(FIXTURE_NAMES) == 3


@pytest.mark.parametrize("fixture", FIXTURE_NAMES)
def test_parse_message_returns_full_contract(fixture):
    result = parse_message(fixture)
    assert set(result.keys()) == set(CONTRACT_KEYS)


def test_credential_phish_fails_auth_with_mismatched_link():
    result = parse_message("01-credential-phish.eml")
    auth = result["authentication_results"][0]
    assert "spf=fail" in auth
    assert "dmarc=fail" in auth
    assert len(result["urls"]) == 1
    url = result["urls"][0]
    assert url["href"] != url["anchor_text"]
    assert url["href"].startswith("http://185.220.101.7/")


def test_invoice_fraud_bec_has_lookalike_domain_and_attachment():
    result = parse_message("02-invoice-fraud-bec.eml")
    assert result["from"]["address"] == "naitik.srivastava@universaI-imports.co"
    assert result["reply_to"]["address"] != result["from"]["address"]
    assert "spf=pass" in result["authentication_results"][0]
    assert len(result["attachments"]) == 1
    assert len(result["attachments"][0]["sha256"]) == 64


def test_legitimate_mail_matches_domains_throughout():
    result = parse_message("03-legitimate.eml")
    domains = {
        result["from"]["address"].split("@")[1],
        result["reply_to"]["address"].split("@")[1],
        result["return_path"]["address"].split("@")[1],
    }
    assert domains == {"universal-imports.example"}
    assert "spf=pass" in result["authentication_results"][0]
    assert result["attachments"] == []


def test_unknown_fixture_is_rejected():
    with pytest.raises(ToolError):
        parse_message("does-not-exist.eml")


def test_path_traversal_is_rejected():
    with pytest.raises(ToolError):
        parse_message("../../.env")


def test_non_eml_file_in_fixtures_dir_is_rejected():
    # A real, regular file inside FIXTURES_DIR that isn't on the advertised
    # .eml whitelist must still be refused, not just path traversal.
    decoy = FIXTURES_DIR / "not-a-fixture.txt"
    decoy.write_text("not an eml file")
    try:
        with pytest.raises(ToolError):
            parse_message("not-a-fixture.txt")
    finally:
        decoy.unlink()


def test_cap_response_leaves_small_results_untouched():
    small = {"authentication_results": [], "received_chain": [], "urls": [], "attachments": []}
    capped = _cap_response(small)
    assert capped["truncated"] is False
    assert "omitted" not in capped


def test_cap_response_truncates_oversized_received_chain_under_the_2kb_cap():
    huge = {
        "from": None,
        "reply_to": None,
        "return_path": None,
        "subject": "",
        "date": "",
        "urls": [],
        "attachments": [],
        "authentication_results": [],
        "received_chain": [f"Received: from host{i}.example ({'x' * 80})" for i in range(200)],
    }
    capped = _cap_response(huge)
    assert capped["truncated"] is True
    assert capped["omitted"]["received_chain"] > 0
    assert len(json.dumps(capped, ensure_ascii=False).encode("utf-8")) <= MAX_RESPONSE_BYTES
