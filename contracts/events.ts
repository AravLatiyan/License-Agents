// contracts/events.ts
//
// Shared contract between the harness (O1), tools (O2), and Cockpit (O3).
// Layer 1: TrueForge's wire-level approval/session schema, confirmed live
// in T-002 (PLAN.md §6) and re-verified field-by-field against a running
// server's own openapi.json in T-037 (2026-08-29). Layer 2: MissionEvent,
// one variant per §10 architecture stage, which is what T-050/T-036 bind to.
//
// The two layers are NOT the same vocabulary and never map one-to-one.
// TrueForge's turn stream is a closed union of 12 generic event types
// (turn.created/done, thread.created/done, model.message[.delta],
// tool.response, tool.approval_required, tool.response_required,
// mcp.initialize, mcp.auth_required, sandbox.created) with a `type`
// discriminator — there is no extension point for an agent to emit a
// `mission.*` event of its own. `mission.*` is therefore always produced by
// translating the raw stream on our side, never by the agent (T-037).
//
// MAINTENANCE (Qodo finding #6, T-016 remediation, 2026-08-26):
// - Shape source of truth is the actual producer code — harness/detonate.js
//   for DetonationResult, TrueForge's live schema (§6/T-002) for the
//   approval primitives, the MCP tool implementations (once merged) for
//   the rest of §10's table. Never PLAN.md prose alone.
// - A PR that changes a producer's output shape updates this file in the
//   same PR — Qodo's T-016 review caught exactly that drift once already.
// - A change here that affects a fixture-used shape updates the fixture
//   in the same PR.
// - /contracts needs 2 approvals (CLAUDE.md) — route the producer-owning
//   owner (O1/O2) plus one other reviewer on any contract change.
// - Cockpit code imports types from here; it never redeclares them.
// - Validate before every push:
//     npx -p typescript tsc --noEmit --strict contracts/events.ts contracts/events.typecheck.ts
//     python3 -m json.tool contracts/fixtures/mission-happy-path.json

// ---------------------------------------------------------------------------
// 1. TrueForge wire-level primitives (T-002, PLAN.md §6)
// ---------------------------------------------------------------------------

/**
 * A tool call awaiting a decision, exactly as `tool.approval_required`
 * carries it (TrueForge schema `ToolCallRef`, both fields required).
 *
 * CORRECTED T-037, 2026-08-29. This was previously declared as a
 * `ToolCallRequest` with `tool_name` and an `arguments` object — a shape
 * TrueForge has never emitted. `ToolCallRequest` is not a schema name
 * TrueForge defines at all; the drift was written from PLAN.md prose rather
 * than the producer, the same class of bug Qodo caught once already on
 * `DomainIntel` (§8, 2026-08-27), and the file's own MAINTENANCE note
 * above is the rule it broke.
 *
 * The approval event deliberately does NOT repeat the name or the
 * arguments. To recover them, follow `source_event_id` back to the
 * `model.message` that requested the call and match `id` against its
 * `tool_calls[].id` — see ModelMessageToolCall. A consumer that needs the
 * human-readable request should read `ApprovalRequiredEvent.action`
 * instead, which is exactly that resolved pair.
 */
export interface ToolCallRef {
  id: string;
  /** Event id of the `model.message` that requested this tool call. */
  source_event_id: string;
}

/**
 * One tool call as it appears on a `model.message` event — the only place
 * the name and arguments are actually published.
 *
 * `arguments` is a **JSON-encoded string**, not an object: TrueForge passes
 * the model's raw function-call arguments through verbatim. Parsing it can
 * fail on a malformed model output, so a consumer parses defensively rather
 * than assuming it is well-formed.
 */
export interface ModelMessageToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

/** SSE from POST /sessions/{id}/turns when a gated tool call needs a decision. */
export interface ToolApprovalRequiredEvent {
  type: "tool.approval_required";
  id: string;
  created_at: string; // ISO 8601
  thread_id: string;
  tool_calls: ToolCallRef[];
}

export type ApprovalStatus = "allow" | "deny";

/** Posted back as a turn's `input` to resume a gated tool call. */
export interface ToolApprovalResume {
  type: "user.tool_approval";
  thread_id: string;
  tool_call_id: string;
  approval: { status: ApprovalStatus; reason?: string };
}

/**
 * Why a turn was cancelled. Exactly TrueForge's `TurnStateCancelledReason`
 * enum, verified against a running server's openapi.json (T-037) — not a
 * paraphrase, and deliberately not collapsed to free text: `abandoned` and
 * `client-cancelled` mean different things to a human reading the cockpit.
 */
export type TurnCancelledReason =
  | "server-execution-timeout"
  | "client-cancelled"
  | "cancelled-for-next-turn"
  | "abandoned";

