"""Unit tests for quarantine (T-030) — Mailpit HTTP API mocked, deterministic.

Nothing here opens a real connection. `requests.get`/`requests.put` are
patched in every test that reaches the tag path, so the normal suite never
depends on a running Mailpit (an opt-in live test, if one gets added later,
would live in test_server_integration_live.py, matching
notify_impersonated/file_abuse_report's own pattern).

quarantine() does one GET (read current tags) + PUT (set tags, unioned with
"Quarantined") per message, not one batched PUT for the whole list — Qodo
caught the batched version silently erasing every message's existing tags,
since Mailpit's PUT /api/v1/tags *overwrites* rather than appending
(PR #67 finding #1). Every test below reflects that shape.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
import requests

from imports_mcp.quarantine import MAX_RESPONSE_BYTES, QUARANTINE_TAG, quarantine

MESSAGE_IDS = ["4oRBnPtCXgAqZniRhzLNmS", "hXayS6wnCgNnt6aFTvmOF6"]


@pytest.fixture(autouse=True)
def _clear_mailpit_env(monkeypatch):
    """MAILPIT_HTTP_BASE_URL may be set in a developer's .env. Clear it so
    every test measures the *code's* default, not the machine's."""
    monkeypatch.delenv("MAILPIT_HTTP_BASE_URL", raising=False)


def _mock_get_response(tags: list[str] | None = None) -> Mock:
    """A GET /api/v1/message/{ID} response - only the Tags field matters
    here, everything else about a real Message summary is irrelevant to
    this tool."""
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"Tags": tags if tags is not None else []}
    resp.raise_for_status.return_value = None
    return resp


def _mock_put_response(status_code: int = 200, text: str = "ok") -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = {}
    return resp


def _mock_ok(mock_get, mock_put, existing_tags: list[str] | None = None) -> None:
    mock_get.return_value = _mock_get_response(existing_tags)
    mock_put.return_value = _mock_put_response(200)


# --- the safety property: where does this tool talk to by default? ---------


def test_default_target_is_the_range_never_a_real_server():
    """With no MAILPIT_HTTP_BASE_URL configured, this tool must only ever
    reach the local T-060 Mailpit range (range/docker-compose.yml publishes
    8025:8025). If someone later changes this default to a real server,
    this test is the tripwire."""
    import imports_mcp.quarantine as quarantine_module

    assert quarantine_module._mailpit_base_url() == "http://localhost:8025"


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_requests_target_the_range_by_default(mock_get, mock_put):
    _mock_ok(mock_get, mock_put)

    quarantine(MESSAGE_IDS[:1])

    assert mock_get.call_args[0][0] == f"http://localhost:8025/api/v1/message/{MESSAGE_IDS[0]}"
    assert mock_put.call_args[0][0] == "http://localhost:8025/api/v1/tags"


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_env_var_overrides_the_base_url(mock_get, mock_put, monkeypatch):
    _mock_ok(mock_get, mock_put)
    monkeypatch.setenv("MAILPIT_HTTP_BASE_URL", "http://mailpit.internal:9025")

    quarantine(MESSAGE_IDS[:1])

    assert mock_get.call_args[0][0].startswith("http://mailpit.internal:9025")
    assert mock_put.call_args[0][0] == "http://mailpit.internal:9025/api/v1/tags"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_blank_env_var_falls_back_to_the_range(mock_get, mock_put, monkeypatch, blank):
    """Same class of bug Qodo caught on notify_impersonated (PR #29 finding
    #1): a set-but-empty env var (what `.env.example`'s `KEY=` loads as via
    python-dotenv) must not silently become an empty/invalid base URL."""
    _mock_ok(mock_get, mock_put)
    monkeypatch.setenv("MAILPIT_HTTP_BASE_URL", blank)

    quarantine(MESSAGE_IDS[:1])

    assert mock_put.call_args[0][0] == "http://localhost:8025/api/v1/tags"


# --- existing tags are preserved, not overwritten (Qodo, PR #67 finding #1) -


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_existing_tags_are_kept_and_quarantined_is_added(mock_get, mock_put):
    _mock_ok(mock_get, mock_put, existing_tags=["VIP", "Newsletter"])

    quarantine(MESSAGE_IDS[:1])

    body = mock_put.call_args.kwargs["json"]
    assert set(body["Tags"]) == {"VIP", "Newsletter", QUARANTINE_TAG}
    assert body["IDs"] == [MESSAGE_IDS[0]]


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_already_quarantined_message_is_not_double_tagged(mock_get, mock_put):
    _mock_ok(mock_get, mock_put, existing_tags=[QUARANTINE_TAG])

    quarantine(MESSAGE_IDS[:1])

    body = mock_put.call_args.kwargs["json"]
    assert body["Tags"] == [QUARANTINE_TAG]


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_each_message_gets_its_own_put_with_its_own_tag_set(mock_get, mock_put):
    """Two messages with different existing tags must each get their own
    correctly-unioned Tags array - a single shared PUT for both would force
    one message's tags onto the other."""
    responses = {
        MESSAGE_IDS[0]: ["VIP"],
        MESSAGE_IDS[1]: ["Newsletter"],
    }
    mock_get.side_effect = lambda url, timeout: _mock_get_response(responses[url.rsplit("/", 1)[-1]])
    mock_put.return_value = _mock_put_response(200)

    quarantine(MESSAGE_IDS)

    assert mock_put.call_count == 2
    put_bodies = {call.kwargs["json"]["IDs"][0]: call.kwargs["json"]["Tags"] for call in mock_put.call_args_list}
    assert set(put_bodies[MESSAGE_IDS[0]]) == {"VIP", QUARANTINE_TAG}
    assert set(put_bodies[MESSAGE_IDS[1]]) == {"Newsletter", QUARANTINE_TAG}


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_never_calls_delete(mock_get, mock_put):
    """Design property, not incidental: quarantine tags, it never deletes.
    Mailpit's DELETE /api/v1/messages destroys the message outright and, if
    IDs were ever empty, deletes the *entire* mailbox — this tool must never
    reach for that endpoint at all, gated action or not."""
    _mock_ok(mock_get, mock_put)

    with patch("imports_mcp.quarantine.requests.delete") as mock_delete:
        quarantine(MESSAGE_IDS)
        mock_delete.assert_not_called()


