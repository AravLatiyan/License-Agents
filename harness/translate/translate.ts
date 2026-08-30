// harness/translate/translate.ts
//
// T-037: a pure, stateful translator from TrueForge's turn-stream events to
// this app's mission.* events. As contracts/events.ts explains at length,
// TrueForge's stream is a closed 12-type union with no extension point for
// an agent to emit mission.* itself - something on our side has to do the
// translation, and this is that something.
//
// "Stateful" because the wire stream splits one logical action across two
// events: `model.message` publishes a tool call's name and arguments,
// `tool.approval_required` and `tool.response` only reference it by id
// (contracts/events.ts's ToolCallRef / ModelMessageToolCall comments cover
// why). A translator has to remember the model.message side until the
// matching approval/response event arrives, so createTranslator returns a
// closure holding that memory rather than a stateless function.
//
// "Never throws" because this sits directly on an SSE stream: one malformed
// or unexpected event must not take down the whole mission. Every lookup
// into a `raw: unknown` value is guarded rather than asserted, mirroring the
// isRecord/isStr/isArr guards in cockpit/src/missionSource.ts - the two
// files check the same wire shapes for different reasons (that one rejects
// bad *mission* events before they reach the UI, this one accepts bad
// *TrueForge* events without ever asserting they're well-formed).

import type {
  ActionExecutedEvent,
  ApprovalRequiredEvent,
  CorrespondenceHistory,
  DetonationResult,
  DomainIntel,
  MissionEvent,
  MissionFailedEvent,
  ParsedMessage,
  ProposedActionName,
  ToolApprovalRequiredEvent,
  TurnCancelledReason,
  UrlReputation,
} from "../../contracts/events";

export interface TranslatorOptions {
  missionId: string;
}

export interface Translator {
  /** Feed one raw TrueForge stream event; get zero or more MissionEvents back. */
  push(raw: unknown): MissionEvent[];
  /**
   * Tell the translator gate `gateIndex` has been resolved, so the next
   * queued gate (if any) can be released. Returns that gate's
   * `mission.approval_required` event, or `[]` if none is queued.
   *
   * The turn stream has no wire event for "approval resolved" (the 12-type
   * closed union has nothing between tool.approval_required and the next
   * turn.done) - a human's decision is a locally-constructed
   * mission.approval_resolved plus an outbound POST of user.tool_approval,
   * neither of which push() ever observes. The caller that already knows a
   * gate resolved (because it just made that POST) is the only thing that
   * can tell the translator to move on, so it must call this - the
   * sequential-gate guarantee lives at this call site, not inside push().
   * A `gateIndex` that doesn't match the currently outstanding gate (stale
   * or already-resolved) is a no-op, not an error.
   */
  resolveGate(gateIndex: 1 | 2 | 3 | 4): MissionEvent[];
}

// --- small structural guards, no validation library - kept dependency-free,
// same approach as cockpit/src/missionSource.ts ---

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
const isStr = (v: unknown): v is string => typeof v === "string";
const isStrOrNull = (v: unknown): v is string | null => v === null || typeof v === "string";
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const isNum = (v: unknown): v is number => typeof v === "number";
const isArr = (v: unknown): v is unknown[] => Array.isArray(v);
const isArrOf = (v: unknown, elem: (x: unknown) => boolean): boolean => isArr(v) && v.every(elem);

// --- tool-result shape guards (Qodo, PR #73: "malformed results become
// mission events"). handleToolResponse only proved `content` parses as
// JSON before this fix, then cast the parsed value straight to its typed
// payload - any tool bug or hostile MCP response that still parsed as JSON
// (e.g. `{}`, or a differently-shaped object) would silently become a
// fully-typed mission.evidence/mission.detonation/mission.message_received
// event, which downstream Cockpit code trusts as already-validated
// (missionSource.ts's own checkers exist for exactly this reason, on the
// mission.* side of the wire; these mirror the same field shapes from
// contracts/events.ts on the tool-result side). Never throws, matching this
// file's own contract - an invalid shape is dropped exactly like an
// unparseable result already is, not reported as a mission.failed, since one
// bad tool result should not fail the whole mission (§13: missing/malformed
// evidence is "not determined", not an error). ---

