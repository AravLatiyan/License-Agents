// contracts/events.ts
//
// Shared event/type contract between the harness (O1), tools (O2), and the
// Cockpit (O3). Two layers:
//
//   1. TrueForge wire-level primitives — the approval/session schema
//      confirmed live against the running server's own OpenAPI schema in
//      T-002 (PLAN.md §6, 2026-08-25). Not invented; copied from that finding.
//
//   2. MissionEvent — our own higher-level event stream, one variant per
//      stage of PLAN.md §10's architecture diagram (message -> 3 parallel
//      subagents + detonation -> verdict -> 4 sequential licence gates ->
//      execute -> done). This is what Cockpit's T-050 scaffold consumes to
//      render the mission end to end, and what T-036's LICENCE REQUIRED
//      panel binds to for each gate.
//
// PLAN.md §11 T-016 is the only source of truth for scope here — this file
// does not implement T-050/T-036/T-052, it only defines the shapes those
// tasks will need.

// ---------------------------------------------------------------------------
// 1. TrueForge wire-level primitives (T-002, PLAN.md §6)
// ---------------------------------------------------------------------------

export interface ToolCallRequest {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

/** Emitted over SSE from POST /sessions/{id}/turns (stream:true) when a
 *  gated tool call needs a human decision. */
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
  approval: {
    status: ApprovalStatus;
    reason?: string;
  };
}

/** Reconnects use GET /turns/{id}/subscribe?after_sequence_number=N */
export interface TurnStreamSubscription {
  turn_id: string;
  after_sequence_number: number;
}

// ---------------------------------------------------------------------------
// 2. MCP tool result shapes (PLAN.md §10, "MCP tool surface" table)
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
  registration_date: string | null; // null = "not published" (PLAN.md §12), never treated as an error
  registrar: string | null;
  abuse_contact: string | null;
  cert_issued_at: string | null;
}

export interface UrlReputation {
  url: string;
  listed: boolean; // URLhaus is a weak signal only (PLAN.md §12 / CLAUDE.md trap #8) — "not listed" != safe
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

/** §10's IDENTITY lane ("display-name vs reply-to, lookalike domain") has no
 *  dedicated MCP tool of its own in the §10 tool table — it's derived from
 *  fields already present on ParsedMessage. Worded directly from that
 *  diagram text; see PLAN.md §8 for the note flagging this to O1/O2. */
export interface IdentityEvidence {
  from_address: string;
  display_name: string | null;
  reply_to: string | null;
  lookalike_domain: boolean;
  lookalike_of: string | null; // the legitimate domain being impersonated, if known
}

export interface DetonationForm {
  action: string | null;
  action_invalid?: boolean; // matches harness/detonate.js's shape (T-014, Qodo pass)
  asks_for_password: boolean;
  posts_cross_domain: boolean;
}

export interface DetonationResult {
  url: string;
  redirect_chain: string[];
  final_url?: string;
  forms?: DetonationForm[];
  screenshot_id?: string; // never base64 in the event, per CLAUDE.md trap #12
  summary: string;
  error?: string;
}

// ---------------------------------------------------------------------------
// 3. Mission-level events — one per §10 architecture stage / §17 demo beat.
//    This is the stream Cockpit's T-050 scaffold consumes start to finish.
// ---------------------------------------------------------------------------

export type EvidenceLane = "infrastructure" | "identity" | "history";

export interface MessageReceivedEvent {
  type: "mission.message_received";
  mission_id: string;
  message: ParsedMessage;
}

/** One of the three parallel subagents (§10) reporting structured evidence,
 *  never prose (T-024's requirement, carried into the contract). */
export interface EvidenceEvent {
  type: "mission.evidence";
  mission_id: string;
  lane: EvidenceLane;
  evidence: DomainIntel | UrlReputation | CorrespondenceHistory | IdentityEvidence;
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
  summary: string; // plain English, <=4 sentences, no jargon (§11 T-054)
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

/** Cockpit's LICENCE REQUIRED panel (T-036) binds to this. It carries the
 *  real ToolApprovalRequiredEvent inline so Cockpit renders gates off one
 *  mission stream rather than a second TrueForge connection. Four sequential
 *  gates, never one modal with four checkboxes (§6, 2026-08-24). */
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
  spoken_verdict: string; // §17, 2:40-3:00 — Web Speech API text (T-043)
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
