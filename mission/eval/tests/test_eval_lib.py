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
# create_session
# ---------------------------------------------------------------------------


@patch("eval_lib.urllib.request.urlopen")
def test_create_session_returns_the_session_id(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(body=json.dumps({"id": "sess-abc"}).encode("utf-8"))

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
def test_create_session_raises_when_response_has_no_id(mock_urlopen):
    mock_urlopen.return_value = _FakeResponse(body=json.dumps({"status": "ok"}).encode("utf-8"))

    with pytest.raises(TrueForgeError):
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
    session_response = _FakeResponse(body=json.dumps({"id": "sess-x"}).encode("utf-8"))

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
