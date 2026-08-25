"""imports-mcp — Slice 1 skeleton (T-012).

Streamable HTTP, stateless per request, one tool: parse_message. This is the
Python-SDK equivalent of the bring-your-own-mcp cookbook example (T-004):
same transport, same "register in TrueForge Settings, reference by name in
agent.json" pattern, no live IMAP mailbox wired up yet — Slice 1 reads a
hardcoded fixture instead (per PLAN.md §14: "hardcoded fixture -> parse").
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.normaliser import parse_message as _parse_message

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

mcp = MCPServer("imports-mcp")


def _resolve_fixture(fixture: str) -> Path:
    """Map a bare fixture name to a real file, staying inside FIXTURES_DIR.

    fixture is attacker-influenced (it's a tool argument), so this rejects
    anything that isn't a plain filename already present in FIXTURES_DIR
    rather than trusting a caller-supplied path.
    """
    candidate = (FIXTURES_DIR / fixture).resolve()
    if candidate.parent != FIXTURES_DIR or not candidate.is_file():
        available = sorted(p.name for p in FIXTURES_DIR.glob("*.eml"))
        raise ToolError(f"Unknown fixture {fixture!r}. Available: {available}")
    return candidate


@mcp.tool()
def parse_message(fixture: str) -> dict[str, Any]:
    """Parse a Slice-1 fixture .eml by filename (e.g. "01-credential-phish.eml").

    Returns headers, raw Authentication-Results/Received chains, URLs (href +
    anchor text), and attachment SHA256s. No network calls, no verdict — that's
    domain_intel/url_reputation/the verdict step, not this tool.
    """
    path = _resolve_fixture(fixture)
    with open(path, "rb") as f:
        return _parse_message(f.read())


if __name__ == "__main__":
    port = int(os.environ.get("IMPORTS_MCP_PORT", "8941"))
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=port,
        stateless_http=True,
        json_response=True,
    )
