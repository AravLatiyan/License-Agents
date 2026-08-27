import type { MissionEvent } from "../../contracts/events";

/**
 * Where mission events come from. T-050 only implements fixture playback;
 * the real source (T-002/PLAN.md §6) is TrueForge's own HTTP/SSE API:
 *   POST /sessions -> POST /sessions/{id}/turns (stream:true) -> SSE
 *   watch for tool.approval_required, resume with a turn whose input is
 *   {type:"user.tool_approval", thread_id, tool_call_id, approval:{...}}
 *   reconnect via GET /turns/{id}/subscribe?after_sequence_number=
 * Swapping fixtureEventSource for a trueForgeEventSource is meant to be the
 * only change later work needs - everything downstream only ever sees
 * MissionEvent, never knows where it came from.
 */
export type MissionEventSource = () => AsyncIterable<MissionEvent>;

const KNOWN_TYPES = new Set<MissionEvent["type"]>([
  "mission.message_received",
  "mission.evidence",
  "mission.detonation",
  "mission.verdict",
  "mission.approval_required",
  "mission.approval_resolved",
  "mission.action_executed",
  "mission.complete",
]);

const KNOWN_LANES = new Set(["infrastructure", "identity", "history"]);
const GATE_INDICES = new Set([1, 2, 3, 4]);

// --- small structural guards, no validation library - kept dependency-free ---

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
const isStr = (v: unknown): v is string => typeof v === "string";
const isStrOrNull = (v: unknown): v is string | null => v === null || typeof v === "string";
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const isNum = (v: unknown): v is number => typeof v === "number";
const isArr = (v: unknown): v is unknown[] => Array.isArray(v);

function fail(index: number, message: string): never {
  throw new Error(`event[${index}]: ${message}`);
}

// --- one checker per nested payload shape in contracts/events.ts - kept in
// lockstep with that file, never a divergent shape of our own ---

function checkParsedMessage(v: unknown, index: number): void {
  if (!isRecord(v)) fail(index, "message: expected an object");
  if (!isStr(v.message_id)) fail(index, "message.message_id: expected string");
  if (!isStr(v.from)) fail(index, "message.from: expected string");
  if (!isStrOrNull(v.reply_to)) fail(index, "message.reply_to: expected string or null");
  if (!isStrOrNull(v.return_path)) fail(index, "message.return_path: expected string or null");
  if (!isStrOrNull(v.display_name)) fail(index, "message.display_name: expected string or null");
  if (!isStr(v.authentication_results)) fail(index, "message.authentication_results: expected string");
  if (!isArr(v.received_chain)) fail(index, "message.received_chain: expected array");
  if (!isArr(v.urls)) fail(index, "message.urls: expected array");
  if (!isArr(v.attachments)) fail(index, "message.attachments: expected array");
}

const isDomainIntel = (v: unknown): boolean =>
  isRecord(v) &&
  isStr(v.domain) &&
  isStrOrNull(v.registration_date) &&
  isStrOrNull(v.registrar) &&
  isStrOrNull(v.abuse_contact) &&
  isStrOrNull(v.cert_issued_at);

const isUrlReputation = (v: unknown): boolean =>
  isRecord(v) && isStr(v.url) && isBool(v.listed) && isArr(v.tags);

const isIdentityEvidence = (v: unknown): boolean =>
  isRecord(v) &&
  isStr(v.from_address) &&
  isStrOrNull(v.display_name) &&
  isStrOrNull(v.reply_to) &&
  isBool(v.lookalike_domain) &&
  isStrOrNull(v.lookalike_of);

const isCorrespondenceHistory = (v: unknown): boolean =>
  isRecord(v) &&
  isStr(v.address) &&
  isStr(v.domain) &&
  isNum(v.prior_contact_count) &&
  isStrOrNull(v.first_seen) &&
  isStrOrNull(v.last_seen) &&
  isArr(v.domains_used);

function checkEvidence(lane: string, evidence: unknown, index: number): void {
  const valid =
    (lane === "infrastructure" && (isDomainIntel(evidence) || isUrlReputation(evidence))) ||
    (lane === "identity" && isIdentityEvidence(evidence)) ||
    (lane === "history" && isCorrespondenceHistory(evidence));
  if (!valid) {
    fail(index, `mission.evidence: "evidence" does not match lane "${lane}"'s shape`);
  }
}

/** Mirrors DetonationResult's two-branch union exactly - error branch has no
 *  final_url/forms/summary, success branch has no error. */
