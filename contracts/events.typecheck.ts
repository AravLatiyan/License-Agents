// contracts/events.typecheck.ts
//
// Dev-only compile-time proof for Qodo finding #4 (T-016 remediation): lane
// and evidence type must be paired, not two independent unions. Not imported
// by app code. Run as part of any contract validation:
//   npx -p typescript tsc --noEmit --strict contracts/events.ts contracts/events.typecheck.ts

import type { EvidenceEvent, DomainIntel } from "./events";

const domainIntel: DomainIntel = {
  domain: "example.com",
  registration_date: null,
  registrar: null,
  abuse_contact: null,
  cert_issued_at: null,
};

// Valid: infrastructure lane accepts DomainIntel.
const validPairing: EvidenceEvent = {
  type: "mission.evidence",
  mission_id: "m",
  lane: "infrastructure",
  evidence: domainIntel,
};

// Invalid: history lane must only accept CorrespondenceHistory. If this line
// stops erroring, the lane/evidence narrowing has regressed.
// @ts-expect-error - history lane cannot accept DomainIntel evidence
const invalidPairing: EvidenceEvent = {
  type: "mission.evidence",
  mission_id: "m",
  lane: "history",
  evidence: domainIntel,
};

void validPairing;
void invalidPairing;

// --- T-037: the approval request carries a reference, not the call itself ---

import type { ToolApprovalRequiredEvent, ModelMessageToolCall } from "./events";

// Valid: tool_calls carry only the reference pair TrueForge actually emits.
const approvalRequired: ToolApprovalRequiredEvent = {
  type: "tool.approval_required",
  id: "evt_01J",
  created_at: "2026-08-29T18:05:00Z",
  thread_id: "main",
  tool_calls: [{ id: "call-001", source_event_id: "evt_01H" }],
};

// Invalid: the pre-T-037 shape. If this line stops erroring, the drift is
// back — tool_name/arguments are not on the wire event, and a consumer that
// reads them renders fields TrueForge never sent.
const staleApprovalShape: ToolApprovalRequiredEvent = {
  type: "tool.approval_required",
  id: "evt_01J",
  created_at: "2026-08-29T18:05:00Z",
  thread_id: "main",
  // @ts-expect-error - tool_calls are ToolCallRef, not {tool_name, arguments}
  tool_calls: [{ id: "call-001", tool_name: "quarantine", arguments: {} }],
};

// The name and arguments live here instead, and `arguments` is a JSON string.
const requestingCall: ModelMessageToolCall = {
  id: "call-001",
  type: "function",
  function: { name: "quarantine", arguments: '{"message_ids":["msg-001"]}' },
};

const parsedArgumentsRejected: ModelMessageToolCall = {
  id: "call-001",
  type: "function",
  function: {
    name: "quarantine",
    // @ts-expect-error - arguments is a JSON-encoded string, never a parsed object
    arguments: { message_ids: ["msg-001"] },
  },
};

void approvalRequired;
void staleApprovalShape;
void requestingCall;
void parsedArgumentsRejected;

// --- T-037: a failed turn is not a verdict, and each cause keeps its own field ---

import type { MissionFailedEvent, MissionEvent } from "./events";

// Valid: the error branch carries TurnStateError.message.
const failedByError: MissionFailedEvent = {
  type: "mission.failed",
  mission_id: "mission-001",
  cause: "error",
  message: "model provider returned 502",
};

// Valid: the cancelled branch carries TurnStateCancelled.reason, an enum.
const failedByCancel: MissionFailedEvent = {
  type: "mission.failed",
  mission_id: "mission-001",
  cause: "cancelled",
  reason: "client-cancelled",
};

// Invalid: cancellation has no message on the wire. If this stops erroring,
// the branches have been collapsed and the four-value reason enum is being
// flattened into synthesised prose.
const cancelWithMessage: MissionFailedEvent = {
  type: "mission.failed",
  mission_id: "mission-001",
  cause: "cancelled",
  // @ts-expect-error - the cancelled branch takes `reason`, never `message`
  message: "cancelled",
};

// Invalid: a reason TrueForge does not define.
const inventedReason: MissionFailedEvent = {
  type: "mission.failed",
  mission_id: "mission-001",
  cause: "cancelled",
  // @ts-expect-error - not a TurnCancelledReason value
  reason: "gave-up",
};

// A failure must never be expressible as a verdict: VerdictLabel is closed,
// so force-fitting a crash into mission.verdict cannot type-check.
const failureIsNotAVerdict: MissionEvent = {
  type: "mission.verdict",
  mission_id: "mission-001",
  // @ts-expect-error - "error" is not a VerdictLabel; failures use mission.failed
  verdict: "error",
  summary: "the turn crashed",
};

void failedByError;
void failedByCancel;
void cancelWithMessage;
void inventedReason;
void failureIsNotAVerdict;
