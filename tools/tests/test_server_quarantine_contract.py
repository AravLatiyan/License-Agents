"""Contract tests for the quarantine tool wiring (T-030).

Tag/degradation behaviour is covered end to end in test_quarantine.py with
requests.put mocked — these only check that server.py's tool wrapper
validates its input and delegates correctly.

Validation matters here for the same reason it does for
notify_impersonated: this is one of the four gated actions (T-034), acting
on model-generated arguments. In particular, an empty or all-blank
message_ids must never reach the underlying tool at all - Mailpit's
DELETE /api/v1/messages (a different endpoint this tool never calls, but
the same "empty IDs" shape) deletes the entire mailbox when IDs is empty,
so this boundary is the one place that footgun gets closed off for good.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.server import MAX_QUARANTINE_MESSAGE_IDS, quarantine

VALID_IDS = ["4oRBnPtCXgAqZniRhzLNmS", "hXayS6wnCgNnt6aFTvmOF6"]


def test_empty_list_is_rejected():
    with pytest.raises(ToolError):
        quarantine([])


@patch("imports_mcp.server._quarantine")
def test_batch_over_the_max_is_rejected_before_any_mailpit_call(mock_quarantine):
    """Qodo, PR #67 finding #4: quarantine() now does one GET+PUT pair per
    message, so an unbounded list means an unbounded number of live
    round-trips, not just a large request body."""
    with pytest.raises(ToolError):
        quarantine([f"msg-{i}" for i in range(MAX_QUARANTINE_MESSAGE_IDS + 1)])
    mock_quarantine.assert_not_called()


@patch("imports_mcp.server._quarantine")
def test_batch_at_exactly_the_max_is_accepted(mock_quarantine):
    mock_quarantine.return_value = {"quarantined": True}
    ids = [f"msg-{i}" for i in range(MAX_QUARANTINE_MESSAGE_IDS)]

    quarantine(ids)

    mock_quarantine.assert_called_once_with(ids)


def test_non_list_is_rejected():
    with pytest.raises(ToolError):
        quarantine("4oRBnPtCXgAqZniRhzLNmS")  # a bare string, not a list of one


@pytest.mark.parametrize(
    "bad_ids",
    [
        [""],
        ["   "],
        [None],
        [123],
        ["4oRBnPtCXgAqZniRhzLNmS", ""],
        ["4oRBnPtCXgAqZniRhzLNmS", "   "],
    ],
)
@patch("imports_mcp.server._quarantine")
def test_any_blank_or_non_string_id_is_rejected_before_any_mailpit_call(mock_quarantine, bad_ids):
    """A caller-supplied blank/None/number in the list must not be silently
    dropped and the rest sent through - that would quarantine fewer
    messages than asked, with no signal anything was skipped."""
    with pytest.raises(ToolError):
        quarantine(bad_ids)
    mock_quarantine.assert_not_called()


@patch("imports_mcp.server._quarantine")
def test_valid_ids_delegate_with_stripped_values(mock_quarantine):
    mock_quarantine.return_value = {"quarantined": True}

    quarantine(["  4oRBnPtCXgAqZniRhzLNmS  ", "hXayS6wnCgNnt6aFTvmOF6"])

    mock_quarantine.assert_called_once_with(["4oRBnPtCXgAqZniRhzLNmS", "hXayS6wnCgNnt6aFTvmOF6"])


@patch("imports_mcp.server._quarantine")
def test_single_id_is_accepted(mock_quarantine):
    mock_quarantine.return_value = {"quarantined": True}

    quarantine(VALID_IDS[:1])

    mock_quarantine.assert_called_once_with(VALID_IDS[:1])