function checkDetonationResult(v: unknown, index: number): void {
  if (!isRecord(v)) fail(index, "detonation: expected an object");
  if (!isStr(v.url)) fail(index, "detonation.url: expected string");
  if (!isArr(v.redirect_chain)) fail(index, "detonation.redirect_chain: expected array");
  const hasError = "error" in v;
  const hasSuccess = "summary" in v;
  if (hasError === hasSuccess) {
    fail(index, "detonation: must have exactly one of error or final_url/forms/summary");
  }
  if (hasError && !isStr(v.error)) fail(index, "detonation.error: expected string");
  if (hasSuccess) {
    if (!isStr(v.final_url)) fail(index, "detonation.final_url: expected string");
    if (!isArr(v.forms)) fail(index, "detonation.forms: expected array");
    if (!isStr(v.summary)) fail(index, "detonation.summary: expected string");
  }
}

function checkToolApprovalRequired(v: unknown, index: number): void {
  if (!isRecord(v)) fail(index, "approval: expected an object");
  if (v.type !== "tool.approval_required") fail(index, 'approval.type: expected "tool.approval_required"');
  if (!isStr(v.id) || !isStr(v.created_at) || !isStr(v.thread_id)) {
    fail(index, "approval: missing id/created_at/thread_id");
  }
  if (!isArr(v.tool_calls)) fail(index, "approval.tool_calls: expected array");
  for (const call of v.tool_calls) {
    if (!isRecord(call) || !isStr(call.id) || !isStr(call.tool_name) || !isRecord(call.arguments)) {
      fail(index, "approval.tool_calls: expected {id, tool_name, arguments}");
    }
  }
}

/**
 * Rejects anything that isn't a genuinely well-formed MissionEvent instead
 * of silently rendering it. Checks every variant's required nested payload,
 * not just the top-level discriminant (and, for evidence, the lane) - a
 * detonation event missing `detonation`, or an evidence event whose payload
 * doesn't actually match its lane, is now caught here rather than reaching
 * MissionView and crashing or rendering undefined fields.
 */
export function assertMissionEvent(value: unknown, index: number): MissionEvent {
  if (!isRecord(value)) {
    fail(index, `expected an object, got ${JSON.stringify(value)}`);
  }
  const type = value.type;
  if (typeof type !== "string" || !KNOWN_TYPES.has(type as MissionEvent["type"])) {
    fail(index, `unknown or missing "type" (${JSON.stringify(type)})`);
  }
  if (!isStr(value.mission_id)) {
    fail(index, `missing "mission_id"`);
  }

  switch (type as MissionEvent["type"]) {
    case "mission.message_received":
      checkParsedMessage(value.message, index);
      break;
    case "mission.evidence": {
      const lane = value.lane;
      if (typeof lane !== "string" || !KNOWN_LANES.has(lane)) {
        fail(index, `mission.evidence has invalid "lane" (${JSON.stringify(lane)})`);
      }
      checkEvidence(lane, value.evidence, index);
      break;
    }
    case "mission.detonation":
      checkDetonationResult(value.detonation, index);
      break;
    case "mission.verdict":
      if (!["malicious", "suspicious", "legitimate"].includes(value.verdict as string)) {
        fail(index, `verdict: invalid value ${JSON.stringify(value.verdict)}`);
      }
      if (!isStr(value.summary)) fail(index, "summary: expected string");
      break;
    case "mission.approval_required":
      if (!GATE_INDICES.has(value.gate_index as number)) fail(index, "gate_index: expected 1-4");
      if (value.gate_count !== 4) fail(index, "gate_count: expected 4");
      if (
        !isRecord(value.action) ||
        !isStr(value.action.action) ||
        !isRecord(value.action.arguments)
      ) {
        fail(index, "action: expected {action, arguments}");
      }
      checkToolApprovalRequired(value.approval, index);
      break;
    case "mission.approval_resolved":
      if (!GATE_INDICES.has(value.gate_index as number)) fail(index, "gate_index: expected 1-4");
      if (value.status !== "allow" && value.status !== "deny") {
        fail(index, `status: expected allow|deny, got ${JSON.stringify(value.status)}`);
      }
      break;
    case "mission.action_executed":
      if (!GATE_INDICES.has(value.gate_index as number)) fail(index, "gate_index: expected 1-4");
      if (!isStr(value.action)) fail(index, "action: expected string");
      if (!isStr(value.result_summary)) fail(index, "result_summary: expected string");
      break;
    case "mission.complete":
      if (!isStr(value.spoken_verdict)) fail(index, "spoken_verdict: expected string");
      break;
  }

  return value as MissionEvent;
}

/**
 * Plays a fixture back one event at a time, a short delay apart, so the
 * consumer genuinely processes a sequence rather than receiving a static
 * array all at once - the same shape of consumption an SSE stream will
 * demand later.
 */
export function fixtureEventSource(events: unknown[], delayMs = 220): MissionEventSource {
  return async function* () {
    for (let i = 0; i < events.length; i++) {
      yield assertMissionEvent(events[i], i);
      if (delayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
  };
}
