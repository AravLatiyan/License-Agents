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

**One GET+PUT pair per message, not one batched PUT (Qodo, PR #67 finding
#1).** The same vendored spec that documents `PUT /api/v1/tags` also states
it plainly: "This will overwrite any existing tags for selected message
database IDs." A single call carrying only `["Quarantined"]` for every ID
would silently wipe out any tag Mailpit or another tool had already set.
Each message's current tags (`GET /api/v1/message/{ID}`, which returns them
in its own `Tags` field) are fetched first and unioned with "Quarantined"
before the tag is set — a genuine read-then-write per message, not a single
shared array assumed safe for all of them.

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
from lxml import html as lxml_html

from imports_mcp._smtp import MAX_RESPONSE_BYTES, cap_response, shrink_string

MAILPIT_TIMEOUT_SECONDS = 10
QUARANTINE_TAG = "Quarantined"

_TRIMMABLE_STRING_FIELDS = ("note",)


def _mailpit_base_url() -> str:
    return os.environ.get("MAILPIT_HTTP_BASE_URL", "").strip() or "http://localhost:8025"


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _describe_response(resp: requests.Response) -> str:
    """CLAUDE.md trap #3: never return raw HTML to the model. Mailpit's own
    spec declares `PUT /api/v1/tags` and `GET /api/v1/message/{ID}` produce
    `text/plain`/`application/json`, but a misconfigured MAILPIT_HTTP_BASE_URL
    or a reverse proxy in front of a real Mailpit could still hand back an
    HTML error page (Qodo, PR #67 finding #3) - content-type is checked, not
    assumed, and only the extracted text (never regex, trap #5) is kept.
    """
    body = resp.text.strip()
    if "html" in resp.headers.get("content-type", "").lower() and body:
        body = lxml_html.fromstring(body).text_content().strip()
    return body


def _cap_response(result: dict[str, Any], max_bytes: int = MAX_RESPONSE_BYTES) -> dict[str, Any]:
    """`message_ids` is a list, so it's trimmed from the end first — same
    order server.py's own `_cap_response` already uses for its list fields
    — before falling through to `_smtp.cap_response`'s shared, strictly-
    shrinking-toward-`""` handling of `note` (Rule 2880706's established
    shape, §6 2026-08-26: every future tool's cap function follows this
    exact pattern, not a new one).

    The trimming loop runs *before* `cap_response`, so a payload that only
    became small enough because IDs were dropped here would otherwise reach
    `cap_response` already under budget and get reported `truncated: False`
    — the trim happened, but the flag `cap_response` sets is computed fresh
    against the *already-shrunk* payload, so it never sees it (Qodo, PR #67
    finding #2). The final result's `truncated`/`omitted` are corrected
    afterward to account for both trimming steps, not just the second one.
    """
    capped = dict(result)
    message_ids = list(capped.get("message_ids") or [])
    original_count = len(message_ids)
    while message_ids and _serialized_size({**capped, "message_ids": message_ids}) > max_bytes:
        message_ids.pop()
    capped["message_ids"] = message_ids

    final = cap_response(capped, _TRIMMABLE_STRING_FIELDS, max_bytes)
    ids_omitted = original_count - len(message_ids)
    if ids_omitted:
        final["truncated"] = True
        omitted = dict(final.get("omitted") or {})
        omitted["message_ids"] = ids_omitted
        final["omitted"] = omitted
        # Adding this bookkeeping can itself push an already-capped response
        # a few bytes back over budget - cap_response has no way to know
        # about it, since it ran before this dict existed. Re-check and
        # shrink `note` further rather than silently return an over-budget
        # response with truncated: True next to it.
        note = final.get("note")
        while isinstance(note, str) and note and _serialized_size(final) > max_bytes:
            note = shrink_string(note)
            final["note"] = note
    return final


def _current_tags(base_url: str, message_id: str) -> list[str]:
    """The message's own current tags, per `GET /api/v1/message/{ID}`'s
    documented `Tags` field. Raises on any failure - the caller decides how
    to degrade, same division of responsibility `quarantine()` already uses
    for its own requests."""
    resp = requests.get(f"{base_url}/api/v1/message/{message_id}", timeout=MAILPIT_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    tags = data.get("Tags")
    return list(tags) if isinstance(tags, list) else []


def _quarantine_one(base_url: str, message_id: str) -> str | None:
    """Tag a single message "Quarantined" without disturbing whatever tags
    it already has. Returns None on success, or a short failure reason."""
    try:
        current = _current_tags(base_url, message_id)
    except (requests.RequestException, ValueError) as exc:
        return f"could not read current tags: {exc}"

    tags = current if QUARANTINE_TAG in current else [*current, QUARANTINE_TAG]

    try:
        resp = requests.put(
            f"{base_url}/api/v1/tags",
            json={"IDs": [message_id], "Tags": tags},
            timeout=MAILPIT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return f"tag request failed: {exc}"

    if resp.status_code != 200:
        return f"Mailpit returned HTTP {resp.status_code}: {_describe_response(resp)}"

    return None


def quarantine(message_ids: list[str]) -> dict[str, Any]:
    """Tag one or more messages "Quarantined" in Mailpit, preserving each
    message's existing tags.

    Gated: TrueForge holds this call for human approval before it runs
    (T-034). Never raises on a transport failure — returns
    `quarantined: False` with a note instead, same degradation contract as
    every other tool in this package. `quarantined` is only True once every
    requested message was tagged; a partial failure is reported as False
    with the specific failures named, not silently treated as a success.
    """
    base_url = _mailpit_base_url()
    failures: list[str] = []

    for message_id in message_ids:
        reason = _quarantine_one(base_url, message_id)
        if reason is not None:
            failures.append(f"{message_id}: {reason}")

    if failures:
        note = f"{len(failures)}/{len(message_ids)} message(s) failed: " + "; ".join(failures)
    else:
        note = f"tagged {len(message_ids)} message(s) {QUARANTINE_TAG!r} via {base_url}"

    return _cap_response(
        {
            "message_ids": message_ids,
            "tag": QUARANTINE_TAG,
            "quarantined": not failures,
            "note": note,
        }
    )
