"""imports-mcp — Slice 1 + 2 skeleton (T-012, T-020, T-021).

Streamable HTTP, stateless per request. This is the Python-SDK equivalent of
the bring-your-own-mcp cookbook example (T-004): same transport, same
"register in TrueForge Settings, reference by name in agent.json" pattern.

Tools:
  parse_message   - hardcoded-fixture RFC822 parse (Slice 1, no IMAP yet)
  domain_intel    - RDAP registration/abuse + crt.sh cert age (Slice 2)
  url_reputation  - URLhaus exact-URL lookup (Slice 2)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from imports_mcp.domain_intel import domain_intel as _domain_intel
from imports_mcp.normaliser import parse_message as _parse_message
from imports_mcp.url_reputation import url_reputation as _url_reputation

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Rule 2880706: MCP tool responses must stay under ~2KB and signal truncation.
# List fields grow with a large or hostile message and are emptied first, in
# this order (one entry at a time, tracked in `omitted`). If the response is
# still oversized once every list is empty, the overflow is in a scalar
# string field instead - subject, date, or an address/display name - so
# those are shortened next, same "cut it down until it fits" approach.
# Nothing is ever assumed to fit: the serialized size is re-checked after
# every single step, list or string.
MAX_RESPONSE_BYTES = 2000
_TRIMMABLE_LIST_FIELDS = ("received_chain", "urls", "authentication_results", "attachments")
_TRIMMABLE_STRING_FIELDS = ("subject", "date")
_TRIMMABLE_ADDRESS_FIELDS = ("from", "reply_to", "return_path")
_STRING_SHRINK_CHARS = 40

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


def _shrink_string(value: str) -> str:
    """Cuts one chunk off the end of value, leaving an ellipsis marker so a
    caller can tell the field was cut short rather than genuinely this
    short. Must strictly shrink toward "" (not plateau at "…") so a caller
    looping "shrink until it fits" always terminates even when this field
    alone can't make the response fit and every other field is untouched."""
    if len(value) <= _STRING_SHRINK_CHARS:
        return ""
    return value[: -_STRING_SHRINK_CHARS] + "…"


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """Cap the serialized response at ~max_bytes, with an explicit indicator.

    Adds `truncated` (bool) and, once true, `omitted` (per-field count of
    dropped list entries) — a caller can tell evidence was trimmed, and how
    much, rather than silently getting a partial result. List fields are
    emptied first (received_chain/urls/authentication_results/attachments,
    in that order); if that alone isn't enough, subject/date/address fields
    are shortened next, character by character rather than dropped outright
    — an oversized value is itself potential evidence, so it's kept in
    truncated form instead of disappearing. The final serialized size is
    verified after every step, never assumed to fit.
    """
    capped = dict(result)
    capped["truncated"] = False
    if _serialized_size(capped) <= max_bytes:
        return capped

    omitted: dict[str, int] = {}
    capped["truncated"] = True
    capped["omitted"] = omitted

    def fits() -> bool:
        return _serialized_size(capped) <= max_bytes

    for field in _TRIMMABLE_LIST_FIELDS:
        items = list(capped.get(field) or [])
        capped[field] = items
        while items and not fits():
            items.pop()
            omitted[field] = omitted.get(field, 0) + 1
        if fits():
            return capped

    for field in _TRIMMABLE_STRING_FIELDS:
        value = capped.get(field)
        while isinstance(value, str) and value and not fits():
            value = _shrink_string(value)
            capped[field] = value
        if fits():
            return capped

    for field in _TRIMMABLE_ADDRESS_FIELDS:
        original_address = capped.get(field)
        if not isinstance(original_address, dict):
            continue
        address = dict(original_address)  # copy - never mutate the caller's result
        capped[field] = address
        for sub_field in ("display_name", "address"):
            value = address.get(sub_field)
            while isinstance(value, str) and value and not fits():
                value = _shrink_string(value)
                address[sub_field] = value
            if fits():
                return capped

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


@mcp.tool()
def domain_intel(domain: str) -> dict[str, Any]:
    """RDAP registration/abuse data + crt.sh cert age for a domain.

    Each source degrades independently to available=False with an
    explanatory note instead of raising - a down source is evidence
    ("not published", "crt.sh unreachable"), not a tool failure.
    """
    domain = domain.strip()
    if not domain:
        raise ToolError("domain must not be empty")
    return _domain_intel(domain)


@mcp.tool()
def url_reputation(url: str) -> dict[str, Any]:
    """URLhaus verdict for one exact URL.

    URLhaus is malware-focused, not phishing-focused: "not listed" is weak
    evidence only, never a verdict on its own — never build a demo beat on
    a URLhaus hit alone.
    """
    url = url.strip()
    if not url:
        raise ToolError("url must not be empty")
    return _url_reputation(url)


if __name__ == "__main__":
    port = int(os.environ.get("IMPORTS_MCP_PORT", "8941"))
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=port,
        stateless_http=True,
        json_response=True,
    )