/** Reconnects use GET /turns/{id}/subscribe?after_sequence_number=N */
export interface TurnStreamSubscription {
  turn_id: string;
  after_sequence_number: number;
}

// ---------------------------------------------------------------------------
// 2. MCP tool result shapes (PLAN.md §10 tool table + real producer code)
// ---------------------------------------------------------------------------

export interface ParsedMessage {
  message_id: string;
  from: string;
  reply_to: string | null;
  return_path: string | null;
  display_name: string | null;
  authentication_results: string;
  received_chain: string[];
  urls: Array<{ href: string; anchor_text: string }>;
  attachments: Array<{ filename: string; sha256: string }>;
}

export interface DomainIntel {
  domain: string;
  registration_date: string | null; // null = "not published" (§12), never an error
  registrar: string | null;
  abuse_contact: string | null;
  cert_issued_at: string | null;
}

export interface UrlReputation {
  url: string;
  listed: boolean; // weak signal only (§12/CLAUDE.md trap #8) — "not listed" != safe
  tags: string[];
}

export interface CorrespondenceHistory {
  address: string;
  domain: string;
  prior_contact_count: number;
  first_seen: string | null;
  last_seen: string | null;
  domains_used: string[];
}

/**
 * §10's IDENTITY lane has no dedicated tool — derived from ParsedMessage
 * fields. Worded from the diagram text; see §8 (needs O1/O2 confirmation).
 *
 * NO PRODUCER EXISTS for `lookalike_domain`/`lookalike_of` (T-037, verified
 * against every module in tools/imports_mcp). When they have not been
 * computed, a translator MUST NOT emit this event with `lookalike_domain:
 * false` — both cockpit render sites turn that into the words "No lookalike
 * domain detected", asserting a clean security finding nothing ever checked.
 *
 * The supported representation of "not determined" is **absence**: emit no
 * `mission.evidence` event for this lane at all. An empty lane is an
 * already-handled, already-tested state (cockpit commit f9a19bd, T-052) and
 * renders as "Waiting…"/"Nothing reported", which is honest. Note also that
 * widening `lookalike_domain` to `boolean | null` would NOT help — `null` is
 * falsy, so both render sites take the identical branch and print the same
 * false negative.
 *
 * `from_address`/`display_name`/`reply_to` are not lost by that absence:
 * they already reach the cockpit on `mission.message_received`'s ParsedMessage.
 */
export interface IdentityEvidence {
  from_address: string;
  display_name: string | null;
  reply_to: string | null;
  lookalike_domain: boolean;
  lookalike_of: string | null;
}

// --- Detonation: modeled directly from harness/detonate.js, not invented ---

export interface RedirectHop {
  url: string;
  status: number;
}

/** One <form>. Mirrors detonate.js's extractForms() exactly: a form with an
 *  unparseable `action` still reports action/method/asks_password, but
 *  action_origin/cross_domain can't be computed (action_invalid: true). */
export type DetonationForm =
  | {
      action: string;
      action_origin: string;
      method: string;
      cross_domain: boolean;
      asks_password: boolean;
      action_invalid?: false;
    }
  | {
      action: string;
      action_origin: null;
      method: string;
      cross_domain: null;
      asks_password: boolean;
      action_invalid: true;
    };

/** detonate() returns exactly one of these two shapes — never throws.
 *  Error branch (bad scheme, DNS/timeout/redirect-loop/oversized body):
 *  no final_url/forms/summary. Success branch: no error. */
export type DetonationResult =
  | { url: string; redirect_chain: RedirectHop[]; error: string }
  | {
      url: string;
      redirect_chain: RedirectHop[];
      final_url: string;
      forms: DetonationForm[];
      summary: string;
      screenshot_id?: string; // stretch goal, §6 — detonate.js never sets this yet
    };

// ---------------------------------------------------------------------------
// 3. Mission-level events — one per §10 architecture stage / §17 demo beat.
// ---------------------------------------------------------------------------

/** Lane and evidence shape are paired per-variant so `lane: "history"` with
 *  `DomainIntel` evidence is a type error, not just a runtime mismatch
 *  (Qodo finding #4). See contracts/events.typecheck.ts for a compiled proof. */
export type EvidenceEvent =
  | { type: "mission.evidence"; mission_id: string; lane: "infrastructure"; evidence: DomainIntel | UrlReputation }
  | { type: "mission.evidence"; mission_id: string; lane: "identity"; evidence: IdentityEvidence }
  | { type: "mission.evidence"; mission_id: string; lane: "history"; evidence: CorrespondenceHistory };

export type EvidenceLane = EvidenceEvent["lane"];

export interface MessageReceivedEvent {
  type: "mission.message_received";
  mission_id: string;
  message: ParsedMessage;
}

export interface DetonationEvent {
  type: "mission.detonation";
  mission_id: string;
  detonation: DetonationResult;
}

export type VerdictLabel = "malicious" | "suspicious" | "legitimate";

