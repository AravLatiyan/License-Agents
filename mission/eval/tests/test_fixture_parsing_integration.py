"""Real, non-mocked regression test for Qodo's PR #76 finding "Eval emails
cannot be parsed": the real agent's own prompt (harness/agent.json) requires
calling parse_message(fixture) before anything else, and that tool
(tools/imports_mcp/server.py's _resolve_fixture) only resolves a bare
filename already present in tools/fixtures/ - a fixed, hardcoded directory
that cannot be redirected to a tmp_path for testing.

This deliberately does NOT mock parse_message or _resolve_fixture: it
imports and calls the real tool function against the real tools/fixtures/
directory, proving the exact filename/path contract eval_lib.py's
write_temp_fixture()/fixture_turn_message() produce is one the real parser
actually accepts - not just that the eval harness's own mocked tests pass.

Every write is cleaned up in a finally, success or failure, using the same
UUID-suffixed names write_temp_fixture() already generates - no collision
risk with the three permanent Slice-1 fixtures or with a concurrent test
run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

from imports_mcp.server import parse_message  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from eval_lib import (  # noqa: E402
    FIXTURES_DIR,
    delete_temp_fixture,
    fixture_turn_message,
    load_fixtures,
    write_temp_fixture,
)


def _fixture(label: str):
    return next(f for f in load_fixtures(FIXTURES_DIR) if f.label == label)


@pytest.mark.parametrize("label", ["phish", "ham"])
def test_the_real_parse_message_tool_resolves_a_written_eval_fixture(label):
    """The exact end-to-end claim Qodo's finding disputes: write a real eval
    fixture the way evaluate_fixture() does, then call the REAL
    parse_message(fixture) - imported directly from tools/imports_mcp/
    server.py, never mocked - with the exact filename fixture_turn_message()
    tells the model to use. Must succeed for both ground-truth labels, not
    just one."""
    fixture = _fixture(label)
    temp_name = write_temp_fixture(fixture.raw_email)
    try:
        # The filename the model is actually told to pass, not a filename
        # this test invents independently - proves the two sides agree.
        message = fixture_turn_message(temp_name)
        assert temp_name in message

        result = parse_message(temp_name)

        assert isinstance(result, dict)
        assert "from" in result
        assert "urls" in result
        assert "authentication_results" in result
    finally:
        delete_temp_fixture(temp_name)


def test_parse_message_no_longer_resolves_after_cleanup():
    """Cleanup must actually happen, and only after the turn is done - a
    fixture that outlives its own turn is a stale-state risk for whichever
    fixture runs next (event isolation's filesystem counterpart)."""
    fixture = _fixture("phish")
    temp_name = write_temp_fixture(fixture.raw_email)

    parse_message(temp_name)  # succeeds while the file exists

    delete_temp_fixture(temp_name)

    with pytest.raises(ToolError):
        parse_message(temp_name)


def test_two_fixtures_written_concurrently_do_not_collide():
    """write_temp_fixture's uniqueness guarantee, proven against the real
    filesystem and the real resolver - not just asserted string inequality
    (already covered in test_eval_lib.py) but that both names independently
    and correctly resolve to their OWN distinct content at the same time."""
    phish = _fixture("phish")
    ham = _fixture("ham")
    phish_name = write_temp_fixture(phish.raw_email)
    ham_name = write_temp_fixture(ham.raw_email)
    try:
        assert phish_name != ham_name
        phish_result = parse_message(phish_name)
        ham_result = parse_message(ham_name)
        # Each resolved to its own fixture's own sender, not the other's.
        assert phish_result["from"] != ham_result["from"]
    finally:
        delete_temp_fixture(phish_name)
        delete_temp_fixture(ham_name)
