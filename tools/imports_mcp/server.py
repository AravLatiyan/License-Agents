"""imports-mcp — Slice 1 skeleton (T-012).

Streamable HTTP, stateless per request, one tool: parse_message. This is the
Python-SDK equivalent of the bring-your-own-mcp cookbook example (T-004):
same transport, same "register in TrueForge Settings, reference by name in
agent.json" pattern, no live IMAP mailbox wired up yet — Slice 1 reads a
hardcoded fixture instead (per PLAN.md §14: "hardcoded fixture -> parse").
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.normaliser import parse_message as _parse_message

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Rule 2880706: MCP tool responses must stay under ~2KB and signal truncation.
# received_chain/urls/authentication_results are the fields that grow with a
# large or hostile message; they're trimmed first, in that order, until the
# serialized response fits.
MAX_RESPONSE_BYTES = 2000
_TRIMMABLE_FIELDS = ("received_chain", "urls", "authentication_results")

mcp = MCPServer("imports-mcp")


def _resolve_fixture(fixture: str) -> Path:
    """Map a bare fixture name to a real file, staying inside FIXTURES_DIR.

    fixture is attacker-influenced (it's a tool argument), so this rejects
    anything that isn't a plain .eml filename already present in
    FIXTURES_DIR — the advertised whitelist — rather than trusting a
    caller-supplied path or letting any regular file in the directory through.
    """
    candidate = (FIXTURES_DIR / fixture).resolve()
    if (
        candidate.parent != FIXTURES_DIR
        or not candidate.is_file()
        or candidate.suffix != ".eml"
    ):
        available = sorted(p.name for p in FIXTURES_DIR.glob("*.eml"))
        raise ToolError(f"Unknown fixture {fixture!r}. Available: {available}")
    return candidate


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """Cap the serialized response at ~max_bytes, with an explicit indicator.

    Adds `truncated` (bool) and, only when something was cut, `omitted`
    (per-field count of dropped entries) — a caller can tell evidence was
    trimmed, and how much, rather than silently getting a partial result.
    """
    capped = dict(result)
    capped["truncated"] = False
    if _serialized_size(capped) <= max_bytes:
        return capped

    omitted: dict[str, int] = {}
    for field in _TRIMMABLE_FIELDS:
        items = list(capped.get(field) or [])
        while items and _serialized_size({**capped, field: items, "truncated": True, "omitted": omitted}) > max_bytes:
            items.pop()
            omitted[field] = omitted.get(field, 0) + 1
        capped[field] = items
        if _serialized_size({**capped, "truncated": True, "omitted": omitted}) <= max_bytes:
            break

    capped["truncated"] = True
    capped["omitted"] = omitted
    return capped


@mcp.tool()
def parse_message(fixture: str) -> dict[str, Any]:
    """Parse a Slice-1 fixture .eml by filename (e.g. "01-credential-phish.eml").

    Returns headers, raw Authentication-Results/Received chains, URLs (href +
    anchor text), and attachment SHA256s. No network calls, no verdict — that's
    domain_intel/url_reputation/the verdict step, not this tool. Response is
    capped at ~2KB serialized (Rule 2880706); see `_cap_response`.
    """
    path = _resolve_fixture(fixture)
    with open(path, "rb") as f:
        result = _parse_message(f.read())
    return _cap_response(result)


if __name__ == "__main__":
    port = int(os.environ.get("IMPORTS_MCP_PORT", "8941"))
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=port,
        stateless_http=True,
        json_response=True,
    )
