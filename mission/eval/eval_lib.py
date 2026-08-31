"""mission/eval/eval_lib.py — T-042 gate-trigger evaluation harness.

Evaluates the REAL `universal-imports` TrueForge agent against 20 real
phishing_pot samples and 20 real SpamAssassin `easy_ham` samples
(mission/eval/fixtures/, §13 Tier 2). Never a heuristic classifier, never
prose parsing — see METRIC NAME below for why.

WIRE-LEVEL SIGNAL
------------------
There is no live producer of a three-way `malicious|suspicious|legitimate`
verdict anywhere in this project: `contracts/events.ts`'s `VerdictLabel`
exists as a type, but T-037's own translator (harness/translate/translate.ts,
PR #73) deliberately never emits it — "the stream carries only the model's
prose; parsing a label out of prose is inventing semantics." This harness
does not invent one either.

Instead it reads TrueForge's own real wire event, `tool.approval_required`
(contracts/events.ts, Layer 1 — "confirmed live in T-002... re-verified
field-by-field against a running server's own openapi.json in T-037,
2026-08-29", on the `contracts/t037-toolcallref` branch — not yet merged,
but the schema fact itself is independent of whether that PR has landed;
this module only reads the documented shape, it does not import or depend
on T-037's code). TrueForge only ever fires this event for a tool named in
`harness/agent.json`'s `require_approval_for_tools` list — so its mere
occurrence is proof the model proposed one of the four gated actions
(`quarantine`, `notify_impersonated`, `create_block_rule`,
`file_abuse_report`), without this harness ever reading or classifying the
model's own prose.

CORRECTED WIRE SHAPE (T-037, 2026-08-29 — the shape this module targets):
`tool.approval_required.tool_calls` is `ToolCallRef[]` — `{id,
source_event_id}` only, NOT the tool's name. The name/arguments were
published earlier, on the `model.message` event `source_event_id` points
at, inside *that* event's own `tool_calls: ModelMessageToolCall[]`
(`{id, type: "function", function: {name, arguments}}`). Resolving a ref
means remembering every `model.message` event's tool calls as the stream is
read, then looking up `source_event_id` -> `tool_calls[].id == ref.id` ->
the tool actually being invoked. That last step is NOT simply
`.function.name`: TrueForge proxies every MCP tool, so `function.name` is
`call_tool` and the real name is `tool_name` inside that call's own
JSON-encoded `arguments` (see _MCP_PROXY_TOOL_NAMES).
On the live stream the finished message is not
available in time: TrueForge opens an assistant turn with a `model.message`
HEADER carrying no tool calls, streams the calls as `model.message.delta`
events, and only assembles the complete message afterwards (persisted, and
returned by GET /events, but emitted too late to correlate against). So the
deltas are accumulated per event id and per tool-call index and folded into
the same shape - structured tool-call data throughout, never prose.
This module keeps that correlation state per-turn (never
across fixtures — see EVENT ISOLATION below).

Name resolution is best-effort diagnostic detail, not the correctness
boundary: the *occurrence* of `tool.approval_required` at all is already
sufficient proof of a positive prediction (TrueForge cannot fire it for a
non-gated tool by construction), so an unresolved reference still counts as
a gate firing — it just cannot be labelled with which of the four tools
fired. This is deliberately more robust than depending on every reference
resolving cleanly.

SAFETY — never resumes a gate
------------------------------
The moment `tool.approval_required` is observed, this module already has
its answer and stops reading the stream. It never posts a
`user.tool_approval` resume. A paused gate with nothing resuming it simply
stays parked — the underlying action (a real quarantine tag, a real SMTP
send, a real abuse-report email) never executes. These are historical
corpus emails being scored, not the live demo; nothing here is allowed to
fire for real (same spirit as CLAUDE.md trap #6, applied to evaluation).

METRIC NAME — deliberately not "agent verdict accuracy"
---------------------------------------------------------
Because the signal is "did the agent propose a gated action," not "did the
agent's own three-way verdict match," this module reports **gate-trigger
accuracy** and **false-positive rate**, defined exactly as:

    predicted positive  = >=1 gated tool proposed for that fixture
    predicted negative  = no gated tool proposed
    ground truth positive = fixture sourced from phishing_pot (label "phish")
    ground truth negative = fixture sourced from SpamAssassin easy_ham (label "ham")

    gate_trigger_accuracy   = (true_positives + true_negatives) / total_scored
    false_positive_rate     = false_positives / total_ham_scored

`total_scored` excludes fixtures whose evaluation failed outright (network
error, non-2xx response, malformed session/turn creation, the live
model-provider being unconfigured) — a failure is never silently folded
into "negative"; see FixtureResult.error and Report.failed below.

FIXTURE DELIVERY — via tools/fixtures/, matching parse_message's real contract
-------------------------------------------------------------------------------
The real agent's own prompt (harness/agent.json) requires it to call
`parse_message(fixture)` before anything else, and that tool
(tools/imports_mcp/server.py's `_resolve_fixture`) only accepts a bare
filename already present in `tools/fixtures/` — not arbitrary email content
(Qodo, PR #76 review, "Eval emails cannot be parsed": submitting raw RFC822
text as the turn's message would leave the model unable to resolve any
fixture, either failing the call outright or silently analyzing one of
Slice 1's three unrelated hardcoded fixtures instead — invalidating the
measured result either way). Each fixture is written into `tools/fixtures/`
under a fresh UUID-suffixed name immediately before its turn
(`write_temp_fixture`) and deleted again in a `finally` right after
(`delete_temp_fixture`), success or failure, never left behind — the turn's
own message then names that exact file (`fixture_turn_message`). This is a
cross-folder *runtime* write, not a source change — `tools/imports_mcp/`
itself is untouched — but it touches O2's fixture directory, flagged here
per CLAUDE.md's cross-folder heads-up convention.

WIRE SHAPES — verified against a live TrueForge 0.1.4 instance
-------------------------------------------------------------------
The two request bodies that were previously flagged as unverified (the
field `POST /sessions` uses to bind a session to an agent by name, and the
`input` shape for a turn's *initial* user message) are now confirmed
against a running server's own `/api/v1/openapi.json` and by issuing the
requests, 2026-08-30. Four assumptions were wrong and are fixed here:

  1. Every route is under `/api/v1` (`API_PREFIX`). The bare `/sessions`
     this module used returned 404.
  2. `POST /api/v1/sessions` takes `{"agent": {"name": ...}}`
     (`CreateSessionRequest` -> `CreateSessionAgent` -> `SessionAgentNameRef`).
     The previous `{"agent_name": ...}` returned
     400 'Unrecognized key: "agent_name"'.
  3. The created session's id is nested: `{"data": {"id": ...}}`
     (`GetSessionResponse` -> `Session`), not a top-level `id`.
  4. `CreateTurnRequest.input` is an **array** of `TurnInputItem`, not a
     single object. The previous object body returned
     400 'expected array, received object'.

Each was confirmed by the server's own validation error before any model
call was made, so none of this cost a paid turn.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_JSON_PATH = REPO_ROOT / "harness" / "agent.json"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_LABELS = ("phish", "ham")

# The real agent's own prompt (harness/agent.json) requires it to call
# parse_message(fixture) before anything else, and that tool only accepts a
# bare filename already present in this exact directory (tools/imports_mcp/
# server.py's _resolve_fixture whitelist) - not arbitrary content (Qodo, PR
# #76 review, "Eval emails cannot be parsed"). Each fixture is written here
# under a unique name immediately before its turn and deleted again in a
# `finally` right after - never left behind, same seed-then-delete pattern
# T-022's own live Mailpit test already uses (PR #72).
TOOLS_FIXTURES_DIR = REPO_ROOT / "tools" / "fixtures"

DEFAULT_TRUEFORGE_URL = "http://localhost:8790"

# Every TrueForge route lives under this prefix - confirmed against a live
# instance's own openapi.json (2026-08-30). The bare "/sessions" this module
# used before returned 404, and a 404 is a transport error, so every fixture
# would have been reported as failed rather than scored.
API_PREFIX = "/api/v1"
TRUEFORGE_TIMEOUT_SECONDS = 60.0  # a real multi-tool-call turn can take a while

# "The wire finished without ever asking for a licence." Arriving with no
# prior tool.approval_required means this fixture never proposed a gated
# action.
#
# `turn.done` is the only turn-terminal type in TrueForge's own 12-type
# streaming union (TurnStreamingEvent, verified against a live instance's
# openapi.json, 2026-08-30). `mission.complete` is this project's own
# Layer 2 translated event (contracts/events.ts), never emitted on the raw
# wire this module reads - it is kept only so a future translated-stream
# consumer of this constant stays correct, and is inert here.
#
# `thread.done` is deliberately NOT in this list even though it is
# turn-terminal-looking: it fires once per thread, and a delegated subagent
# finishing would end the read long before the root agent has proposed
# anything.
_TURN_FINISHED_EVENT_TYPES = ("turn.done", "mission.complete")

# TurnDoneEvent.state is one of TurnStateDone / TurnStateCancelled /
# TurnStateError, discriminated on `status`. Only "done" means the agent
# actually finished and chose not to act; the other two mean the turn never
# reached a decision at all.
#
# Found the hard way on the first live fixture (2026-08-30): a real turn.done
# arrived carrying {"status": "error", "message": "Cannot connect to API: "}
# after a subagent's model call failed mid-turn, and this module scored it
# `predicted_positive=False, error=None` - a false negative on a
# ground-truth phishing fixture, indistinguishable from a real "the agent
# saw the evidence and declined to act". Exactly the failure the module
# docstring promises never happens; it was already handled for truncated
# streams and transport errors, and simply missed for an errored turn.
_TURN_SUCCEEDED_STATUS = "done"
_TURN_ERROR_STATUS = "error"

# Terminal event types that legitimately carry no `state` at all. Only this
# project's own Layer 2 `mission.complete` qualifies (contracts/events.ts).
#
# TrueForge's raw `turn.done` is NOT in this set: its schema requires `state`,
# and that state is the discriminated union this module reads. A `turn.done`
# without a readable status is protocol drift, not a completed turn - accepting
# it as one would recreate exactly the silent metric corruption this module
# fixed (Qodo, PR #99, "Missing status scores negative").
_STATELESS_TERMINAL_EVENT_TYPES = ("mission.complete",)

# Transport-layer failures that mean "this fixture's evaluation could not be
# completed," never "the model quietly declined to act." HTTPError/URLError
# alone missed a real class of failure (Qodo, PR #76, "Stream timeouts abort
# evaluation"): a timeout or dropped connection *while iterating* an
# already-open SSE response raises a bare TimeoutError/ConnectionError/
# http.client.HTTPException, none of which subclass URLError - uncaught,
# any of these would escape evaluate_fixture entirely and abort the whole
# 40-fixture loop instead of recording one failed fixture.
_TRANSPORT_ERRORS = (
    urllib.error.HTTPError,
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    http.client.HTTPException,
)


class TrueForgeError(Exception):
    """A fixture's evaluation could not be completed. Always surfaced as a
    FixtureResult.error, never silently treated as a negative prediction."""


class RetryableTurnError(TrueForgeError):
    """A turn that failed for a transport reason the provider SDK itself
    classifies as retryable - see _RETRYABLE_TURN_ERROR_MARKERS.

    Subclasses TrueForgeError deliberately: when the retry budget is spent
    this still reaches evaluate_fixture's existing `except TrueForgeError`
    and still becomes a FixtureResult.error excluded from both metrics. The
    subclass only decides whether one more attempt is worth making, never
    whether a failure counts."""


# TrueForge does not retry model calls: VercelAILLM.ts:939 hardcodes
# `maxRetries: 0` in its request builder, with no env knob (§7,
# 2026-08-30). So a connect-layer blip that the Vercel AI SDK has already
# classified as retryable still kills the whole turn, and the retry has to
# live here instead.
#
# `Cannot connect to API:` is that SDK's own marker, not TrueForge's:
# @ai-sdk/provider-utils' handleFetchError builds that exact prefix in both
# of its network-failure branches, and BOTH set `isRetryable: true`. No
# other branch of that function produces the prefix, so matching it maps
# one-to-one onto the SDK's own retryable classification rather than onto a
# guess of ours.
#
# Everything else stays unretried by construction: an auth failure, an
# invalid request, a rate limit and a provider-side model error all arrive
# with an HTTP status and a different message, and a `cancelled` turn is a
# deliberate stop, not a blip.
_RETRYABLE_TURN_ERROR_MARKERS = ("cannot connect to api:",)

# Three attempts total. Bounded on purpose and kept small: every attempt is
# a real, billed turn, so this trades a bounded amount of money for not
# losing a fixture to one dropped socket - it is not a way to push through
# a provider that is genuinely down.
MAX_TURN_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0


def _wrap_transport_error(exc: BaseException, context: str) -> TrueForgeError:
    if isinstance(exc, urllib.error.HTTPError):
        body_text = exc.read().decode("utf-8", "replace")[:500]
        return TrueForgeError(f"HTTP {exc.code} {context}: {body_text}")
    if isinstance(exc, urllib.error.URLError):
        return TrueForgeError(f"could not reach the server {context}: {exc.reason}")
    return TrueForgeError(f"transport error {context}: {exc!r}")


def trueforge_url() -> str:
    """Same call-time-resolution, strip-or-default pattern every other tool
    in this repo uses (`_smtp.py`'s `smtp_target()`, `correspondence_history
    ._mailpit_url()`) — a blank-but-set env var must fall back too, not be
    used as-is (the SMTP_HOST bug class, Qodo PR #29)."""
    return os.environ.get("TRUEFORGE_URL", "").strip() or DEFAULT_TRUEFORGE_URL


def gated_tool_names(agent_json_path: Path = AGENT_JSON_PATH) -> frozenset[str]:
    """Read directly from harness/agent.json's own require_approval_for_tools
    (T-034) rather than duplicating the four names here — so this harness
    cannot silently drift from the actual gate configuration it measures."""
    data = json.loads(agent_json_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for server in data["manifest"]["mcp_servers"]:
        for name in server.get("require_approval_for_tools", []):
            if isinstance(name, str) and name:
                names.add(name)
    if not names:
        raise ValueError(
            f"{agent_json_path} declares no require_approval_for_tools — "
            "nothing to measure a gate-trigger signal against"
        )
    return frozenset(names)


def agent_name(agent_json_path: Path = AGENT_JSON_PATH) -> str:
    data = json.loads(agent_json_path.read_text(encoding="utf-8"))
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{agent_json_path} has no top-level 'name'")
    return name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fixture:
    name: str  # filename, e.g. "sample-7.eml" or "00012.eml"
    label: str  # "phish" or "ham" — ground truth, from which directory it came from
    raw_email: str


def load_fixtures(fixtures_dir: Path = FIXTURES_DIR) -> list[Fixture]:
    """Deterministic order (sorted per label directory) so a re-run's
    fixture-to-result mapping is reproducible. Raises rather than silently
    returning a short list — a missing/empty fixture directory is a setup
    bug, not zero fixtures to evaluate."""
    fixtures: list[Fixture] = []
    for label in FIXTURE_LABELS:
        label_dir = fixtures_dir / label
        if not label_dir.is_dir():
            raise FileNotFoundError(f"missing fixture directory: {label_dir}")
        paths = sorted(label_dir.glob("*.eml"))
        if not paths:
            raise FileNotFoundError(f"no .eml fixtures found in {label_dir}")
        for path in paths:
            raw = path.read_text(encoding="utf-8", errors="replace")
            if not raw.strip():
                raise ValueError(f"empty fixture file: {path}")
            fixtures.append(Fixture(name=path.name, label=label, raw_email=raw))
    return fixtures


def write_temp_fixture(raw_email: str, fixtures_dir: Path = TOOLS_FIXTURES_DIR) -> str:
    """Writes raw_email into tools/fixtures/ under a fresh, collision-proof
    name so the real agent's mandatory parse_message(fixture) call has a
    real, exact filename to resolve - the fixture under test, never one of
    Slice 1's three unrelated hardcoded fixtures. Caller deletes it with
    delete_temp_fixture() once the turn finishes, success or failure."""
    name = f"eval-{uuid.uuid4().hex[:16]}.eml"
    (fixtures_dir / name).write_text(raw_email, encoding="utf-8")
    return name


def delete_temp_fixture(name: str, fixtures_dir: Path = TOOLS_FIXTURES_DIR) -> None:
    (fixtures_dir / name).unlink(missing_ok=True)


def _delete_temp_fixture_quietly(name: str | None) -> str | None:
    """Delete the temp fixture, returning a note instead of raising.

    Returns None when there was nothing to delete or the delete worked, and
    a short description otherwise. Callers report the note rather than
    letting it end the run - see evaluate_fixture's `finally`.
    """
    if name is None:
        return None
    try:
        delete_temp_fixture(name)
    except OSError as exc:
        return (
            f"temp fixture {name} left behind in tools/fixtures/ - "
            f"could not delete it ({type(exc).__name__}: {exc})"
        )
    return None


def fixture_turn_message(temp_fixture_name: str) -> str:
    """The turn's initial user message - tells the model the exact filename
    its own mandatory parse_message(fixture) call needs, matching that
    tool's documented contract (a bare name already present in
    tools/fixtures/) exactly."""
    return (
        "A suspicious email has been forwarded to you. It has been saved as "
        f"the fixture {temp_fixture_name!r}. Call parse_message with that "
        "exact filename to begin your analysis."
    )


# ---------------------------------------------------------------------------
# TrueForge client — raw wire stream only, never the (unmerged) translator
# ---------------------------------------------------------------------------


def _post_json(url: str, body: dict[str, Any], timeout: float) -> bytes:
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except _TRANSPORT_ERRORS as exc:
        raise _wrap_transport_error(exc, f"from {url}") from exc


def create_session(
    agent: str, *, base_url: str | None = None, timeout: float = TRUEFORGE_TIMEOUT_SECONDS
) -> str:
    """POST /api/v1/sessions — request and response shapes both verified
    against a live TrueForge 0.1.4 instance (2026-08-30); see the module
    docstring's WIRE SHAPES section for what was wrong before and how each
    was confirmed."""
    url = f"{(base_url or trueforge_url()).rstrip('/')}{API_PREFIX}/sessions"
    raw = _post_json(url, {"agent": {"name": agent}}, timeout)
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise TrueForgeError(f"non-JSON response creating a session: {raw[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise TrueForgeError(f"session response was not a JSON object: {payload!r}")
    # GetSessionResponse wraps the Session in `data`; the id is never at the
    # top level. Reading `payload["id"]` (as this did) meant every fixture
    # failed with "carried no usable id" against a real server.
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TrueForgeError(f"session response carried no data object: {payload!r}")
    session_id = data.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise TrueForgeError(f"session response carried no usable id: {payload!r}")
    return session_id


def _iter_sse_data_lines(response: Any) -> Iterator[str]:
    """Yields the payload of every `data:` line in an SSE stream. Lines
    that aren't `data:` (blank separators, `event:`, `id:`, SSE comments)
    are skipped, never raised on."""
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload:
            yield payload


# TrueForge does not expose an MCP tool to the model under its own name. It
# proxies every one through a wrapper whose model-level `function.name` is
# `call_tool`, carrying the real name in that call's JSON-encoded arguments:
#
#   {"name": "call_tool",
#    "arguments": "{\"mcp_server\": \"imports-mcp\",
#                   \"tool_name\": \"quarantine\",
#                   \"input\": {...}}"}
#
# Observed live on the first fixture whose gate actually fired (sample-11.eml,
# 2026-08-30): three gated calls - quarantine, create_block_rule and
# file_abuse_report - all arriving as `call_tool`. Reading `function.name`
# alone therefore resolved every one of them to "call_tool", which is not in
# the gated set, so `resolved_gated_tools` came back empty on a fixture where
# three gates had genuinely fired.
#
# `list_tools` and `get_tool_info` are the sibling proxy tools; neither ever
# carries a gated invocation, so only `call_tool` is unwrapped here.
_MCP_PROXY_TOOL_NAMES = frozenset({"call_tool"})


def _proxied_tool_name(arguments: Any) -> str | None:
    """The real MCP tool name inside a `call_tool` wrapper's arguments.

    `arguments` arrives as a JSON *string* on the wire (confirmed live); a
    dict is accepted too so a caller that already decoded it still works.
    Returns None rather than a guess whenever the arguments are missing,
    malformed, or carry no usable `tool_name` - an unresolved reference is
    reported as unresolved, never invented.
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    if not isinstance(arguments, dict):
        return None
    name = arguments.get("tool_name")
    if not isinstance(name, str) or not name.strip():
        return None
    return name


def _effective_tool_name(function: dict[str, Any]) -> str | None:
    """The tool actually being invoked: the proxied name when this is one of
    TrueForge's MCP wrappers, otherwise the model-level name as-is."""
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    if name in _MCP_PROXY_TOOL_NAMES:
        # A wrapper whose real target cannot be read is unresolved. Returning
        # the wrapper's own name would be worse than None: "call_tool" is not
        # a gated tool, so it would read as a confident non-gated answer.
        return _proxied_tool_name(function.get("arguments"))
    return name


# TrueForge's SSE stream opens an assistant turn with a `model.message` event
# that is only a HEADER - type, id, thread_id, created_at and nothing else:
#
#   // AgentThread.ts:1021 - "We start the delta stream with a model message event."
#   yield { type: EventType.MODEL_MESSAGE, thread_id, created_at, id: modelMessageEventId };
#
# The tool calls arrive afterwards as `model.message.delta` events, and the
# assembled message that carries `tool_calls` is built once the stream ends -
# it is persisted and returned by GET /events, but it is not what reaches this
# reader before `tool.approval_required` fires.
#
# Found on live fixtures #3 and #4 (2026-08-30): every gated call resolved to
# None even after the call_tool proxy was handled, because the correlation
# dict only ever held a header for that event id. Replaying the *persisted*
# events resolved correctly and hid the problem - a stored log is not the
# stream.
#
# The deltas do carry the real structured tool call (ExtendedChunkDeltaToolCall:
# index, id, function.name, function.arguments), fragmented across events, so
# the names come from accumulating those - never from prose, never from
# matching text.
def _accumulate_delta_tool_calls(
    accumulator: dict[str, dict[int, dict[str, Any]]], event: dict[str, Any]
) -> None:
    """Folds one `model.message.delta` into per-event, per-index tool calls.

    A delta's own `id` is the same modelMessageEventId the finished message
    carries, which is what `tool.approval_required.source_event_id` points at.
    `function.name` and `function.arguments` may each arrive whole or split
    across several deltas, so both are concatenated in arrival order.
    """
    event_id = event.get("id")
    deltas = event.get("tool_calls")
    if not isinstance(event_id, str) or not isinstance(deltas, list):
        return
    per_index = accumulator.setdefault(event_id, {})
    for delta in deltas:
        if not isinstance(delta, dict):
            continue
        index = delta.get("index")
        if not isinstance(index, int):
            continue
        entry = per_index.setdefault(index, {"id": None, "name": "", "arguments": ""})
        call_id = delta.get("id")
        if isinstance(call_id, str) and call_id:
            entry["id"] = call_id
        function = delta.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if isinstance(name, str):
            entry["name"] += name
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            entry["arguments"] += arguments


def _assembled_delta_tool_calls(
    per_index: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Re-shapes accumulated deltas into the same `tool_calls` shape a finished
    `model.message` carries, so one resolver handles both - including the
    call_tool proxy unwrap, unchanged."""
    calls: list[dict[str, Any]] = []
    for index in sorted(per_index):
        entry = per_index[index]
        if not entry["id"]:
            # Without an id this call cannot be matched to a ToolCallRef.
            # Dropped rather than guessed at.
            continue
        calls.append(
            {
                "id": entry["id"],
                "type": "function",
                "function": {"name": entry["name"], "arguments": entry["arguments"]},
            }
        )
    return calls


def _resolve_tool_name(
    model_message_tool_calls: dict[str, list[Any]], source_event_id: Any, tool_call_id: Any
) -> str | None:
    if not isinstance(source_event_id, str) or not isinstance(tool_call_id, str):
        return None
    calls = model_message_tool_calls.get(source_event_id)
    if not calls:
        return None
    for call in calls:
        if not isinstance(call, dict) or call.get("id") != tool_call_id:
            continue
        function = call.get("function")
        if isinstance(function, dict):
            return _effective_tool_name(function)
    return None


def _terminal_status(event: dict[str, Any]) -> str | None:
    """The `status` on a turn-finished event's own state, if it carried one.

    Returns None when the event has no state at all, which is how
    `mission.complete` (this project's Layer 2 event, never on the raw wire)
    and any future stateless terminal event stay readable rather than being
    treated as failures.
    """
    state = event.get("state")
    if not isinstance(state, dict):
        return None
    status = state.get("status")
    # A blank status is as unreadable as a missing one - it names no state in
    # the discriminated union, so it must not reach the "finished with status
    # ''" branch as though it were a real value.
    if not isinstance(status, str) or not status.strip():
        return None
    return status


def _is_retryable_turn_error(detail: str) -> bool:
    """True only for a failure message carrying the provider SDK's own
    retryable-transport marker. Substring match on a lowercased message: the
    marker is a fixed English prefix the SDK builds itself, and the variable
    part is the underlying cause, which was an empty string in the live
    failure that prompted this."""
    lowered = detail.lower()
    return any(marker in lowered for marker in _RETRYABLE_TURN_ERROR_MARKERS)


def _raise_if_turn_failed(event: dict[str, Any], event_type: str, session_id: str) -> str | None:
    """Raises unless the turn genuinely completed. Returns the status seen.

    A turn that errored or was cancelled produced no verdict and proposed no
    action - it is a failed evaluation, to be excluded from the metrics via
    FixtureResult.error, never a "no gated action proposed" negative.

    An event type that is documented as stateless (`mission.complete`) is
    accepted as a completion with no status. Anything else - i.e. `turn.done` -
    must carry a readable `state.status`, because that discriminator is the
    only thing separating a completed turn from a crashed one. A missing or
    malformed one is a failed fixture, not a negative.
    """
    if event_type in _STATELESS_TERMINAL_EVENT_TYPES:
        return None
    status = _terminal_status(event)
    if status is None:
        raise TrueForgeError(
            f"turn-finished event {event_type!r} for session {session_id} carried no readable "
            "state.status - the turn's outcome is unknown, so this fixture could not be scored"
        )
    if status == _TURN_SUCCEEDED_STATUS:
        return status
    state = event.get("state")
    detail = ""
    if isinstance(state, dict):
        # TurnStateError carries `message`, TurnStateCancelled carries `reason`.
        for key in ("message", "reason"):
            value = state.get(key)
            if isinstance(value, str) and value.strip():
                detail = f": {value.strip()}"
                break
    summary = (
        f"turn for session {session_id} finished with status {status!r}{detail} - "
        "the turn never reached a verdict, so this fixture could not be scored"
    )
    # Only an *errored* turn can be transient. A cancelled turn was stopped
    # deliberately by somebody, and re-submitting it would be re-spending
    # money to override a decision.
    if status == _TURN_ERROR_STATUS and _is_retryable_turn_error(detail):
        raise RetryableTurnError(summary)
    raise TrueForgeError(summary)


@dataclass
class TurnObservation:
    gate_fired: bool = False
    """True the instant a tool.approval_required event is seen at all -
    TrueForge cannot emit that event type for a non-gated tool (agent.json's
    require_approval_for_tools is what makes a tool gated in the first
    place), so this alone is already the positive/negative signal."""
    resolved_gated_tools: list[str] = field(default_factory=list)
    """Best-effort diagnostic detail only - which of the four names actually
    resolved. Can be shorter than the true count of proposed gated calls if
    a ToolCallRef's source_event_id was never seen (see module docstring);
    gate_fired is the correctness boundary, this list is not."""
    completed_without_gate: bool = False
    raw_event_types_seen: list[str] = field(default_factory=list)
    terminal_status: str | None = None
    """The turn-finished event's own state.status, when it carried one -
    diagnostic only. A non-"done" status never reaches here as an
    observation: it raises instead (see _turn_finished_or_raise)."""


def run_turn_and_observe(
    session_id: str,
    message: str,
    gated_tools: frozenset[str],
    *,
    base_url: str | None = None,
    timeout: float = TRUEFORGE_TIMEOUT_SECONDS,
) -> TurnObservation:
    """Submits one turn, watches its SSE stream for tool.approval_required,
    and stops reading the instant it fires — see the module docstring's
    SAFETY section for why this never resumes a paused gate."""
    url = f"{(base_url or trueforge_url()).rstrip('/')}{API_PREFIX}/sessions/{session_id}/turns"
    # `input` is an array of TurnInputItem, not one item. A bare object is
    # rejected before the turn runs: 400 "expected array, received object".
    request_body = {
        "input": [{"type": "user.message", "content": message}],
        "stream": True,
    }
    data = json.dumps(request_body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    observation = TurnObservation()
    model_message_tool_calls: dict[str, list[Any]] = {}
    delta_tool_calls: dict[str, dict[int, dict[str, Any]]] = {}

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for payload in _iter_sse_data_lines(response):
                try:
                    event = json.loads(payload)
                except ValueError:
                    continue  # one malformed frame must not abort the rest of the stream
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if not isinstance(event_type, str):
                    continue
                observation.raw_event_types_seen.append(event_type)

                if event_type == "model.message":
                    event_id = event.get("id")
                    tool_calls = event.get("tool_calls")
                    # Only a populated list is worth recording. The event that
                    # OPENS an assistant turn carries no tool_calls at all, and
                    # an empty list would overwrite deltas already accumulated
                    # under the same id with nothing.
                    if isinstance(event_id, str) and isinstance(tool_calls, list) and tool_calls:
                        model_message_tool_calls[event_id] = tool_calls
                    continue

                if event_type == "model.message.delta":
                    _accumulate_delta_tool_calls(delta_tool_calls, event)
                    continue

                if event_type == "tool.approval_required":
                    observation.gate_fired = True
                    # A finished model.message wins when one arrived; otherwise
                    # fall back to what the deltas accumulated for that same
                    # event id. On the live stream it is always the latter.
                    correlation = dict(model_message_tool_calls)
                    for event_id, per_index in delta_tool_calls.items():
                        if event_id not in correlation:
                            assembled = _assembled_delta_tool_calls(per_index)
                            if assembled:
                                correlation[event_id] = assembled
                    refs = event.get("tool_calls")
                    if isinstance(refs, list):
                        for ref in refs:
                            if not isinstance(ref, dict):
                                continue
                            resolved = _resolve_tool_name(
                                correlation,
                                ref.get("source_event_id"),
                                ref.get("id"),
                            )
                            if resolved is not None and resolved in gated_tools:
                                observation.resolved_gated_tools.append(resolved)
                    return observation  # answer found - never resume, stop reading

                if event_type in _TURN_FINISHED_EVENT_TYPES:
                    # Raises for an errored/cancelled turn rather than
                    # returning it as a clean negative.
                    observation.terminal_status = _raise_if_turn_failed(
                        event, event_type, session_id
                    )
                    observation.completed_without_gate = True
                    return observation
    except _TRANSPORT_ERRORS as exc:
        raise _wrap_transport_error(exc, "submitting a turn") from exc

    # The stream ended (EOF) without ever reaching tool.approval_required or
    # a recognized turn-finished event - the turn's outcome is genuinely
    # unknown, not a negative (Qodo, PR #76, "Truncated streams become
    # negatives": the prior default-False TurnObservation returned here was
    # indistinguishable from a real, completed negative). A dropped or
    # empty stream must be a scoring failure, excluded from metrics, never
    # silently counted as "no gated action proposed."
    raise TrueForgeError(
        f"SSE stream for session {session_id} ended without a "
        f"tool.approval_required or turn-finished event "
        f"(event types seen: {observation.raw_event_types_seen})"
    )


# ---------------------------------------------------------------------------
# Per-fixture evaluation
# ---------------------------------------------------------------------------


@dataclass
class FixtureResult:
    fixture_name: str
    label: str  # "phish" or "ham" - ground truth
    predicted_positive: bool | None  # None means evaluation failed, never coerced to False
    resolved_gated_tools: list[str] = field(default_factory=list)
    error: str | None = None
    attempts: int = 1
    """How many turns this fixture actually submitted, and therefore what it
    cost. >1 means a transient transport failure was retried; 0 means it
    failed before any turn was posted (a local write error, or a session that
    could not be created) and so was never billed. Reported so a run's real
    spend and its blip rate are both visible, never folded into the metrics."""


def evaluate_fixture(
    fixture: Fixture,
    *,
    agent: str,
    gated_tools: frozenset[str],
    base_url: str | None = None,
    timeout: float = TRUEFORGE_TIMEOUT_SECONDS,
    max_attempts: int = MAX_TURN_ATTEMPTS,
    retry_backoff_seconds: float = RETRY_BACKOFF_SECONDS,
) -> FixtureResult:
    """One fresh session per attempt (EVENT ISOLATION): no state from a
    previous fixture's turn - including this module's own per-turn
    model.message correlation dict - can leak into this one, since
    run_turn_and_observe's dict is a fresh local every call. That is also
    what makes the retry below safe to score: a retried attempt is read
    from its own session's stream, so no event can be counted twice and no
    earlier attempt's tool calls can be mistaken for this one's.

    Writes the fixture into tools/fixtures/ under a temporary name so the
    real agent's mandatory parse_message(fixture) call can actually resolve
    it (Qodo, PR #76, "Eval emails cannot be parsed") - deleted again in a
    `finally`, success or failure, never left behind. The temp file is
    written once and reused across attempts; only the session and the turn
    are new each time.

    RETRY - bounded, and only for a transport failure the provider SDK
    itself calls retryable (RetryableTurnError). Two things make this safe
    to do at all: such a failure arrives *on a turn.done*, so the previous
    turn is known terminal and cannot still be running up a bill in the
    background; and a gate that already fired returns before any turn.done
    is read, so a retry can never retract a licence request the operator
    has already seen. Every other failure - auth, invalid request, rate
    limit, provider error, a cancelled turn, a dropped stream, a transport
    error talking to TrueForge itself - is NOT retried: a dropped stream in
    particular may leave a turn still running server-side, and re-submitting
    would double-spend."""
    if max_attempts < 1:
        # A caller that configured no attempts must not be charged for one
        # (Qodo, PR #99, "Nonpositive retry budget ignored"). Rejected before
        # the temp fixture is written, let alone before a session is opened.
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
    temp_fixture_name: str | None = None
    # Turns actually submitted, which is what a turn costs money for. Counted
    # only once a session exists and a turn is about to be posted, so a failed
    # session POST or a local filesystem error reports zero spend rather than a
    # phantom billed turn (Qodo, PR #99, findings 2 and 3).
    attempts = 0
    try:
        temp_fixture_name = write_temp_fixture(fixture.raw_email)
        message = fixture_turn_message(temp_fixture_name)
        while True:
            try:
                # create_session only POSTs /sessions - no turn, no model call,
                # so it is deliberately outside the counter.
                session_id = create_session(agent, base_url=base_url, timeout=timeout)
                attempts += 1
                observation = run_turn_and_observe(
                    session_id, message, gated_tools, base_url=base_url, timeout=timeout
                )
            except RetryableTurnError as exc:
                if attempts >= max_attempts:
                    result = FixtureResult(
                        fixture_name=fixture.name,
                        label=fixture.label,
                        predicted_positive=None,
                        error=f"{exc} (gave up after {attempts} attempts)",
                        attempts=attempts,
                    )
                    break
                if retry_backoff_seconds > 0:
                    time.sleep(retry_backoff_seconds)
                continue
            result = FixtureResult(
                fixture_name=fixture.name,
                label=fixture.label,
                predicted_positive=observation.gate_fired,
                resolved_gated_tools=observation.resolved_gated_tools,
                attempts=attempts,
            )
            break
    except (TrueForgeError, OSError) as exc:
        result = FixtureResult(
            fixture_name=fixture.name,
            label=fixture.label,
            predicted_positive=None,
            error=str(exc),
            # Never floored to 1: a failure before any turn was submitted
            # genuinely cost zero turns.
            attempts=attempts,
        )
    finally:
        # Cleanup runs whatever happened, but it must never become the
        # reason a 40-fixture run stops: unlink() can raise (a locked file
        # on Windows, a read-only directory), and letting that escape from
        # `finally` would discard a turn that already succeeded and abort
        # every fixture after it (Qodo, PR #76, finding 4).
        cleanup_note = _delete_temp_fixture_quietly(temp_fixture_name)

    if cleanup_note is not None:
        # Recorded, never swallowed - the file is still sitting in
        # tools/fixtures/ and somebody has to know to remove it.
        result.error = f"{result.error}; {cleanup_note}" if result.error else cleanup_note
    return result


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class Report:
    gate_trigger_accuracy: float | None
    false_positive_rate: float | None
    total_fixtures: int
    total_scored: int
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    failed: list[FixtureResult]


def score(results: Iterable[FixtureResult]) -> Report:
    """gate_trigger_accuracy = (TP+TN) / total_scored.
    false_positive_rate = FP / total_ham_scored.
    Both None (not 0.0 - a real division-by-zero would silently lie) if
    there is nothing to divide by. `failed` fixtures (predicted_positive is
    None) are excluded from both, never folded into a negative."""
    results = list(results)
    scored = [r for r in results if r.predicted_positive is not None]
    failed = [r for r in results if r.predicted_positive is None]

    tp = sum(1 for r in scored if r.label == "phish" and r.predicted_positive)
    fn = sum(1 for r in scored if r.label == "phish" and not r.predicted_positive)
    tn = sum(1 for r in scored if r.label == "ham" and not r.predicted_positive)
    fp = sum(1 for r in scored if r.label == "ham" and r.predicted_positive)

    accuracy = (tp + tn) / len(scored) if scored else None
    total_ham_scored = tn + fp
    fpr = fp / total_ham_scored if total_ham_scored else None

    return Report(
        gate_trigger_accuracy=accuracy,
        false_positive_rate=fpr,
        total_fixtures=len(results),
        total_scored=len(scored),
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        failed=failed,
    )
