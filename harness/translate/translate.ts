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
}

// --- small structural guards, no validation library - kept dependency-free,
// same approach as cockpit/src/missionSource.ts ---

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
const isStr = (v: unknown): v is string => typeof v === "string";
const isArr = (v: unknown): v is unknown[] => Array.isArray(v);

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

  // Number of mission.approval_required events emitted so far. Gate indices
  // are assigned in arrival order starting at 1, per contracts/events.ts's
  // ApprovalRequiredEvent doc comment ("a translator assigns them by arrival
  // order").
  let gatesAssigned = 0;

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

  function handleApprovalRequired(raw: Record<string, unknown>): MissionEvent[] {
    const toolCalls = raw.tool_calls;
    if (!isArr(toolCalls)) return [];
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
        // Kept verbatim for provenance (contracts/events.ts's `approval`
        // field doc). This is the same raw event we already read tool_calls
        // out of above, cast back to its wire type rather than re-validated -
        // this translator's job is to move data, not to police TrueForge's
        // own schema a second time.
        approval: raw as unknown as ToolApprovalRequiredEvent,
      };
      out.push(event);
    }

    return out;
  }

  function handleToolResponse(raw: Record<string, unknown>): MissionEvent[] {
    const toolCallId = raw.tool_call_id;
    const content = raw.content;
    if (!isStr(toolCallId) || !isStr(content)) return [];

    const pending = pendingCalls.get(toolCallId);
    if (!pending) return []; // no matching model.message seen - can't tell which tool this result is from

    let parsed: unknown;
    try {
      parsed = JSON.parse(content);
    } catch {
      return []; // unreadable result - nothing safe to attach it to
    }

    const name = pending.name;
    switch (name) {
      case "parse_message":
        return [{ type: "mission.message_received", mission_id: missionId, message: parsed as ParsedMessage }];

      case "domain_intel":
      case "url_reputation":
        return [
          {
            type: "mission.evidence",
            mission_id: missionId,
            lane: "infrastructure",
            evidence: parsed as DomainIntel | UrlReputation,
          },
        ];

      case "correspondence_history":
        return [
          {
            type: "mission.evidence",
            mission_id: missionId,
            lane: "history",
            evidence: parsed as CorrespondenceHistory,
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
        return [{ type: "mission.detonation", mission_id: missionId, detonation: parsed as DetonationResult }];

      case "quarantine":
      case "notify_impersonated":
      case "create_block_rule":
      case "file_abuse_report": {
        const gateIndex = gateIndexByToolCallId.get(toolCallId);
        if (gateIndex === undefined) return []; // result for a call that never became a licence gate - nothing to attach it to
        const resultSummary = isRecord(parsed) && isStr(parsed.note) ? parsed.note : "";
        const event: ActionExecutedEvent = {
          type: "mission.action_executed",
          mission_id: missionId,
          gate_index: gateIndex,
          action: name,
          result_summary: resultSummary,
        };
        return [event];
      }

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
      return [event];
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
        return [event];
      }
      const event: MissionFailedEvent = { type: "mission.failed", mission_id: missionId, cause: "cancelled", reason };
      return [event];
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
      return [{ type: "mission.complete", mission_id: missionId, spoken_verdict: spokenVerdict }];
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

  return { push };
}
