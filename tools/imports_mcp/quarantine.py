"""quarantine — tag a message "Quarantined" in Mailpit, over its HTTP API (T-030).

One of the four **gated** actions (§10 tool table, CLAUDE.md "four
sequential per-tool-call gates"). `harness/agent.json` already marks this
tool `require_approval_for_tools` (T-034), so TrueForge pauses the call for
a human licence decision before this module ever runs. Nothing here checks
for approval itself — that is the harness's job, and re-implementing it
would be exactly the "don't rebuild what the harness already does" mistake.

**Tags, does not delete.** Mailpit's `DELETE /api/v1/messages` genuinely
destroys evidence — and, worse, deletes *every* message in the mailbox if
`IDs` is empty or omitted (confirmed in the vendored `range/mailpit-api.json`
spec). A real security response contains a message, it doesn't destroy the
only record of the attack. `PUT /api/v1/tags` (tag as "Quarantined") is a
visible, irreversible-enough state change for §17's demo beat (2:20-2:40,
"Quarantined") without that failure mode — and the mailbox-protocol
decision behind T-022/T-030 (§6, 2026-08-29) already settled that Mailpit's
HTTP API, not IMAP, is how every one of these tools reaches the Range.

Talks only to the local Range's Mailpit instance (`MAILPIT_HTTP_BASE_URL`,
defaulting to `range/docker-compose.yml`'s published `8025`) — there is no
real-world mailbox behind this the way notify_impersonated/file_abuse_report
have a real recipient, so CLAUDE.md trap #6 doesn't apply here the same way,
but the target is still resolved at call time (not import time) so a test
can override it without re-importing the module, same pattern `_smtp.py`'s
`smtp_target()` and `domain_intel.py`'s `_crtsh_cache_db_path()` already use.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from imports_mcp._smtp import MAX_RESPONSE_BYTES, cap_response

MAILPIT_TIMEOUT_SECONDS = 10
QUARANTINE_TAG = "Quarantined"

_TRIMMABLE_STRING_FIELDS = ("note",)


def _mailpit_base_url() -> str:
    return os.environ.get("MAILPIT_HTTP_BASE_URL", "").strip() or "http://localhost:8025"


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """`message_ids` is a list, so it's trimmed from the end first — same
    order server.py's own `_cap_response` already uses for its list fields
    — before falling through to `_smtp.cap_response`'s shared, strictly-
    shrinking-toward-`""` handling of `note` (Rule 2880706's established
    shape, §6 2026-08-26: every future tool's cap function follows this
    exact pattern, not a new one)."""
    capped = dict(result)
    message_ids = list(capped.get("message_ids") or [])
    while message_ids and _serialized_size({**capped, "message_ids": message_ids}) > max_bytes:
        message_ids.pop()
    capped["message_ids"] = message_ids
    return cap_response(capped, _TRIMMABLE_STRING_FIELDS, max_bytes)


def quarantine(message_ids: list[str]) -> dict[str, Any]:
    """Tag one or more messages "Quarantined" in Mailpit.

    Gated: TrueForge holds this call for human approval before it runs
    (T-034). Never raises on a transport failure — returns
    `quarantined: False` with a note instead, same degradation contract as
    every other tool in this package.
    """
    base_url = _mailpit_base_url()

    try:
        resp = requests.put(
            f"{base_url}/api/v1/tags",
            json={"IDs": message_ids, "Tags": [QUARANTINE_TAG]},
            timeout=MAILPIT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return _cap_response(
            {
                "message_ids": message_ids,
                "tag": QUARANTINE_TAG,
                "quarantined": False,
                "note": f"Mailpit tag request failed: {exc}",
            }
        )

    if resp.status_code != 200:
        # resp.text is upstream-controlled - not pre-truncated here, since
        # _cap_response's shared shrink-toward-"" handling (Rule 2880706,
        # §6 2026-08-26) already covers any caller- or upstream-controlled
        # scalar; a second, fixed-size cut here would just be a second place
        # for the same guard to drift out of sync with the other tools.
        return _cap_response(
            {
                "message_ids": message_ids,
                "tag": QUARANTINE_TAG,
                "quarantined": False,
                "note": f"Mailpit returned HTTP {resp.status_code}: {resp.text.strip()}",
            }
        )

    return _cap_response(
        {
            "message_ids": message_ids,
            "tag": QUARANTINE_TAG,
            "quarantined": True,
            "note": f"tagged {len(message_ids)} message(s) {QUARANTINE_TAG!r} via {base_url}",
        }
    )