# --- the happy path ----------------------------------------------------------


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_successful_tag_returns_structured_result(mock_get, mock_put):
    _mock_ok(mock_get, mock_put)

    result = quarantine(MESSAGE_IDS)

    assert result["quarantined"] is True
    assert result["message_ids"] == MESSAGE_IDS
    assert result["tag"] == QUARANTINE_TAG
    assert result["truncated"] is False


# --- degradation, not exceptions ---------------------------------------------


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_put_failure_degrades_instead_of_raising(mock_get, mock_put):
    mock_get.return_value = _mock_get_response([])
    mock_put.return_value = _mock_put_response(400, text="bad request")

    result = quarantine(MESSAGE_IDS[:1])

    assert result["quarantined"] is False
    assert "400" in result["note"]


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_get_failure_degrades_instead_of_raising(mock_get, mock_put):
    """A failure reading current tags must not raise, and must not fall
    through to a PUT with an incomplete tag list - the whole message is
    reported as a failure instead."""
    mock_get.side_effect = requests.exceptions.ConnectionError("connection refused")

    result = quarantine(MESSAGE_IDS[:1])

    assert result["quarantined"] is False
    assert "connection refused" in result["note"]
    mock_put.assert_not_called()


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_put_connection_failure_degrades_instead_of_raising(mock_get, mock_put):
    mock_get.return_value = _mock_get_response([])
    mock_put.side_effect = requests.exceptions.ConnectionError("connection refused")

    result = quarantine(MESSAGE_IDS[:1])

    assert result["quarantined"] is False
    assert "connection refused" in result["note"]


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_timeout_degrades_instead_of_raising(mock_get, mock_put):
    mock_get.return_value = _mock_get_response([])
    mock_put.side_effect = requests.exceptions.Timeout("timed out")

    result = quarantine(MESSAGE_IDS[:1])

    assert result["quarantined"] is False
    assert "timed out" in result["note"]


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_partial_failure_is_reported_as_not_quarantined(mock_get, mock_put):
    """One message failing must not make the whole call report success -
    quarantined is only True once every requested message was tagged."""

    def get_side_effect(url, timeout):
        if url.endswith(MESSAGE_IDS[0]):
            return _mock_get_response([])
        raise requests.exceptions.ConnectionError("connection refused")

    mock_get.side_effect = get_side_effect
    mock_put.return_value = _mock_put_response(200)

    result = quarantine(MESSAGE_IDS)

    assert result["quarantined"] is False
    assert MESSAGE_IDS[1] in result["note"]


# --- raw HTML never enters the tool result (Qodo, PR #67 finding #3) --------


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_html_error_body_is_reduced_to_text_not_returned_raw(mock_get, mock_put):
    mock_get.return_value = _mock_get_response([])
    resp = _mock_put_response(502, text="<html><body><h1>Bad Gateway</h1></body></html>")
    resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_put.return_value = resp

    result = quarantine(MESSAGE_IDS[:1])

    assert "<html>" not in result["note"]
    assert "<h1>" not in result["note"]
    assert "Bad Gateway" in result["note"]


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_plain_text_error_body_is_unaffected(mock_get, mock_put):
    mock_get.return_value = _mock_get_response([])
    resp = _mock_put_response(400, text="bad request")
    resp.headers = {"content-type": "text/plain"}
    mock_put.return_value = resp

    result = quarantine(MESSAGE_IDS[:1])

    assert "bad request" in result["note"]


# --- response-size cap (Rule 2880706) ----------------------------------------


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_normal_response_is_not_truncated(mock_get, mock_put):
    _mock_ok(mock_get, mock_put)

    result = quarantine(MESSAGE_IDS)

    assert result["truncated"] is False
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_oversized_message_id_list_is_truncated_and_flagged(mock_get, mock_put):
    _mock_ok(mock_get, mock_put)
    huge_ids = [f"msg-{i:04d}" for i in range(300)]

    result = quarantine(huge_ids)

    assert result["truncated"] is True
    assert len(result["message_ids"]) < len(huge_ids)
    assert result["omitted"]["message_ids"] == len(huge_ids) - len(result["message_ids"])
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES
    # A structured field a caller branches on survives truncation.
    assert result["quarantined"] is True


@patch("imports_mcp.quarantine.requests.put")
@patch("imports_mcp.quarantine.requests.get")
def test_oversized_failure_note_is_truncated_and_flagged(mock_get, mock_put):
    mock_get.return_value = _mock_get_response([])
    resp = _mock_put_response(500, text="x" * 10_000)
    resp.headers = {"content-type": "text/plain"}
    mock_put.return_value = resp

    result = quarantine(MESSAGE_IDS[:1])

    assert result["truncated"] is True
    assert result["quarantined"] is False
    assert len(json.dumps(result).encode("utf-8")) <= MAX_RESPONSE_BYTES