const isUrlEntry = (v: unknown): boolean => isRecord(v) && isStr(v.href) && isStr(v.anchor_text);
const isAttachmentEntry = (v: unknown): boolean => isRecord(v) && isStr(v.filename) && isStr(v.sha256);
const isRedirectHop = (v: unknown): boolean => isRecord(v) && isStr(v.url) && isNum(v.status);

function isParsedMessage(v: unknown): v is ParsedMessage {
  return (
    isRecord(v) &&
    isStr(v.message_id) &&
    isStr(v.from) &&
    isStrOrNull(v.reply_to) &&
    isStrOrNull(v.return_path) &&
    isStrOrNull(v.display_name) &&
    isStr(v.authentication_results) &&
    isArrOf(v.received_chain, isStr) &&
    isArrOf(v.urls, isUrlEntry) &&
    isArrOf(v.attachments, isAttachmentEntry)
  );
}

const isDomainIntel = (v: unknown): v is DomainIntel =>
  isRecord(v) &&
  isStr(v.domain) &&
  isStrOrNull(v.registration_date) &&
  isStrOrNull(v.registrar) &&
  isStrOrNull(v.abuse_contact) &&
  isStrOrNull(v.cert_issued_at);

const isUrlReputation = (v: unknown): v is UrlReputation =>
  isRecord(v) && isStr(v.url) && isBool(v.listed) && isArrOf(v.tags, isStr);

const isCorrespondenceHistory = (v: unknown): v is CorrespondenceHistory =>
  isRecord(v) &&
  isStr(v.address) &&
  isStr(v.domain) &&
  isNum(v.prior_contact_count) &&
  isStrOrNull(v.first_seen) &&
  isStrOrNull(v.last_seen) &&
  isArrOf(v.domains_used, isStr);

/** Mirrors DetonationForm's two-branch union: action_invalid true pairs with
 *  null action_origin/cross_domain, false-or-absent pairs with real values. */
function isDetonationForm(v: unknown): boolean {
  if (!isRecord(v) || !isStr(v.action) || !isStr(v.method) || !isBool(v.asks_password)) return false;
  if (v.action_invalid === true) return v.action_origin === null && v.cross_domain === null;
  if (v.action_invalid !== undefined && v.action_invalid !== false) return false;
  return isStr(v.action_origin) && isBool(v.cross_domain);
}

/** Mirrors DetonationResult's two-branch union exactly - error branch has no
 *  final_url/forms/summary, success branch has no error. */
function isDetonationResult(v: unknown): v is DetonationResult {
  if (!isRecord(v) || !isStr(v.url) || !isArrOf(v.redirect_chain, isRedirectHop)) return false;
  const hasError = "error" in v;
  const hasSuccess = "summary" in v;
  if (hasError === hasSuccess) return false; // must have exactly one
  if (hasError) return isStr(v.error);
  return (
    isStr(v.final_url) &&
    isArrOf(v.forms, isDetonationForm) &&
    isStr(v.summary) &&
    (v.screenshot_id === undefined || isStr(v.screenshot_id))
  );
}

/** The four tool names that carry a licence gate (contracts/events.ts
 *  ProposedActionName). A plain function rather than a typed Set: Set<T>.has
 *  requires its argument to already be T, which is exactly what we don't
 *  have yet for a value pulled out of `unknown`. */
function isGatedActionName(name: string): name is ProposedActionName {
  return (
    name === "quarantine" ||
    name === "notify_impersonated" ||
    name === "create_block_rule" ||
    name === "file_abuse_report"
  );
}

/**
 * How much of a gated tool's unreadable reply is quoted back to the operator
 * (T-074). Long enough to carry a real validation message ("message_ids must
 * be a non-empty list"), short enough that a buggy or hostile server cannot
 * push a wall of text into a licence-gate panel. The ~2KB tool-response cap is
 * a rule our own tools follow; nothing on the wire enforces it for us.
 */
const MAX_QUOTED_FAILURE_CHARS = 200;

