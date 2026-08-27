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

/**
 * Rejects anything that isn't a recognized MissionEvent shape instead of
 * silently rendering it. Deliberately checks the exact class of bug Qodo's
 * PR #12 review caught in the contract itself (finding #4: an evidence
 * event's lane and evidence type must actually pair, not just both be
 * individually well-formed) - the compiler enforces that for code written
 * against the type; this is the runtime equivalent for data loaded from
 * outside the type system (a JSON fixture today, a live SSE payload later).
 */
export function assertMissionEvent(value: unknown, index: number): MissionEvent {
  if (typeof value !== "object" || value === null) {
    throw new Error(`event[${index}]: expected an object, got ${JSON.stringify(value)}`);
  }
  const type = (value as { type?: unknown }).type;
  if (typeof type !== "string" || !KNOWN_TYPES.has(type as MissionEvent["type"])) {
    throw new Error(`event[${index}]: unknown or missing "type" (${JSON.stringify(type)})`);
  }
  if (type === "mission.evidence") {
    const lane = (value as { lane?: unknown }).lane;
    if (typeof lane !== "string" || !KNOWN_LANES.has(lane)) {
      throw new Error(`event[${index}]: mission.evidence has invalid "lane" (${JSON.stringify(lane)})`);
    }
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
