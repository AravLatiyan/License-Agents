"""Unit tests for create_block_rule (T-0XX) — one of the four GATED actions.

Written against the SPEC, not the implementation: `create_block_rule.py`
may not exist yet while this file is authored, and that is expected (see
PLAN.md handoff note). The storage design mirrors T-045's crt.sh SQLite
cache in domain_intel.py exactly:

- default DB path is a file next to the module, resolved AT CALL TIME (not
  import time) via a helper reading `BLOCK_RULES_DB_PATH`, falling back to
  a default in the module's own directory. Every test below sets that env
  var to a tmp_path file first, so nothing here ever touches the real
  store on a developer's machine.
- table created with `CREATE TABLE IF NOT EXISTS`, same as crt.sh's cache.

Like quarantine.py, this tool must NEVER raise — a gated action is already
paused for a human decision by TrueForge (`require_approval_for_tools`,
T-034); the tool itself degrades to a structured failure result instead of
throwing, the same contract every sibling tool in this package holds to.

Assertions about the SQLite file's contents are made by opening it
directly with the stdlib `sqlite3` module — this file is the only place
that reads the store back; the tool itself is write-only by design.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from imports_mcp.create_block_rule import create_block_rule

# Rule 2880706 / _smtp.py's canonical value: every MCP tool response stays
# under ~2KB and signals truncation explicitly. Read from the shared
# constant rather than assumed as a magic number, but not from
# create_block_rule itself — the spec doesn't require that module to
# re-export a same-named constant, only to honour the cap.
from imports_mcp._smtp import MAX_RESPONSE_BYTES

TABLE_NAME = "block_rules"


# --- local helpers: the only code in the repo that reads this store back ----


def _table_exists(db_path: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE_NAME,),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def _read_patterns(db_path: str) -> list[str]:
    """All stored patterns, in insertion order. Assumes only what the SPEC
    guarantees: a `pattern` column on the `block_rules` table."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(f"SELECT pattern FROM {TABLE_NAME}")
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def _row_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Every test gets its own throwaway SQLite file — never the real
    store next to the module. Resolved at call time (per SPEC), so setting
    the env var here, without re-importing create_block_rule, is enough."""
    path = str(tmp_path / "block_rules.sqlite3")
    monkeypatch.setenv("BLOCK_RULES_DB_PATH", path)
    return path


# --- default path resolution -------------------------------------------------


def test_default_db_path_lives_next_to_the_module(monkeypatch: pytest.MonkeyPatch):
    """With no BLOCK_RULES_DB_PATH configured, the store must default to a
    file inside the module's own directory — same pattern as
    domain_intel.py's `_crtsh_cache_db_path()` (T-045). If this default
    ever silently changed to something else (a shared temp dir, a path
    outside the repo), this is the tripwire."""
    monkeypatch.delenv("BLOCK_RULES_DB_PATH", raising=False)
    import imports_mcp.create_block_rule as create_block_rule_module

    default_path = create_block_rule_module.block_rules_db_path()

    module_dir = os.path.dirname(create_block_rule_module.__file__)
    assert os.path.dirname(default_path) == module_dir


def test_blank_env_var_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch):
    """Same class of bug Qodo caught on notify_impersonated (PR #29 finding
    #1) and quarantine's MAILPIT_HTTP_BASE_URL test: a set-but-empty env
    var (what `.env.example`'s `KEY=` loads as via python-dotenv) must not
    silently become an unusable empty path."""
    monkeypatch.setenv("BLOCK_RULES_DB_PATH", "")
    import imports_mcp.create_block_rule as create_block_rule_module

    default_path = create_block_rule_module.block_rules_db_path()

    module_dir = os.path.dirname(create_block_rule_module.__file__)
    assert os.path.dirname(default_path) == module_dir


# --- the happy path -----------------------------------------------------------


def test_valid_pattern_is_stored_and_reports_success(db_path: str):
    result = create_block_rule("phish-sender@evil.example")

    assert result["pattern"] == "phish-sender@evil.example"
    assert result["created"] is True
    assert isinstance(result["note"], str) and result["note"]

    # The only read of the store that exists — proves the row is really
    # there, not just that the tool claims success.
    assert "phish-sender@evil.example" in _read_patterns(db_path)


# --- idempotency: no duplicate rows, no error on a repeat -------------------


def test_repeat_call_with_same_pattern_is_idempotent(db_path: str):
    first = create_block_rule("repeat-offender@evil.example")
    second = create_block_rule("repeat-offender@evil.example")

    assert first["created"] is True
    assert second["created"] is False
    # Still succeeds - "already exists" is not a failure to report, and the
    # note should say so rather than looking like an unexplained no-op.
    assert isinstance(second["note"], str) and second["note"]
    assert "already" in second["note"].lower() or "exist" in second["note"].lower()

    # The row-count check, not just the two dicts, is what actually proves
    # no duplicate was inserted.
    assert _row_count(db_path) == 1
    assert _read_patterns(db_path) == ["repeat-offender@evil.example"]


def test_three_distinct_patterns_all_persist(db_path: str):
    """Concurrent/repeated calls for genuinely different patterns must each
    land their own row — idempotency must be keyed on the pattern, not
    accidentally collapse every call into one."""
    patterns = ["a@evil.example", "b@evil.example", "c@evil.example"]
    for pattern in patterns:
        result = create_block_rule(pattern)
        assert result["created"] is True

    assert _row_count(db_path) == 3
    assert set(_read_patterns(db_path)) == set(patterns)


# --- fail-safe: never raises on bad input ------------------------------------


@pytest.mark.parametrize(
    "bad_pattern",
    ["", "   ", "\t", None, 123, ["a", "list"], {"not": "a string"}],
    ids=["empty", "whitespace", "tab", "none", "int", "list", "dict"],
)
def test_invalid_input_degrades_instead_of_raising(db_path: str, bad_pattern):
    """Every one of these is a caller/model mistake, not a valid sender
    pattern. The tool must report a structured failure - never raise, and
    never silently create a nonsense block rule."""
    result = create_block_rule(bad_pattern)

    assert result["created"] is False
    assert isinstance(result["note"], str) and result["note"]


def test_invalid_input_never_creates_a_row(db_path: str):
    """Belt-and-braces on the parametrized case above: confirm the store
    itself stays empty (or at least gains no row for the input) rather
    than only trusting the returned dict's `created` flag."""
    create_block_rule("")
    create_block_rule(None)
    create_block_rule(123)

    # The table may or may not have been created at all yet by this point -
    # either is acceptable, since nothing valid has been stored. Only assert
    # there is no row if the table exists.
    if os.path.exists(db_path) and _table_exists(db_path):
        assert _row_count(db_path) == 0


# --- SQL injection cannot corrupt the store (proves parameterised queries) --


def test_sql_metacharacter_pattern_does_not_raise(db_path: str):
    malicious = "'; DROP TABLE block_rules;--"

    result = create_block_rule(malicious)  # must not raise

    assert isinstance(result, dict)
    assert isinstance(result["note"], str)


def test_sql_injection_pattern_cannot_corrupt_the_store(db_path: str):
    """The real proof that the store uses parameterised queries, not
    string-built SQL: after passing a pattern that would DROP the table if
    ever concatenated into a query, the table must still exist, and the
    store must still work normally afterward."""
    malicious = "'; DROP TABLE block_rules;--"
    create_block_rule(malicious)

    assert _table_exists(db_path)

    # A subsequent, ordinary call must still succeed and be queryable -
    # proof the table survived intact, not just that sqlite_master lists it.
    result = create_block_rule("still-works@evil.example")
    assert result["created"] is True
    assert "still-works@evil.example" in _read_patterns(db_path)


# --- a DB error degrades instead of raising ----------------------------------


def test_db_path_pointing_at_a_directory_degrades_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """sqlite3.connect() on a path that is itself a directory raises
    OperationalError ("unable to open database file"). This must never
    escape create_block_rule - a persistence failure is reported as a
    normal failure result, exactly like every other degrade-not-raise path
    in this package (quarantine's connection failures, domain_intel's
    cache misses)."""
    monkeypatch.setenv("BLOCK_RULES_DB_PATH", str(tmp_path))  # a directory, not a file

    result = create_block_rule("victim@evil.example")

    assert result["created"] is False
    assert isinstance(result["note"], str) and result["note"]


def test_db_path_inside_missing_directory_degrades_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """sqlite3 does not create missing parent directories - a path like
    .../nonexistent/db.sqlite3 also raises OperationalError. Same
    degrade-don't-raise contract as the directory case above."""
    unusable = tmp_path / "nonexistent_subdir" / "block_rules.sqlite3"
    monkeypatch.setenv("BLOCK_RULES_DB_PATH", str(unusable))

    result = create_block_rule("victim@evil.example")

    assert result["created"] is False
    assert isinstance(result["note"], str) and result["note"]


# --- response-size cap (Rule 2880706) ----------------------------------------


def test_normal_response_is_not_truncated(db_path: str):
    result = create_block_rule("short-pattern@evil.example")

    assert result["truncated"] is False
    assert _serialized_size(result) <= MAX_RESPONSE_BYTES


def test_extremely_long_pattern_is_refused_not_truncated(db_path: str):
    """An over-long pattern is REFUSED, deliberately not truncated.

    quarantine truncates its oversized message-id list, and this suite was
    first written to mirror that. It is the wrong convention here, and the
    difference is a safety one rather than a stylistic one: a block rule is
    approved at a licence gate for one specific pattern. Truncating
    "x"*10000 down to 512 characters would silently record a DIFFERENT rule
    from the one the human said yes to. quarantine's list can lose a
    trailing id and still be a subset of what was approved; a truncated
    wildcard is a new rule nobody approved.

    So the tool bounds the pattern up front and refuses beyond it. Nothing
    is stored, and the refusal is explicit rather than a silent narrowing.
    """
    huge_pattern = "x" * 10_000

    result = create_block_rule(huge_pattern)  # must not raise

    assert isinstance(result, dict)
    assert result["created"] is False, "an over-long pattern must not be stored"
    assert "refused" in result["note"]
    assert _serialized_size(result) <= MAX_RESPONSE_BYTES

    # And nothing reached the store at all - the refusal happens before any
    # connection is opened, so the table is never even created. Asserting the
    # absence of the table is a stronger guarantee than a zero row count: it
    # proves the rejected input never got as far as the database.
    with sqlite3.connect(db_path) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='block_rules'"
        ).fetchall()
    assert tables == [], "a refused pattern must not even open the rule store"
