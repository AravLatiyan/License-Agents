"""Tests for mission/eval/eval_lib.py (T-042). All TrueForge HTTP calls are
mocked — this suite never touches a real server, same "opt-in only for a
live run" boundary the rest of the project already uses for Mailpit/RDAP/
URLhaus live tests. run_eval.py itself (never pytest) is the opt-in for an
actual 40-fixture run.
"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import call, patch

import pytest

from eval_lib import (
    AGENT_JSON_PATH,
    MAX_TURN_ATTEMPTS,
    RetryableTurnError,
    FIXTURES_DIR,
    FixtureResult,
    TrueForgeError,
    agent_name,
    create_session,
    evaluate_fixture,
    gated_tool_names,
    load_fixtures,
    run_turn_and_observe,
    score,
)

GATED_TOOLS = frozenset(
    {"quarantine", "notify_impersonated", "create_block_rule", "file_abuse_report"}
)


class _FakeResponse:
    """Mimics what `with urllib.request.urlopen(...) as response:` yields -
    a context manager that is also directly iterable (SSE line-by-line) and
    supports .read() (JSON responses)."""

    def __init__(self, lines: list[bytes] | None = None, body: bytes = b""):
        self._lines = lines or []
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return self._body


def _sse_lines(*events: dict) -> list[bytes]:
    lines: list[bytes] = []
    for event in events:
        lines.append(f"data: {json.dumps(event)}\n".encode("utf-8"))
        lines.append(b"\n")
    return lines


def _model_message(event_id: str, tool_name: str, call_id: str) -> dict:
    return {
        "type": "model.message",
        "id": event_id,
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": tool_name, "arguments": "{}"}}
        ],
    }


def _approval_required(refs: list[tuple[str, str]]) -> dict:
    return {
        "type": "tool.approval_required",
        "id": "approval-1",
        "created_at": "2026-08-30T00:00:00Z",
        "thread_id": "thread-1",
        "tool_calls": [{"id": call_id, "source_event_id": source_id} for call_id, source_id in refs],
    }


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


def test_load_fixtures_returns_40_fixtures_with_correct_labels():
    fixtures = load_fixtures(FIXTURES_DIR)

    assert len(fixtures) == 40
    phish = [f for f in fixtures if f.label == "phish"]
    ham = [f for f in fixtures if f.label == "ham"]
    assert len(phish) == 20
    assert len(ham) == 20
    assert all(f.name.endswith(".eml") for f in fixtures)
    assert all(f.raw_email.strip() for f in fixtures)


def test_load_fixtures_is_deterministically_ordered():
    first = [f.name for f in load_fixtures(FIXTURES_DIR)]
    second = [f.name for f in load_fixtures(FIXTURES_DIR)]

    assert first == second


def test_load_fixtures_raises_on_missing_label_directory(tmp_path):
    (tmp_path / "phish").mkdir()
    (tmp_path / "phish" / "a.eml").write_text("From: a@example.com\n\nhi", encoding="utf-8")
    # no ham/ directory at all

    with pytest.raises(FileNotFoundError):
        load_fixtures(tmp_path)


def test_load_fixtures_raises_on_empty_label_directory(tmp_path):
    (tmp_path / "phish").mkdir()
    (tmp_path / "phish" / "a.eml").write_text("From: a@example.com\n\nhi", encoding="utf-8")
    (tmp_path / "ham").mkdir()  # present but empty

    with pytest.raises(FileNotFoundError):
        load_fixtures(tmp_path)


def test_load_fixtures_raises_on_empty_fixture_file(tmp_path):
    for label in ("phish", "ham"):
        (tmp_path / label).mkdir()
    (tmp_path / "phish" / "a.eml").write_text("   ", encoding="utf-8")
    (tmp_path / "ham" / "b.eml").write_text("From: b@example.com\n\nhi", encoding="utf-8")

    with pytest.raises(ValueError):
        load_fixtures(tmp_path)


# ---------------------------------------------------------------------------
# agent.json-derived config
# ---------------------------------------------------------------------------


def test_gated_tool_names_reads_the_real_agent_json():
    assert gated_tool_names(AGENT_JSON_PATH) == GATED_TOOLS


def test_agent_name_reads_the_real_agent_json():
    assert agent_name(AGENT_JSON_PATH) == "universal-imports"


def test_gated_tool_names_raises_if_agent_json_declares_none(tmp_path):
    path = tmp_path / "agent.json"
    path.write_text(
        json.dumps({"manifest": {"mcp_servers": [{"name": "x", "require_approval_for_tools": []}]}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        gated_tool_names(path)


# ---------------------------------------------------------------------------
# Wire-signal extraction (run_turn_and_observe)
# ---------------------------------------------------------------------------


@patch("eval_lib.urllib.request.urlopen")
def test_positive_gated_action_is_detected(mock_urlopen):
    lines = _sse_lines(
        _model_message("msg-1", "quarantine", "call-1"),
        _approval_required([("call-1", "msg-1")]),
    )
    mock_urlopen.return_value = _FakeResponse(lines=lines)

    observation = run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)

    assert observation.gate_fired is True
    assert observation.resolved_gated_tools == ["quarantine"]


@patch("eval_lib.urllib.request.urlopen")
def test_negative_when_turn_completes_with_no_approval_event(mock_urlopen):
    lines = _sse_lines(
        _model_message("msg-1", "domain_intel", "call-1"),  # read-only, never gated
        {"type": "turn.done"},
    )
    mock_urlopen.return_value = _FakeResponse(lines=lines)

    observation = run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)

    assert observation.gate_fired is False
    assert observation.completed_without_gate is True
    assert observation.resolved_gated_tools == []


@patch("eval_lib.urllib.request.urlopen")
def test_read_only_tool_calls_never_count_as_a_positive_signal(mock_urlopen):
    # A model.message calling every read-only tool, still no approval_required
    # at all - mere tool-calling must never be mistaken for a gate firing.
    lines = _sse_lines(
        {
            "type": "model.message",
            "id": "msg-1",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "domain_intel", "arguments": "{}"}},
                {"id": "c2", "type": "function", "function": {"name": "url_reputation", "arguments": "{}"}},
                {"id": "c3", "type": "function", "function": {"name": "correspondence_history", "arguments": "{}"}},
                {"id": "c4", "type": "function", "function": {"name": "detonate", "arguments": "{}"}},
            ],
        },
        {"type": "mission.complete"},
    )
    mock_urlopen.return_value = _FakeResponse(lines=lines)

    observation = run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)

    assert observation.gate_fired is False


@patch("eval_lib.urllib.request.urlopen")
def test_multiple_tool_calls_in_one_approval_event_are_all_resolved(mock_urlopen):
    lines = _sse_lines(
        _model_message("msg-1", "quarantine", "call-1"),
        _model_message("msg-2", "notify_impersonated", "call-2"),
        _approval_required([("call-1", "msg-1"), ("call-2", "msg-2")]),
    )
    mock_urlopen.return_value = _FakeResponse(lines=lines)

    observation = run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)

    assert observation.gate_fired is True
    assert sorted(observation.resolved_gated_tools) == ["notify_impersonated", "quarantine"]


@patch("eval_lib.urllib.request.urlopen")
def test_unresolved_reference_still_counts_as_gate_fired(mock_urlopen):
    # source_event_id points at a model.message this stream never actually
    # carried (e.g. it arrived before this harness started reading, or a
    # reordering bug) - the approval_required event itself is still proof
    # a gated tool was proposed, even though the name can't be recovered.
    lines = _sse_lines(_approval_required([("call-1", "msg-that-never-arrived")]))
    mock_urlopen.return_value = _FakeResponse(lines=lines)

    observation = run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)

    assert observation.gate_fired is True
    assert observation.resolved_gated_tools == []


@patch("eval_lib.urllib.request.urlopen")
def test_malformed_sse_data_line_is_skipped_not_fatal(mock_urlopen):
    lines = [
        b"data: {not valid json at all\n",
        b"\n",
        b": this is an SSE comment, not a data line\n",
        *_sse_lines(
            _model_message("msg-1", "quarantine", "call-1"),
            _approval_required([("call-1", "msg-1")]),
        ),
    ]
    mock_urlopen.return_value = _FakeResponse(lines=lines)

    observation = run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)

    assert observation.gate_fired is True
    assert observation.resolved_gated_tools == ["quarantine"]


@patch("eval_lib.urllib.request.urlopen")
def test_turn_submission_http_error_raises_trueforge_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.HTTPError(
        "url", 422, "provider not configured", hdrs=None, fp=None  # type: ignore[arg-type]
    )

    with pytest.raises(TrueForgeError, match="422"):
        run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)


@patch("eval_lib.urllib.request.urlopen")
def test_turn_submission_timeout_raises_trueforge_error_not_escapes(mock_urlopen):
    # A raw TimeoutError (e.g. the connect itself times out) is not a
    # subclass of URLError/HTTPError - must still be wrapped, never allowed
    # to escape uncaught (Qodo, PR #76, "Stream timeouts abort evaluation").
    mock_urlopen.side_effect = TimeoutError("timed out")

    with pytest.raises(TrueForgeError, match="timed out"):
        run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)


@patch("eval_lib.urllib.request.urlopen")
def test_turn_submission_connection_error_raises_trueforge_error(mock_urlopen):
    mock_urlopen.side_effect = ConnectionResetError("connection reset by peer")

    with pytest.raises(TrueForgeError, match="reset"):
        run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)


class _TimeoutMidStreamResponse(_FakeResponse):
    """A response that starts iterating normally, then raises TimeoutError
    partway through - simulating a slow/stalled SSE read after the initial
    connection succeeded (the class of failure HTTPError/URLError alone
    never catches, since urlopen() itself already returned)."""

    def __iter__(self):
        def _lines():
            yield from self._lines
            raise TimeoutError("read timed out mid-stream")

        return _lines()


@patch("eval_lib.urllib.request.urlopen")
def test_timeout_while_iterating_an_open_stream_raises_trueforge_error(mock_urlopen):
    lines = _sse_lines(_model_message("msg-1", "quarantine", "call-1"))  # no terminal event yet
    mock_urlopen.return_value = _TimeoutMidStreamResponse(lines=lines)

    with pytest.raises(TrueForgeError, match="timed out"):
        run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)


@patch("eval_lib.urllib.request.urlopen")
def test_stream_ending_without_a_terminal_event_raises_trueforge_error(mock_urlopen):
    # EOF with only a model.message seen - no tool.approval_required, no
    # turn.done/mission.complete. Must be a failure, not a "negative"
    # (Qodo, PR #76, "Truncated streams become negatives").
    lines = _sse_lines(_model_message("msg-1", "domain_intel", "call-1"))
    mock_urlopen.return_value = _FakeResponse(lines=lines)

    with pytest.raises(TrueForgeError, match="ended without"):
        run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)


@patch("eval_lib.urllib.request.urlopen")
def test_completely_empty_stream_raises_trueforge_error(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(lines=[])

    with pytest.raises(TrueForgeError, match="ended without"):
        run_turn_and_observe("sess-1", "raw email", GATED_TOOLS)


# ---------------------------------------------------------------------------
# turn.done carrying a failure status
#
# Regression for the first live fixture (2026-08-30, sample-1.eml): a real
# turn.done arrived with {"status": "error", "message": "Cannot connect to
# API: "} after a subagent's model call failed mid-turn, and the harness
# scored it predicted_positive=False / error=None - a false negative on a
# ground-truth phishing fixture, silently counted in the denominator.
# ---------------------------------------------------------------------------


# The event exactly as the live server sent it, byte for byte.
_LIVE_ERRORED_TURN_DONE = {
    "type": "turn.done",
    "id": "01m19gqb1x0000000000000000",
    "state": {
        "status": "error",
        "message": "Cannot connect to API: ",
        "completed_at": "2026-08-30T14:21:09.133Z",
        "metrics": {
            "total_input_tokens": 70086,
            "total_output_tokens": 5723,
            "total_tokens": 75809,
        },
    },
    "created_at": "2026-08-30T14:21:09.133Z",
    "thread_id": None,
}


@patch("eval_lib.urllib.request.urlopen")
def test_errored_turn_done_raises_instead_of_scoring_a_negative(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE))

    with pytest.raises(TrueForgeError, match="finished with status 'error'"):
        run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)


@patch("eval_lib.urllib.request.urlopen")
def test_errored_turn_done_surfaces_the_servers_own_message(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE))

    with pytest.raises(TrueForgeError) as excinfo:
        run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)

    assert "Cannot connect to API" in str(excinfo.value)


@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_a_phish_whose_turn_errors_is_a_failure_not_a_false_negative(
    mock_urlopen, mock_write, mock_delete
):
    """The whole point of the fix: this fixture must not land in the metrics
    as `predicted_positive is False` on a phishing label."""
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [
        _FakeResponse(body=json.dumps({"data": {"id": "sess-1"}}).encode("utf-8")),
        _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE)),
    ]

    result = evaluate_fixture(
        _fixture(name="sample-1.eml", label="phish"),
        agent="universal-imports",
        gated_tools=GATED_TOOLS,
        # Retries are covered separately; this test is about the scoring
        # semantics of a failed turn, so it buys exactly one attempt.
        max_attempts=1,
    )

    assert result.predicted_positive is None, "an errored turn must never be a negative"
    assert result.error is not None and "Cannot connect to API" in result.error

    report = score([result])
    assert report.failed == [result]
    assert report.total_scored == 0
    assert report.false_negatives == 0
    assert report.gate_trigger_accuracy is None


@patch("eval_lib.urllib.request.urlopen")
def test_cancelled_turn_done_is_also_a_failure(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines(
            {"type": "turn.done", "state": {"status": "cancelled", "reason": "user_cancelled"}}
        )
    )

    with pytest.raises(TrueForgeError, match="user_cancelled"):
        run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)


@patch("eval_lib.urllib.request.urlopen")
def test_successful_turn_done_still_scores_as_a_clean_negative(mock_urlopen):
    """The fix must not turn a genuine 'agent declined to act' into a
    failure - that is the measurement this harness exists to make."""
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines({"type": "turn.done", "state": {"status": "done"}})
    )

    observation = run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)

    assert observation.gate_fired is False
    assert observation.completed_without_gate is True
    assert observation.terminal_status == "done"


@patch("eval_lib.urllib.request.urlopen")
def test_a_stateless_turn_finished_event_is_still_a_clean_negative(mock_urlopen):
    """mission.complete (this project's Layer 2 event) carries no state at
    all; a missing status must stay readable, not become a failure."""
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines({"type": "mission.complete"})
    )

    observation = run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)

    assert observation.completed_without_gate is True
    assert observation.terminal_status is None


@patch("eval_lib.urllib.request.urlopen")
def test_a_gate_that_fires_before_an_errored_turn_done_still_counts(mock_urlopen):
    """The gate is the answer the instant it fires - a turn that errors
    afterwards cannot retract a licence request the operator already saw."""
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines(
            _model_message("msg-1", "quarantine", "call-1"),
            _approval_required([("call-1", "msg-1")]),
            _LIVE_ERRORED_TURN_DONE,
        )
    )

    observation = run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)

    assert observation.gate_fired is True
    assert observation.resolved_gated_tools == ["quarantine"]


# ---------------------------------------------------------------------------
# Bounded retry for transient model-transport failures
#
# TrueForge hardcodes maxRetries: 0 (VercelAILLM.ts:939), so a connect-layer
# blip the Vercel AI SDK itself stamps `isRetryable: true` still kills the
# whole turn. Every attempt below is a real billed turn in production, so
# these tests pin exactly which failures earn one and which never do.
# ---------------------------------------------------------------------------


def _errored_turn(message):
    return {"type": "turn.done", "state": {"status": "error", "message": message}}


def _session_ok():
    return _FakeResponse(body=json.dumps({"data": {"id": "sess-1"}}).encode("utf-8"))


@patch("eval_lib.urllib.request.urlopen")
def test_a_retryable_transport_failure_raises_the_retryable_subclass(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE))

    with pytest.raises(RetryableTurnError):
        run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)


@patch("eval_lib.urllib.request.urlopen")
def test_a_provider_error_is_not_the_retryable_subclass(mock_urlopen):
    """Still a failure - just never worth paying for a second attempt."""
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines(_errored_turn("model produced an invalid tool call"))
    )

    with pytest.raises(TrueForgeError) as excinfo:
        run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)

    assert not isinstance(excinfo.value, RetryableTurnError)


@pytest.mark.parametrize(
    "message",
    [
        "authentication_error: invalid x-api-key",
        "rate_limit_error: number of requests has exceeded your rate limit",
        "invalid_request_error: max_tokens must be greater than 0",
        "overloaded_error",
    ],
)
@patch("eval_lib.urllib.request.urlopen")
def test_auth_rate_limit_and_invalid_request_are_never_retryable(mock_urlopen, message):
    mock_urlopen.return_value = _FakeResponse(lines=_sse_lines(_errored_turn(message)))

    with pytest.raises(TrueForgeError) as excinfo:
        run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)

    assert not isinstance(excinfo.value, RetryableTurnError)


@patch("eval_lib.urllib.request.urlopen")
def test_a_cancelled_turn_is_never_retryable(mock_urlopen):
    """Somebody stopped it on purpose; re-spending to override that is wrong."""
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines(
            {"type": "turn.done", "state": {"status": "cancelled", "reason": "user_cancelled"}}
        )
    )

    with pytest.raises(TrueForgeError) as excinfo:
        run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)

    assert not isinstance(excinfo.value, RetryableTurnError)


@patch("eval_lib.time.sleep")
@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_one_transient_failure_then_success_scores_normally(
    mock_urlopen, mock_write, mock_delete, mock_sleep
):
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [
        _session_ok(),
        _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE)),   # attempt 1: blip
        _session_ok(),
        _FakeResponse(                                              # attempt 2: gate fires
            lines=_sse_lines(
                _model_message("msg-1", "quarantine", "call-1"),
                _approval_required([("call-1", "msg-1")]),
            )
        ),
    ]

    result = evaluate_fixture(
        _fixture(name="sample-1.eml", label="phish"),
        agent="universal-imports",
        gated_tools=GATED_TOOLS,
    )

    assert result.predicted_positive is True
    assert result.error is None
    assert result.attempts == 2
    assert result.resolved_gated_tools == ["quarantine"], "no duplicate gate events across retries"

    report = score([result])
    assert report.true_positives == 1
    assert report.total_scored == 1
    assert report.failed == []


@patch("eval_lib.time.sleep")
@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_repeated_transient_failures_eventually_fail_the_fixture(
    mock_urlopen, mock_write, mock_delete, mock_sleep
):
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [
        _session_ok(), _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE)),
        _session_ok(), _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE)),
        _session_ok(), _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE)),
    ]

    result = evaluate_fixture(
        _fixture(name="sample-1.eml", label="phish"),
        agent="universal-imports",
        gated_tools=GATED_TOOLS,
    )

    assert result.predicted_positive is None, "an exhausted retry is still never a negative"
    assert result.attempts == 3
    assert "gave up after 3 attempts" in result.error

    report = score([result])
    assert report.failed == [result]
    assert report.total_scored == 0
    assert report.false_negatives == 0


@patch("eval_lib.time.sleep")
@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_the_retry_budget_is_bounded(mock_urlopen, mock_write, mock_delete, mock_sleep):
    """No unbounded loop: exactly MAX_TURN_ATTEMPTS turns, no more."""
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [
        _session_ok(), _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE)),
    ] * 10

    result = evaluate_fixture(_fixture(), agent="universal-imports", gated_tools=GATED_TOOLS)

    assert result.attempts == MAX_TURN_ATTEMPTS
    # one create_session + one turn per attempt, and nothing beyond the budget
    assert mock_urlopen.call_count == 2 * MAX_TURN_ATTEMPTS


@patch("eval_lib.time.sleep")
@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_a_non_retryable_failure_is_not_retried_at_all(
    mock_urlopen, mock_write, mock_delete, mock_sleep
):
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [
        _session_ok(),
        _FakeResponse(lines=_sse_lines(_errored_turn("authentication_error: invalid x-api-key"))),
    ]

    result = evaluate_fixture(_fixture(), agent="universal-imports", gated_tools=GATED_TOOLS)

    assert result.predicted_positive is None
    assert result.attempts == 1
    assert mock_urlopen.call_count == 2, "an auth failure must never cost a second billed turn"
    assert mock_sleep.call_count == 0


@patch("eval_lib.time.sleep")
@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_a_successful_turn_is_never_retried(mock_urlopen, mock_write, mock_delete, mock_sleep):
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [
        _session_ok(),
        _FakeResponse(lines=_sse_lines({"type": "turn.done", "state": {"status": "done"}})),
    ]

    result = evaluate_fixture(
        _fixture(name="ham-1.eml", label="ham"),
        agent="universal-imports",
        gated_tools=GATED_TOOLS,
    )

    assert result.predicted_positive is False
    assert result.attempts == 1
    assert mock_urlopen.call_count == 2


@patch("eval_lib.time.sleep")
@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_a_gate_that_already_fired_is_never_retracted_by_a_later_failure(
    mock_urlopen, mock_write, mock_delete, mock_sleep
):
    """The operator has already seen the licence request. Reading stops at
    the gate, so the errored turn.done behind it is never even parsed - and
    no second turn is paid for."""
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [
        _session_ok(),
        _FakeResponse(
            lines=_sse_lines(
                _model_message("msg-1", "quarantine", "call-1"),
                _approval_required([("call-1", "msg-1")]),
                _LIVE_ERRORED_TURN_DONE,
            )
        ),
    ]

    result = evaluate_fixture(
        _fixture(name="sample-1.eml", label="phish"),
        agent="universal-imports",
        gated_tools=GATED_TOOLS,
    )

    assert result.predicted_positive is True
    assert result.attempts == 1
    assert result.error is None
    assert mock_urlopen.call_count == 2


@patch("eval_lib.time.sleep")
@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_a_dropped_stream_is_not_retried(mock_urlopen, mock_write, mock_delete, mock_sleep):
    """A truncated stream leaves the turn's outcome unknown and possibly
    still running server-side; re-submitting would double-spend."""
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [_session_ok(), _FakeResponse(lines=[])]

    result = evaluate_fixture(_fixture(), agent="universal-imports", gated_tools=GATED_TOOLS)

    assert result.predicted_positive is None
    assert result.attempts == 1
    assert "ended without" in result.error
    assert mock_urlopen.call_count == 2


@patch("eval_lib.time.sleep")
@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_each_retry_uses_a_fresh_session(mock_urlopen, mock_write, mock_delete, mock_sleep):
    """Event isolation is what makes a retry safe to score: attempt 2 reads
    its own session's stream, so attempt 1's events cannot leak in."""
    mock_write.return_value = "eval-x.eml"
    first = _FakeResponse(body=json.dumps({"data": {"id": "sess-A"}}).encode("utf-8"))
    second = _FakeResponse(body=json.dumps({"data": {"id": "sess-B"}}).encode("utf-8"))
    mock_urlopen.side_effect = [
        first, _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE)),
        second, _FakeResponse(lines=_sse_lines({"type": "turn.done", "state": {"status": "done"}})),
    ]

    evaluate_fixture(_fixture(), agent="universal-imports", gated_tools=GATED_TOOLS)

    turn_urls = [
        c[0][0].full_url for c in mock_urlopen.call_args_list if "/turns" in c[0][0].full_url
    ]
    assert turn_urls == [
        "http://localhost:8790/api/v1/sessions/sess-A/turns",
        "http://localhost:8790/api/v1/sessions/sess-B/turns",
    ]


@patch("eval_lib.time.sleep")
@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_the_temp_fixture_is_written_once_and_deleted_once_across_retries(
    mock_urlopen, mock_write, mock_delete, mock_sleep
):
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [
        _session_ok(), _FakeResponse(lines=_sse_lines(_LIVE_ERRORED_TURN_DONE)),
        _session_ok(),
        _FakeResponse(lines=_sse_lines({"type": "turn.done", "state": {"status": "done"}})),
    ]

    evaluate_fixture(_fixture(), agent="universal-imports", gated_tools=GATED_TOOLS)

    assert mock_write.call_count == 1
    assert mock_delete.call_count == 1


# ---------------------------------------------------------------------------
# Gated-tool name resolution through TrueForge's MCP proxy
#
# Regression for fixture #3 (sample-11.eml, 2026-08-30): three gates fired for
# real - quarantine, create_block_rule, file_abuse_report - and
# resolved_gated_tools came back EMPTY, because TrueForge proxies every MCP
# tool behind function.name == "call_tool" with the real name in the call's
# own JSON-encoded arguments. Scoring was unaffected (gate_fired is the
# correctness boundary) but the run could not report WHICH action the agent
# proposed, on every fixture, permanently.
# ---------------------------------------------------------------------------


def _proxied_call(call_id, tool_name, extra_input=None):
    """A tool call in the shape TrueForge actually emits: the wrapper name at
    function.name, the real tool inside arguments as a JSON *string*."""
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "call_tool",
            "arguments": json.dumps(
                {
                    "mcp_server": "imports-mcp",
                    "tool_name": tool_name,
                    "input": extra_input if extra_input is not None else {},
                }
            ),
        },
    }


def _message_with_calls(event_id, calls):
    return {"type": "model.message", "id": event_id, "tool_calls": calls}


@patch("eval_lib.urllib.request.urlopen")
def test_a_directly_named_gated_tool_still_resolves(mock_urlopen):
    """Unproxied shape must keep working - this is what every earlier test
    in this file exercises, and it is not hypothetical: a non-MCP or
    client-side tool would arrive this way."""
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines(
            _model_message("msg-1", "quarantine", "call-1"),
            _approval_required([("call-1", "msg-1")]),
        )
    )

    observation = run_turn_and_observe("sess-1", "m", GATED_TOOLS)

    assert observation.gate_fired is True
    assert observation.resolved_gated_tools == ["quarantine"]


@patch("eval_lib.urllib.request.urlopen")
def test_a_proxied_call_tool_resolves_to_the_real_gated_name(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines(
            _message_with_calls("msg-1", [_proxied_call("call-1", "quarantine")]),
            _approval_required([("call-1", "msg-1")]),
        )
    )

    observation = run_turn_and_observe("sess-1", "m", GATED_TOOLS)

    assert observation.gate_fired is True
    assert observation.resolved_gated_tools == ["quarantine"]


@patch("eval_lib.urllib.request.urlopen")
def test_a_proxied_non_gated_tool_is_not_reported_as_gated(mock_urlopen):
    """parse_message travels through the same wrapper. Unwrapping must not
    turn a read-only tool into a gated one."""
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines(
            _message_with_calls(
                "msg-1",
                [_proxied_call("call-1", "parse_message", {"fixture": "eval-x.eml"})],
            ),
            _approval_required([("call-1", "msg-1")]),
        )
    )

    observation = run_turn_and_observe("sess-1", "m", GATED_TOOLS)

    # The gate still fired - TrueForge cannot emit that event for an ungated
    # tool, so its occurrence stays the correctness boundary - but nothing is
    # claimed about which gated tool it was.
    assert observation.gate_fired is True
    assert observation.resolved_gated_tools == []


@pytest.mark.parametrize(
    "arguments",
    [
        "not json at all",
        json.dumps({"mcp_server": "imports-mcp"}),          # no tool_name
        json.dumps({"mcp_server": "imports-mcp", "tool_name": ""}),
        json.dumps({"mcp_server": "imports-mcp", "tool_name": "   "}),
        json.dumps({"mcp_server": "imports-mcp", "tool_name": 7}),
        json.dumps(["not", "an", "object"]),
        None,
    ],
)
@patch("eval_lib.urllib.request.urlopen")
def test_malformed_proxy_arguments_resolve_to_nothing_never_a_guess(mock_urlopen, arguments):
    call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "call_tool", "arguments": arguments},
    }
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines(
            _message_with_calls("msg-1", [call]),
            _approval_required([("call-1", "msg-1")]),
        )
    )

    observation = run_turn_and_observe("sess-1", "m", GATED_TOOLS)

    assert observation.gate_fired is True, "an unreadable name never un-fires the gate"
    assert observation.resolved_gated_tools == []
    # Specifically: the wrapper's own name must not leak through as a result.
    assert "call_tool" not in observation.resolved_gated_tools


@patch("eval_lib.urllib.request.urlopen")
def test_three_proxied_gated_calls_in_one_approval_event_all_resolve(mock_urlopen):
    """Replays fixture #3's real event: one tool.approval_required carrying
    three ToolCallRefs that all point at the same model.message."""
    mock_urlopen.return_value = _FakeResponse(
        lines=_sse_lines(
            _message_with_calls(
                "01m19jw6pmpa8nvnqdxk8h7wba",
                [
                    _proxied_call(
                        "toolu_01Bb4AFs2Nj8ghNacVRvRDbs",
                        "quarantine",
                        {"message_ids": ["<c614a2e5@example.invalid>"]},
                    ),
                    _proxied_call(
                        "toolu_01Y7sWz6QE9E57q2uH3XUz9E",
                        "create_block_rule",
                        {"pattern": "*@123gereedschap.nl"},
                    ),
                    _proxied_call(
                        "toolu_01Scjg9pcnW22SQZUFCB9QFq",
                        "file_abuse_report",
                        {"domain": "123gereedschap.nl", "evidence": "..."},
                    ),
                ],
            ),
            _approval_required(
                [
                    ("toolu_01Bb4AFs2Nj8ghNacVRvRDbs", "01m19jw6pmpa8nvnqdxk8h7wba"),
                    ("toolu_01Y7sWz6QE9E57q2uH3XUz9E", "01m19jw6pmpa8nvnqdxk8h7wba"),
                    ("toolu_01Scjg9pcnW22SQZUFCB9QFq", "01m19jw6pmpa8nvnqdxk8h7wba"),
                ]
            ),
        )
    )

    observation = run_turn_and_observe("sess-1", "m", GATED_TOOLS)

    assert observation.gate_fired is True
    assert observation.resolved_gated_tools == [
        "quarantine",
        "create_block_rule",
        "file_abuse_report",
    ]


@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_the_proxy_fix_does_not_change_scoring(mock_urlopen, mock_write, mock_delete):
    """Fixture #3 scored TP with an empty resolved list and must still score
    TP now - the names are diagnostics, never an input to the metric."""
    mock_write.return_value = "eval-x.eml"
    mock_urlopen.side_effect = [
        _FakeResponse(body=json.dumps({"data": {"id": "sess-1"}}).encode("utf-8")),
        _FakeResponse(
            lines=_sse_lines(
                _message_with_calls("msg-1", [_proxied_call("call-1", "quarantine")]),
                _approval_required([("call-1", "msg-1")]),
            )
        ),
    ]

    result = evaluate_fixture(
        _fixture(name="sample-11.eml", label="phish"),
        agent="universal-imports",
        gated_tools=GATED_TOOLS,
    )

    assert result.predicted_positive is True
    assert result.resolved_gated_tools == ["quarantine"]
    report = score([result])
    assert report.true_positives == 1


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_returns_the_session_id(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(body=json.dumps({"data": {"id": "sess-abc"}}).encode("utf-8"))

    session_id = create_session("universal-imports")

    assert session_id == "sess-abc"


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_raises_on_http_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.HTTPError(
        "url", 500, "boom", hdrs=None, fp=None  # type: ignore[arg-type]
    )

    with pytest.raises(TrueForgeError, match="500"):
        create_session("universal-imports")


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_raises_when_response_has_no_data(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(body=json.dumps({"status": "ok"}).encode("utf-8"))

    with pytest.raises(TrueForgeError, match="no data object"):
        create_session("universal-imports")


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_raises_when_data_carries_no_id(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(
        body=json.dumps({"data": {"title": None}}).encode("utf-8")
    )

    with pytest.raises(TrueForgeError, match="no usable id"):
        create_session("universal-imports")


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_raises_when_the_id_is_top_level_only(mock_urlopen):
    """The pre-fix shape. A server that answered like this would mean the
    wire changed again, and that must fail loudly rather than silently."""
    mock_urlopen.return_value = _FakeResponse(body=json.dumps({"id": "sess-abc"}).encode("utf-8"))

    with pytest.raises(TrueForgeError, match="no data object"):
        create_session("universal-imports")


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_raises_on_non_json_response(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(body=b"not json")

    with pytest.raises(TrueForgeError):
        create_session("universal-imports")


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_raises_trueforge_error_on_timeout(mock_urlopen):
    mock_urlopen.side_effect = TimeoutError("timed out")

    with pytest.raises(TrueForgeError, match="timed out"):
        create_session("universal-imports")


# ---------------------------------------------------------------------------
# Request shape - URL and body
#
# Nothing in this suite used to assert either, which is exactly how four
# wrong wire shapes survived until a live instance rejected them (module
# docstring, WIRE SHAPES). These pin all four against regression.
# ---------------------------------------------------------------------------


def _sent_request(mock_urlopen):
    """The urllib.request.Request object passed to the mocked urlopen."""
    return mock_urlopen.call_args[0][0]


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_posts_to_the_api_v1_path(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(
        body=json.dumps({"data": {"id": "sess-abc"}}).encode("utf-8")
    )

    create_session("universal-imports", base_url="http://localhost:8790")

    assert _sent_request(mock_urlopen).full_url == "http://localhost:8790/api/v1/sessions"


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_binds_the_agent_by_nested_name(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(
        body=json.dumps({"data": {"id": "sess-abc"}}).encode("utf-8")
    )

    create_session("universal-imports")

    body = json.loads(_sent_request(mock_urlopen).data.decode("utf-8"))
    assert body == {"agent": {"name": "universal-imports"}}


@patch("eval_lib.urllib.request.urlopen")
def test_run_turn_posts_to_the_api_v1_turns_path(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(lines=_sse_lines({"type": "turn.done"}))

    run_turn_and_observe(
        "sess-1", "look at eval-x.eml", GATED_TOOLS, base_url="http://localhost:8790"
    )

    assert (
        _sent_request(mock_urlopen).full_url
        == "http://localhost:8790/api/v1/sessions/sess-1/turns"
    )


@patch("eval_lib.urllib.request.urlopen")
def test_run_turn_sends_input_as_an_array_of_items(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(lines=_sse_lines({"type": "turn.done"}))

    run_turn_and_observe("sess-1", "look at eval-x.eml", GATED_TOOLS)

    body = json.loads(_sent_request(mock_urlopen).data.decode("utf-8"))
    assert body["input"] == [{"type": "user.message", "content": "look at eval-x.eml"}]
    assert body["stream"] is True


# ---------------------------------------------------------------------------
# evaluate_fixture - execution failure handling, never coerced to negative
# ---------------------------------------------------------------------------


def _fixture(name="f.eml", label="phish", raw="From: a@example.com\n\nhi"):
    from eval_lib import Fixture

    return Fixture(name=name, label=label, raw_email=raw)


@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.create_session")
def test_execution_failure_is_reported_not_coerced_to_negative(
    mock_create_session, mock_write, mock_delete
):
    mock_write.return_value = "eval-abc123.eml"
    mock_create_session.side_effect = TrueForgeError("HTTP 422 from ...: provider not configured")

    result = evaluate_fixture(
        _fixture(label="phish"), agent="universal-imports", gated_tools=GATED_TOOLS
    )

    assert result.predicted_positive is None
    assert result.error is not None
    assert "422" in result.error


@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.run_turn_and_observe")
@patch("eval_lib.create_session")
def test_successful_evaluation_reports_predicted_positive(
    mock_create_session, mock_run_turn, mock_write, mock_delete
):
    from eval_lib import TurnObservation

    mock_write.return_value = "eval-abc123.eml"
    mock_create_session.return_value = "sess-1"
    mock_run_turn.return_value = TurnObservation(gate_fired=True, resolved_gated_tools=["quarantine"])

    result = evaluate_fixture(
        _fixture(label="phish"), agent="universal-imports", gated_tools=GATED_TOOLS
    )

    assert result.predicted_positive is True
    assert result.error is None
    assert result.resolved_gated_tools == ["quarantine"]


@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.run_turn_and_observe")
@patch("eval_lib.create_session")
def test_evaluate_fixture_writes_the_raw_email_and_references_it_in_the_turn_message(
    mock_create_session, mock_run_turn, mock_write, mock_delete
):
    from eval_lib import TurnObservation

    mock_write.return_value = "eval-abc123.eml"
    mock_create_session.return_value = "sess-1"
    mock_run_turn.return_value = TurnObservation(gate_fired=False)

    evaluate_fixture(
        _fixture(label="ham", raw="From: b@example.com\n\nham body"),
        agent="universal-imports",
        gated_tools=GATED_TOOLS,
    )

    mock_write.assert_called_once_with("From: b@example.com\n\nham body")
    turn_message = mock_run_turn.call_args[0][1]
    assert "eval-abc123.eml" in turn_message


@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.create_session")
def test_evaluate_fixture_deletes_the_temp_fixture_even_when_the_turn_fails(
    mock_create_session, mock_write, mock_delete
):
    mock_write.return_value = "eval-abc123.eml"
    mock_create_session.side_effect = TrueForgeError("boom")

    evaluate_fixture(_fixture(label="phish"), agent="universal-imports", gated_tools=GATED_TOOLS)

    mock_delete.assert_called_once_with("eval-abc123.eml")


@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.run_turn_and_observe")
@patch("eval_lib.create_session")
@patch("eval_lib.write_temp_fixture")
def test_evaluate_fixture_survives_a_cleanup_failure_and_keeps_the_observation(
    mock_write, mock_create_session, mock_run_turn, mock_delete
):
    """A failed unlink must never abort the run (Qodo, PR #76, finding 4).

    The turn already succeeded here: its observation is the expensive part
    and is not thrown away because a temp file could not be removed. The
    failure is reported on the result instead, because the leftover file
    sits in tools/fixtures/ and somebody has to know to remove it.
    """
    from eval_lib import TurnObservation

    mock_write.return_value = "eval-abc123.eml"
    mock_create_session.return_value = "sess-1"
    mock_run_turn.return_value = TurnObservation(gate_fired=True, resolved_gated_tools=["quarantine"])
    mock_delete.side_effect = OSError("file is locked")

    result = evaluate_fixture(
        _fixture(label="phish"), agent="universal-imports", gated_tools=GATED_TOOLS
    )

    assert result.predicted_positive is True
    assert result.resolved_gated_tools == ["quarantine"]
    assert result.error is not None
    assert "eval-abc123.eml" in result.error


@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.create_session")
@patch("eval_lib.write_temp_fixture")
def test_evaluate_fixture_cleanup_failure_does_not_hide_the_turn_failure(
    mock_write, mock_create_session, mock_delete
):
    """Both things went wrong: the caller needs to see the turn error, which
    is the one that explains predicted_positive being None."""
    mock_write.return_value = "eval-abc123.eml"
    mock_create_session.side_effect = TrueForgeError("boom")
    mock_delete.side_effect = OSError("file is locked")

    result = evaluate_fixture(
        _fixture(label="phish"), agent="universal-imports", gated_tools=GATED_TOOLS
    )

    assert result.predicted_positive is None
    assert "boom" in result.error
    assert "eval-abc123.eml" in result.error


# ---------------------------------------------------------------------------
# Fixture delivery via tools/fixtures/ - write_temp_fixture, delete_temp_fixture
# ---------------------------------------------------------------------------


def test_write_temp_fixture_creates_a_readable_file_and_returns_its_name(tmp_path):
    from eval_lib import write_temp_fixture

    name = write_temp_fixture("From: a@example.com\n\nhi", fixtures_dir=tmp_path)

    assert name.endswith(".eml")
    assert (tmp_path / name).read_text(encoding="utf-8") == "From: a@example.com\n\nhi"


def test_write_temp_fixture_names_are_unique_across_calls(tmp_path):
    from eval_lib import write_temp_fixture

    first = write_temp_fixture("a", fixtures_dir=tmp_path)
    second = write_temp_fixture("b", fixtures_dir=tmp_path)

    assert first != second


def test_delete_temp_fixture_removes_the_file(tmp_path):
    from eval_lib import delete_temp_fixture, write_temp_fixture

    name = write_temp_fixture("hi", fixtures_dir=tmp_path)
    assert (tmp_path / name).exists()

    delete_temp_fixture(name, fixtures_dir=tmp_path)

    assert not (tmp_path / name).exists()


def test_delete_temp_fixture_is_safe_if_the_file_is_already_gone(tmp_path):
    from eval_lib import delete_temp_fixture

    delete_temp_fixture("never-existed.eml", fixtures_dir=tmp_path)  # must not raise


def test_fixture_turn_message_names_the_exact_filename():
    from eval_lib import fixture_turn_message

    message = fixture_turn_message("eval-abc123.eml")

    assert "eval-abc123.eml" in message
    assert "parse_message" in message


# ---------------------------------------------------------------------------
# Event isolation between fixtures
# ---------------------------------------------------------------------------


@patch("eval_lib.delete_temp_fixture")
@patch("eval_lib.write_temp_fixture")
@patch("eval_lib.urllib.request.urlopen")
def test_one_fixtures_events_cannot_contaminate_anothers_result(
    mock_urlopen, mock_write, mock_delete
):
    mock_write.side_effect = ["eval-first.eml", "eval-second.eml"]
    positive_lines = _sse_lines(
        _model_message("msg-1", "quarantine", "call-1"),
        _approval_required([("call-1", "msg-1")]),
    )
    negative_lines = _sse_lines({"type": "turn.done"})
    session_response = _FakeResponse(body=json.dumps({"data": {"id": "sess-x"}}).encode("utf-8"))

    # First fixture: session creation, then a positive turn.
    # Second fixture: a fresh session creation, then a negative turn - a
    # fresh correlation dict inside run_turn_and_observe means the first
    # fixture's "msg-1"/"call-1" ids cannot leak into this one, even though
    # the ids are reused.
    mock_urlopen.side_effect = [
        session_response,
        _FakeResponse(lines=positive_lines),
        session_response,
        _FakeResponse(lines=negative_lines),
    ]

    first = evaluate_fixture(
        _fixture(name="phish-1.eml", label="phish"),
        agent="universal-imports",
        gated_tools=GATED_TOOLS,
    )
    second = evaluate_fixture(
        _fixture(name="ham-1.eml", label="ham"), agent="universal-imports", gated_tools=GATED_TOOLS
    )

    assert first.predicted_positive is True
    assert second.predicted_positive is False
    assert mock_urlopen.call_count == 4  # two sessions, two turns - never reused
    assert mock_delete.call_args_list == [call("eval-first.eml"), call("eval-second.eml")]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _result(label, predicted_positive, error=None):
    return FixtureResult(fixture_name="x", label=label, predicted_positive=predicted_positive, error=error)


def test_score_computes_accuracy_and_false_positive_rate():
    results = [
        _result("phish", True),  # TP
        _result("phish", True),  # TP
        _result("phish", False),  # FN
        _result("ham", False),  # TN
        _result("ham", False),  # TN
        _result("ham", True),  # FP
    ]

    report = score(results)

    assert report.true_positives == 2
    assert report.false_negatives == 1
    assert report.true_negatives == 2
    assert report.false_positives == 1
    assert report.total_scored == 6
    assert report.gate_trigger_accuracy == pytest.approx(4 / 6)
    assert report.false_positive_rate == pytest.approx(1 / 3)


def test_score_excludes_failed_fixtures_from_metrics():
    results = [
        _result("phish", True),
        _result("ham", False),
        _result("phish", None, error="timed out"),
        _result("ham", None, error="HTTP 422"),
    ]

    report = score(results)

    assert report.total_fixtures == 4
    assert report.total_scored == 2
    assert len(report.failed) == 2
    assert report.gate_trigger_accuracy == 1.0
    assert report.false_positive_rate == 0.0


def test_score_handles_zero_ham_scored_without_division_by_zero():
    results = [_result("phish", True), _result("phish", False)]

    report = score(results)

    assert report.false_positive_rate is None
    assert report.gate_trigger_accuracy == pytest.approx(0.5)


def test_score_handles_empty_results_without_crashing():
    report = score([])

    assert report.gate_trigger_accuracy is None
    assert report.false_positive_rate is None
    assert report.total_scored == 0
    assert report.failed == []
