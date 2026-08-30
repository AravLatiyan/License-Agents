"""create_block_rule — persist a sender-pattern block rule (T-032).

The fourth and last of the **gated** actions (§10 tool table, CLAUDE.md
"four sequential per-tool-call gates"). `harness/agent.json` has marked this
name `require_approval_for_tools` since T-034, so TrueForge pauses the call
for a human licence decision before this module runs. Nothing here checks
for approval — that is the harness's job, and re-implementing it would be
the "don't rebuild what the harness already does" mistake.

**READ THIS BEFORE BELIEVING THE NAME: the store is WRITE-ONLY.**

Nothing in this repository ever reads these rules back. No mail is blocked.
This tool records a decision; it does not enforce one. That is a deliberate,
approved scope call (T-032, Option B), taken only after confirming no real
target exists to enforce against:

- Mailpit is a mail *catcher*, not an MTA. Its entire vendored API surface
  (`range/mailpit-api.json`) is messages, tags, search, send, chaos, info —
  there is no rule, filter, or policy endpoint to install a pattern into.
  Its tags apply to messages that already arrived, by id, which is
  *quarantine* semantics and is what `quarantine.py` correctly uses them for.
- `range/fake-portal/` serves two static routes and reads no configuration.
- Nothing anywhere in `tools/`, `harness/`, `cockpit/` or `mission/` reads a
  blocklist, denylist or pattern list.

So the honest description is: this makes the fourth licence gate real — a
genuine tool call, a genuine human decision, a genuine durable record of
what was decided — without claiming an enforcement path that does not exist.
§17's beat for this gate is the *licence decision itself* (the demo denies
it: "Allow, allow, deny, allow", and this is gate 3 of 4 in `agent.json`'s
order), not a blocked message.

If a real enforcement target ever exists, this table is where it would read
from, and the shape below is chosen to make that possible rather than to
foreclose it.

Persistence follows `domain_intel.py`'s crt.sh cache (T-045) exactly — same
library, same call-time path resolution via an env var so a test can point
it somewhere disposable, same "a storage failure degrades, never raises"
posture. That is the only persistence precedent in this folder, and matching
it means one pattern to understand rather than two.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from imports_mcp._smtp import MAX_RESPONSE_BYTES, cap_response

# Same shape as _crtsh_cache_db_path (T-045): a file beside the module,
# overridable per-call so tests never touch the real store.
_DEFAULT_BLOCK_RULES_DB_PATH = os.path.join(os.path.dirname(__file__), ".block_rules.sqlite3")
BLOCK_RULES_DB_ENV = "BLOCK_RULES_DB_PATH"
BLOCK_RULES_DB_TIMEOUT_SECONDS = 5

# A pattern is a sender wildcard like "*@evil.example.com" (the shape the
# fixture and agent.json's own examples use). Bounded because the whole
# response has to fit MCP's ~2KB cap, and an unbounded pattern would eat it.
MAX_PATTERN_LENGTH = 512

_TRIMMABLE_STRING_FIELDS = ("note", "pattern")


def block_rules_db_path() -> str:
    """Resolved at call time, not import time — so a test (or a deployment)
    can point this somewhere else without re-importing the module. Same
    reasoning as `_crtsh_cache_db_path()` and `smtp_target()`."""
    return os.environ.get(BLOCK_RULES_DB_ENV, "").strip() or _DEFAULT_BLOCK_RULES_DB_PATH


def _cap(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """Every caller-controlled string is trimmable. `created` is never
    dropped — it is the field a caller branches on."""
    return cap_response(result, _TRIMMABLE_STRING_FIELDS, max_bytes)


def _failure(pattern: Any, note: str) -> dict[str, Any]:
    """One failure shape. `created: False` plus a note explaining why, never
    an exception: this tool sits behind a licence gate, and a raise would
    turn a refused write into a broken turn."""
    return _cap({"pattern": pattern if isinstance(pattern, str) else "", "created": False, "note": note})


def create_block_rule(pattern: str) -> dict[str, Any]:
    """Record a block rule for `pattern`. Never raises.

    Idempotent: the same pattern twice creates one row and reports
    `created: False` the second time. A licence gate can legitimately be
    approved twice (a retried tool call, a reconnect replaying a decision),
    and duplicating the row on the second would misrepresent one human
    decision as two.
    """
    if not isinstance(pattern, str):
        return _failure(pattern, "refused: pattern must be a string")

    # Whitespace is used to DETECT a blank pattern, never to transform what
    # gets stored. Stripping would durably record a different rule from the
    # one approved at the gate — " *@evil.example.com" would become the
    # broader "*@evil.example.com" — which is the exact failure this tool
    # refuses over-long patterns to avoid, so it must not commit it here
    # either (Qodo, PR #90). The approved string is stored verbatim.
    if not pattern.strip():
        return _failure(pattern, "refused: pattern was empty")
    if len(pattern) > MAX_PATTERN_LENGTH:
        return _failure(
            "",
            f"refused: pattern longer than {MAX_PATTERN_LENGTH} characters",
        )
    cleaned = pattern

    try:
        conn = sqlite3.connect(block_rules_db_path(), timeout=BLOCK_RULES_DB_TIMEOUT_SECONDS)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS block_rules "
                "(pattern TEXT PRIMARY KEY, created_at TEXT NOT NULL)"
            )
            # Parameterised, never interpolated — the pattern is model-supplied
            # and reaches here off a third party's message. A pattern like
            # "'; DROP TABLE block_rules;--" is stored as the literal string
            # it is, not executed.
            cursor = conn.execute(
                "INSERT OR IGNORE INTO block_rules (pattern, created_at) VALUES (?, ?)",
                (cleaned, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            # rowcount is 0 when INSERT OR IGNORE hit the primary key — that
            # is the idempotent case, not a failure.
            created = cursor.rowcount > 0
        finally:
            conn.close()
    except sqlite3.Error as exc:
        # Storage is unavailable, read-only, or the path is unusable. Degrade
        # exactly as the crt.sh cache does rather than raising.
        return _failure(cleaned, f"refused: could not record the rule ({type(exc).__name__})")
    except OSError as exc:
        return _failure(cleaned, f"refused: could not open the rule store ({type(exc).__name__})")
    except UnicodeError as exc:
        # A lone UTF-16 surrogate passes every check above — it is a str, not
        # blank, not over-length — but binding it as SQLite text raises
        # UnicodeEncodeError, which is neither sqlite3.Error nor OSError. Such
        # a string can genuinely arrive through a JSON escape, and this tool
        # promises a structured refusal for ANY input rather than a raise
        # (Qodo, PR #90).
        return _failure("", f"refused: pattern is not storable text ({type(exc).__name__})")

    note = (
        f"block rule recorded for {cleaned}"
        if created
        else f"block rule for {cleaned} already existed — not duplicated"
    )
    return _cap({"pattern": cleaned, "created": created, "note": note})