/**
 * The `result_summary` for a gated action whose reply could not be read as a
 * result (T-074). Its job is to make the failure unmistakable in prose,
 * because the cockpit renders this text after the fixed words "Executed: "
 * (cockpit/src/ApprovalPanel.tsx:165, cockpit/src/missionPlan.ts:352) - a
 * render this file cannot change and should not need to. Leading with
 * UNCONFIRMED means a human reads "Executed: UNCONFIRMED - ..." rather than
 * mistaking an unreadable reply for a completed irreversible action.
 *
 * NOT "FAILED" (Qodo, PR #96): an unreadable reply can follow a side effect
 * that really happened, so calling it a failure would be a claim we cannot
 * support - and these actions are not idempotent. An operator told
 * "notify_impersonated FAILED" may well send the notification a second time,
 * to a real person, which is a worse outcome than the frozen panel this
 * whole change exists to fix. The wording therefore states exactly what is
 * known - the reply could not be read - says the outcome is unknown in both
 * directions, and quotes the reply so the operator can judge it themselves.
 */
function describeUnreadableResult(action: ProposedActionName, content: string): string {
  const trimmed = content.trim();
  if (trimmed === "") {
    return (
      `UNCONFIRMED - ${action} returned an empty reply. It may or may not have run; ` +
      `check before retrying, because this action is not safe to repeat blindly.`
    );
  }
  const quoted =
    trimmed.length > MAX_QUOTED_FAILURE_CHARS ? `${trimmed.slice(0, MAX_QUOTED_FAILURE_CHARS)}…` : trimmed;
  return (
    `UNCONFIRMED - ${action} returned no readable result. It may or may not have run; ` +
    `check before retrying, because this action is not safe to repeat blindly. ` +
    `The tool replied: ${quoted}`
  );
}

/** Exactly TrueForge's TurnStateCancelledReason enum (contracts/events.ts). */
function isTurnCancelledReason(v: unknown): v is TurnCancelledReason {
  return (
    v === "server-execution-timeout" ||
    v === "client-cancelled" ||
    v === "cancelled-for-next-turn" ||
    v === "abandoned"
  );
}

/** What we remember from a `model.message` tool call until the matching
 *  approval/response event arrives. `argumentsJson` is kept as the raw
 *  string - TrueForge passes the model's function-call arguments through
 *  verbatim, so parsing is deferred to the point where each argument is
 *  actually needed (and can fail defensively there, see ModelMessageToolCall
 *  in contracts/events.ts). */
interface PendingCall {
  name: string;
  argumentsJson: string;
  /** Id of the `model.message` event that requested this call. A
   *  `ToolCallRef` names both `id` and `source_event_id`, and resolution must
   *  match BOTH: tool-call ids are only unique within the message that issued
   *  them, so joining on `id` alone lets a stale or reused id from an earlier
   *  message supply the name and arguments for this gate. That would show a
   *  human one action while approving another — the exact failure this whole
   *  licence mechanism exists to prevent (Qodo, PRs #73/#74). */
  sourceEventId: string;
}

/** Pull the spoken text out of a turn.done `output`. `output.content` may be
 *  a plain string, an array of parts (only `{type:"text", text}` parts are
 *  read - other part types carry no text to speak), or absent/null. */
function extractOutputText(output: unknown): string {
  if (!isRecord(output)) return "";
  const content = output.content;
  if (isStr(content)) return content;
  if (isArr(content)) {
    const parts: string[] = [];
    for (const part of content) {
      if (isRecord(part) && part.type === "text" && isStr(part.text)) {
        parts.push(part.text);
      }
    }
    return parts.join("");
  }
  return "";
}

