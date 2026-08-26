// contracts/events.ts
//
// Shared contract between the harness (O1), tools (O2), and Cockpit (O3).
// Layer 1: TrueForge's wire-level approval/session schema, confirmed live
// in T-002 (PLAN.md §6). Layer 2: MissionEvent, one variant per §10
// architecture stage, which is what T-050/T-036 bind to.
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

export interface ToolCallRequest {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

/** SSE from POST /sessions/{id}/turns when a gated tool call needs a decision. */
export interface ToolApprovalRequiredEvent {
  type: "tool.approval_required";
  id: string;
  created_at: string; // ISO 8601
  thread_id: string;
  tool_calls: ToolCallRequest[];
}

export type ApprovalStatus = "allow" | "deny";

/** Posted back as a turn's `input` to resume a gated tool call. */
export interface ToolApprovalResume {
  type: "user.tool_approval";
  thread_id: string;
  tool_call_id: string;
  approval: { status: ApprovalStatus; reason?: string };
}

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

/** §10's IDENTITY lane has no dedicated tool — derived from ParsedMessage
 *  fields. Worded from the diagram text; see §8 (needs O1/O2 confirmation). */
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

/** T-036's LICENCE REQUIRED panel binds to this. Carries the real
 *  ToolApprovalRequiredEvent inline. Four sequential gates (§6, 2026-08-24). */
export interface ApprovalRequiredEvent {
  type: "mission.approval_required";
  mission_id: string;
  gate_index: 1 | 2 | 3 | 4;
  gate_count: 4;
  action: ProposedAction;
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

export type MissionEvent =
  | MessageReceivedEvent
  | EvidenceEvent
  | DetonationEvent
  | VerdictEvent
  | ApprovalRequiredEvent
  | ApprovalResolvedEvent
  | ActionExecutedEvent
  | MissionCompleteEvent;