export interface VerdictEvent {
  type: "mission.verdict";
  mission_id: string;
  verdict: VerdictLabel;
  summary: string; // plain English, <=4 sentences (§11 T-054)
}

export type ProposedActionName =
  | "quarantine"
  | "notify_impersonated"
  | "create_block_rule"
  | "file_abuse_report";

export interface ProposedAction {
  action: ProposedActionName;
  arguments: Record<string, unknown>;
}

/**
 * T-036's LICENCE REQUIRED panel binds to this. Four sequential gates
 * (§6, 2026-08-24).
 *
 * `action` is the human-readable request — the resolved tool name and its
 * decoded arguments — and is what a panel should display. `approval` is the
 * raw wire event kept verbatim for provenance; since T-037 corrected it to
 * the real schema, its `tool_calls` carry only `{id, source_event_id}` and
 * are NOT displayable on their own.
 *
 * `gate_index`/`gate_count` are our semantics, not TrueForge's: nothing in
 * the turn stream numbers approvals. A translator assigns them by arrival
 * order. `gate_count: 4` therefore encodes §10/§17's four-gate design, and
 * a run that proposes a different number of actions does not fit this shape
 * — deliberately left as-is pending a decision, not silently widened (T-037).
 */
export interface ApprovalRequiredEvent {
  type: "mission.approval_required";
  mission_id: string;
  gate_index: 1 | 2 | 3 | 4;
  gate_count: 4;
  action: ProposedAction;
  /**
   * The id of the tool call THIS gate is about (T-046, Qodo PR #85).
   *
   * `approval` below is the raw wire event, and one such event can carry
   * several `tool_calls` — so a consumer resuming a decision cannot take
   * `approval.tool_calls[0]`: for the second gate of a multi-call request
   * that is the *first* call's id. Doing so would display one action while
   * allowing or denying a different one, which is the exact failure this
   * whole licence mechanism exists to prevent. The translator knows which
   * call each gate belongs to, so it records it here rather than leaving
   * every consumer to re-derive it and get it wrong.
   */
  tool_call_id: string;
  approval: ToolApprovalRequiredEvent;
}

export interface ApprovalResolvedEvent {
  type: "mission.approval_resolved";
  mission_id: string;
  gate_index: 1 | 2 | 3 | 4;
  status: ApprovalStatus;
  reason?: string;
}

export interface ActionExecutedEvent {
  type: "mission.action_executed";
  mission_id: string;
  gate_index: 1 | 2 | 3 | 4;
  action: ProposedActionName;
  result_summary: string;
}

export interface MissionCompleteEvent {
  type: "mission.complete";
  mission_id: string;
  spoken_verdict: string; // §17 2:40-3:00 — Web Speech API text (T-043)
}

/**
 * A turn that ended without completing. Added in T-037 because nothing else
 * could carry it honestly: `VerdictLabel` is a closed
 * malicious|suspicious|legitimate union, so a crash is not expressible as a
 * verdict, and `mission.complete` means finished and carries the
 * `spoken_verdict` T-043 reads aloud. Without this variant the cockpit's
 * `missionDone` (derived solely from `mission.complete`) never becomes true
 * on a failed turn and every stage renders as in-progress forever.
 *
 * Scope is deliberately *terminal turn failure only* — `TurnDoneEvent.state`
 * has exactly three members and one of them is success, which is why `cause`
 * has exactly two values. It is NOT a general error channel: a subagent's
 * `ThreadStateError` and a model `refusal`/`content_filter` both occur inside
 * a turn that still reaches `turn.done` normally, so neither leaves the
 * mission unterminated, and both are already handled as evidence quality by
 * agent.json's T-041 instruction. They are not force-fitted here.
 *
 * Each branch carries the field its own producer actually publishes, rather
 * than one shared `message`: TrueForge's `TurnStateError` has a required
 * `message` string, while `TurnStateCancelled` has no message at all — only a
 * required four-value `reason` enum. Collapsing both into one string would
 * have meant synthesising text and discarding that enum, which is the exact
 * drift class T-037 exists to correct.
 */
export type MissionFailedEvent =
  | {
      type: "mission.failed";
      mission_id: string;
      cause: "error";
      /** TrueForge TurnStateError.message — required there, always present. */
      message: string;
    }
  | {
      type: "mission.failed";
      mission_id: string;
      cause: "cancelled";
      /** TrueForge TurnStateCancelled.reason — required there. No message
       *  field exists on that state, so none is invented here. */
      reason: TurnCancelledReason;
    };

export type MissionEvent =
  | MessageReceivedEvent
  | EvidenceEvent
  | DetonationEvent
  | VerdictEvent
  | ApprovalRequiredEvent
  | ApprovalResolvedEvent
  | ActionExecutedEvent
  | MissionCompleteEvent
  | MissionFailedEvent;