export function createTranslator(options: TranslatorOptions): Translator {
  const missionId = options.missionId;

  // Recorded from model.message, keyed by ModelMessageToolCall.id. Consumed
  // by both tool.approval_required (to resolve name+arguments) and
  // tool.response (to resolve which tool produced a result).
  const pendingCalls = new Map<string, PendingCall>();

  // Recorded from tool.approval_required, keyed by the same tool_call id, so
  // that when the matching tool.response later arrives we know which of the
  // four licence gates its result belongs to.
  const gateIndexByToolCallId = new Map<string, 1 | 2 | 3 | 4>();

  // Number of gates assigned so far (emitted or still queued). Gate indices
  // are assigned in arrival order starting at 1, per contracts/events.ts's
  // ApprovalRequiredEvent doc comment ("a translator assigns them by arrival
  // order") - assignment happens the moment a call qualifies, before it's
  // known whether the gate can be emitted immediately or has to queue.
  let gatesAssigned = 0;

  // At most one gate is ever "outstanding" (emitted, not yet resolved) at a
  // time - this is what actually enforces §6/CLAUDE.md's sequential-gate
  // requirement when a single tool.approval_required carries several calls,
  // or when more arrive while one is still pending. Anything assigned while
  // a gate is already outstanding goes into the queue instead of `out`, and
  // is only released by resolveGate().
  let activeGateIndex: 1 | 2 | 3 | 4 | null = null;
  const pendingGateQueue: ApprovalRequiredEvent[] = [];

  function handleModelMessage(raw: Record<string, unknown>): MissionEvent[] {
    const toolCalls = raw.tool_calls;
    if (!isArr(toolCalls)) return [];
    // The event's own id is what a later ToolCallRef.source_event_id points
    // back to, so it has to be remembered alongside each call.
    const sourceEventId = raw.id;
    if (!isStr(sourceEventId)) return [];
    for (const call of toolCalls) {
      if (!isRecord(call)) continue;
      const id = call.id;
      const fn = call.function;
      if (!isStr(id) || !isRecord(fn)) continue;
      const name = fn.name;
      const args = fn.arguments;
      if (!isStr(name) || !isStr(args)) continue;
      pendingCalls.set(id, { name, argumentsJson: args, sourceEventId });
    }
    // model.message never itself becomes a mission event - it only feeds the
    // pendingCalls memory that tool.approval_required/tool.response read.
    return [];
  }

  // SEQUENTIAL GATES (Qodo, PR #73/#74). If one tool.approval_required
  // carries several tool calls, only the first qualifying one is emitted
  // here - the rest are assigned an index (so ordering is still arrival
  // order) but queued, and only released one at a time via resolveGate(),
  // below. This is the actual enforcement of §6/CLAUDE.md's "four sequential
  // per-tool-call gates, not one modal with four checkboxes"; see
  // resolveGate()'s own doc comment for why the release signal has to come
  // from the caller rather than from anything push() itself observes.
  function handleApprovalRequired(raw: Record<string, unknown>): MissionEvent[] {
    const toolCalls = raw.tool_calls;
    if (!isArr(toolCalls)) return [];
    // ToolApprovalRequiredEvent requires id/created_at/thread_id
    // (contracts/events.ts) - `raw` is cast verbatim into the emitted
    // event's `approval` field below, so a missing one here would produce a
    // MissionEvent that cockpit/src/missionSource.ts's checkToolApprovalRequired
    // rejects at runtime (Qodo, PR #75 finding #1). Caught before any gate is
    // built, same "no gate is better than a malformed one" posture as the
    // source_event_id check below.
    if (!isStr(raw.id) || !isStr(raw.created_at) || !isStr(raw.thread_id)) return [];
    const out: MissionEvent[] = [];

    for (const call of toolCalls) {
      // ToolCallRef is {id, source_event_id} only (T-037 correction) - no
      // name or arguments here. Resolve both from the model.message that
      // requested this call, recorded earlier under the same id.
      if (!isRecord(call) || !isStr(call.id) || !isStr(call.source_event_id)) continue;
      const toolCallId = call.id;
      const pending = pendingCalls.get(toolCallId);
      if (!pending) continue; // no matching model.message seen - can't resolve, so can't gate it
      if (pending.sourceEventId !== call.source_event_id) {
        // The ref points at a different model.message than the one this id
        // was recorded from. Resolving anyway would let a stale or reused
        // tool-call id put the wrong tool name and arguments in front of the
        // human granting the licence. Fail closed: no gate is better than a
        // mislabelled one (Qodo, PRs #73/#74).
        continue;
      }

      const name = pending.name;
      if (!isGatedActionName(name)) continue; // only the four gated actions become a licence gate; everything else is skipped

      if (gatesAssigned >= 4) {
        // ApprovalRequiredEvent.gate_index is typed 1|2|3|4 (contracts/events.ts)
        // precisely because the cockpit's four-gate design (§10/§17) has no
        // slot for a fifth. A 5th simultaneous gate can't be represented
        // without lying about which of the four panels it belongs to, so it
        // is dropped rather than mis-numbered.
        continue;
      }

      let args: Record<string, unknown> = {};
      try {
        const parsed: unknown = JSON.parse(pending.argumentsJson);
        if (isRecord(parsed)) args = parsed;
      } catch {
        args = {}; // malformed model output - a licence gate with unreadable arguments is still shown, just with none listed
      }

      gatesAssigned += 1;
      const gateIndex = gatesAssigned as 1 | 2 | 3 | 4;
      gateIndexByToolCallId.set(toolCallId, gateIndex);

      const event: ApprovalRequiredEvent = {
        type: "mission.approval_required",
        mission_id: missionId,
        gate_index: gateIndex,
        gate_count: 4,
        action: { action: name, arguments: args },
        // This gate's OWN call, not approval.tool_calls[0] - one wire event
        // can carry several calls, and taking the first would let gate 2
        // resume gate 1's action (Qodo, PR #85).
        tool_call_id: toolCallId,
        // Kept verbatim for provenance (contracts/events.ts's `approval`
        // field doc). This is the same raw event we already read tool_calls
        // out of above, cast back to its wire type rather than re-validated -
        // this translator's job is to move data, not to police TrueForge's
        // own schema a second time.
        approval: raw as unknown as ToolApprovalRequiredEvent,
      };

      if (activeGateIndex === null) {
        activeGateIndex = gateIndex;
        out.push(event);
      } else {
        pendingGateQueue.push(event);
      }
    }

    return out;
  }

  /**
   * Release every gate still waiting behind the active one.
   *
   * `resolveGate` is otherwise the queue's only drain, and it is driven by a
   * consumer reacting to a human decision. Once a turn reaches a terminal
   * state no further decision is coming, so anything left queued would be
   * silently dropped and the cockpit would show FEWER licence gates than the
   * agent actually requested. That is the worse failure: a missing LICENCE
   * REQUIRED panel reads as an action nobody was asked to approve, which is
   * precisely what this project exists to make visible. Releasing them late
   * is honest; dropping them is not (O1 review of PR #73).
   *
   * Deliberately NOT called when a turn ends *paused* — a pause is the
   * harness waiting on exactly these gates, so the queue is still live.
   */
  function flushQueuedGates(): MissionEvent[] {
    activeGateIndex = null;
    if (pendingGateQueue.length === 0) return [];
    return pendingGateQueue.splice(0, pendingGateQueue.length);
  }

  function resolveGate(gateIndex: 1 | 2 | 3 | 4): MissionEvent[] {
    if (activeGateIndex !== gateIndex) return []; // stale or already-resolved - nothing to release
    activeGateIndex = null;
    const next = pendingGateQueue.shift();
    if (!next) return [];
    activeGateIndex = next.gate_index;
    return [next];
  }

  function handleToolResponse(raw: Record<string, unknown>): MissionEvent[] {
    const toolCallId = raw.tool_call_id;
    const content = raw.content;
    if (!isStr(toolCallId) || !isStr(content)) return [];

    const pending = pendingCalls.get(toolCallId);
    if (!pending) return []; // no matching model.message seen - can't tell which tool this result is from

    let parsed: unknown;
    let parsedOk = true;
    try {
      parsed = JSON.parse(content);
    } catch {
      parsedOk = false;
    }

    const name = pending.name;

    // GATED ACTIONS ARE DECIDED BEFORE THE PARSE RESULT IS CONSULTED (T-074).
    //
    // For every other tool here an unreadable reply means "drop it": nothing
    // is waiting on it, and §13 says missing evidence is "not determined",
    // not an error. A gated action is the opposite case. A human has already
    // granted the licence, and the cockpit's gate stays on "Allowed -
    // executing..." until a mission.action_executed carrying its gate index
    // arrives (cockpit/src/ApprovalPanel.tsx:161, missionPlan.ts:354).
    // Nothing else ever clears it - mission.approval_resolved is already
    // past, and a tool error does not end the turn - so returning [] here
    // left the operator watching a spinner for an action that had already
    // failed.
    //
    // That is not hypothetical: three of the four gated wrappers in
    // tools/imports_mcp/server.py validate their arguments by raising
    // ToolError (quarantine :292-301, notify_impersonated :319-330,
    // file_abuse_report :351-358), and that raise happens after the gate, so
    // the licence is spent and the tool still did not run. An error message
    // is not a JSON document, so it fails the parse above - which is exactly
    // why this branch sits before the parse check rather than after it.
    // (create_block_rule never raises; create_block_rule.py's own _failure()
    // gives this same reason for why it returns a note instead.)
    if (isGatedActionName(name)) {
      const gateIndex = gateIndexByToolCallId.get(toolCallId);
      // A result for a call that never became a licence gate: no gate to
      // attach an outcome to, and no stuck panel to clear. Unchanged from
      // before - inventing a gate index would put an outcome on a gate the
      // human was never shown.
      if (gateIndex === undefined) return [];
      // `note` is the one field all four gated tools publish across success
      // and failure alike (quarantine.py / notify_impersonated.py /
      // file_abuse_report.py / create_block_rule.py; their own status field's
      // *name* differs - quarantined vs sent - so note is the one thing safe
      // to require without hard-coding a per-tool union here). Its absence no
      // longer means silence, but it still never means success: the summary
      // says so in words, so a malformed or hostile payload cannot read as a
      // completed action (the standing requirement from Qodo, PR #75
      // finding #2, now met by saying UNCONFIRMED instead of by saying nothing).
      const note = parsedOk && isRecord(parsed) && isStr(parsed.note) ? parsed.note : null;
      const event: ActionExecutedEvent = {
        type: "mission.action_executed",
        mission_id: missionId,
        gate_index: gateIndex,
        action: name,
        result_summary: note ?? describeUnreadableResult(name, content),
      };
      return [event];
    }

    if (!parsedOk) return []; // unreadable result - nothing safe to attach it to

    switch (name) {
      case "parse_message":
        if (!isParsedMessage(parsed)) return []; // malformed result - not a well-formed mission event either
        return [{ type: "mission.message_received", mission_id: missionId, message: parsed }];

      case "domain_intel":
        // Validated against domain_intel's own shape, not "either
        // infrastructure-lane shape" - a url_reputation-shaped result
        // reaching this branch is exactly as wrong as any other malformed
        // payload, and the pre-fix grouped check would have accepted it
        // (Qodo, PR #75 finding #3).
        if (!isDomainIntel(parsed)) return [];
        return [{ type: "mission.evidence", mission_id: missionId, lane: "infrastructure", evidence: parsed }];

      case "url_reputation":
        if (!isUrlReputation(parsed)) return [];
        return [{ type: "mission.evidence", mission_id: missionId, lane: "infrastructure", evidence: parsed }];

      case "correspondence_history":
        if (!isCorrespondenceHistory(parsed)) return [];
        return [
          {
            type: "mission.evidence",
            mission_id: missionId,
            lane: "history",
            evidence: parsed,
          },
        ];

      // NOTE: there is deliberately no "identity" lane case here. §10's
      // IDENTITY lane has no producer - no tool emits lookalike_domain /
      // lookalike_of (contracts/events.ts's IdentityEvidence doc, PLAN.md §6
      // 2026-08-30). Emitting mission.evidence with lane:"identity" and a
      // fabricated `lookalike_domain: false` would render as "No lookalike
      // domain detected" on a check nothing ever ran - a false negative
      // presented as a finding. The correct representation of "not
      // determined" is silence: no event for this lane at all.

      case "detonate":
        if (!isDetonationResult(parsed)) return []; // malformed result - not a well-formed mission event either
        return [{ type: "mission.detonation", mission_id: missionId, detonation: parsed }];

      // NOTE: the four gated tools (quarantine, notify_impersonated,
      // create_block_rule, file_abuse_report) are deliberately absent from
      // this switch - they are handled above, before the JSON parse is
      // allowed to decide the outcome.

      default:
        return []; // unrecognised tool name
    }

    // NOTE: there is also no mission.verdict emitted anywhere in this file.
    // VerdictEvent requires a malicious|suspicious|legitimate label
    // (contracts/events.ts), but the stream only ever publishes the model's
    // plain prose (turn.done's output.content, read below). Turning that
    // prose into one of three labels would mean this translator inventing a
    // verdict TrueForge never actually rendered - out of scope for a
    // translator whose job is to move data, not to add analysis.
  }

  function handleTurnDone(raw: Record<string, unknown>): MissionEvent[] {
    const state = raw.state;
    if (!isRecord(state)) return [];
    const status = state.status;

    if (status === "error") {
      // TurnStateError.message is required on the wire (contracts/events.ts),
      // but `raw` is unknown here, so still guard rather than assume.
      const message = isStr(state.message) ? state.message : "";
      const event: MissionFailedEvent = { type: "mission.failed", mission_id: missionId, cause: "error", message };
      return [...flushQueuedGates(), event];
    }

    if (status === "cancelled") {
      const reason = state.reason;
      if (!isTurnCancelledReason(reason)) {
        // TurnCancelledReason is a closed 4-value enum, so a reason outside
        // it cannot be reported as `cause: "cancelled"` without inventing an
        // enum value. But dropping the event is worse than reporting it
        // imprecisely: `mission.failed` exists precisely so a terminated
        // mission stops rendering as in-progress forever, and staying silent
        // here reintroduces exactly that bug for the one input we did not
        // expect. So it degrades to the free-text branch, quoting whatever
        // arrived verbatim — no enum value is fabricated, and the mission
        // still terminates. Only reachable if TrueForge widens the enum.
        const described = isStr(reason) ? reason : JSON.stringify(reason);
        const event: MissionFailedEvent = {
          type: "mission.failed",
          mission_id: missionId,
          cause: "error",
          message: `turn cancelled with an unrecognised reason: ${described}`,
        };
        return [...flushQueuedGates(), event];
      }
      const event: MissionFailedEvent = { type: "mission.failed", mission_id: missionId, cause: "cancelled", reason };
      return [...flushQueuedGates(), event];
    }

    if (status === "done") {
      // IMPORTANT: `done` means the turn's model loop finished, not that the
      // mission finished. TrueForge sets `required_actions` when a gated
      // tool call is still awaiting a decision, and leaves `output` null/
      // absent in that same case (verified against a running server's
      // openapi.json, T-037). Treating `done` as mission.complete here would
      // tell the cockpit a run that's actually paused on a human licence
      // decision has already reached its spoken verdict - exactly the kind
      // of premature "finished" state T-037 exists to avoid.
      const requiredActions = state.required_actions;
      const isPaused = (isArr(requiredActions) && requiredActions.length > 0) || state.output === null || state.output === undefined;
      if (isPaused) return [];

      const spokenVerdict = extractOutputText(state.output);
      return [
        ...flushQueuedGates(),
        { type: "mission.complete", mission_id: missionId, spoken_verdict: spokenVerdict },
      ];
    }

    return []; // unrecognised status
  }

  function push(raw: unknown): MissionEvent[] {
    if (!isRecord(raw)) return [];
    const type = raw.type;
    if (!isStr(type)) return [];

    switch (type) {
      // These carry nothing a mission.* event needs, or nothing a translator
      // can safely act on yet - listed explicitly (rather than falling
      // through to default) so a reviewer can see every wire type was
      // considered, not just guessed to be irrelevant.
      case "turn.created": // no mission-relevant payload
      case "thread.created": // no mission-relevant payload
      case "thread.done": // superseded by turn.done, which carries the actual outcome
      case "mcp.initialize": // transport bookkeeping, not mission content
      case "mcp.auth_required": // transport bookkeeping, not mission content
      case "sandbox.created": // infra bookkeeping - CLAUDE.md trap: we write what runs inside the sandbox, not the sandbox lifecycle
      case "tool.response_required": // superseded by tool.approval_required for the four gated tools; nothing else asks a human
      case "model.message.delta": // streaming fragments of model.message - only the assembled message carries usable tool_calls
        return [];

      case "model.message":
        return handleModelMessage(raw);

      case "tool.approval_required":
        return handleApprovalRequired(raw);

      case "tool.response":
        return handleToolResponse(raw);

      case "turn.done":
        return handleTurnDone(raw);

      default:
        return []; // unrecognised type - never throw on an event TrueForge might add later
    }
  }

  return { push, resolveGate };
}
