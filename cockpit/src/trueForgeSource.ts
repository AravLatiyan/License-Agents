// Explicit .ts extension: `allowImportingTsExtensions` is on in
// tsconfig.app.json, Vite resolves it, and Node's --experimental-strip-types
// REQUIRES it — without the extension this module cannot be imported by the
// test runner at all (found by the T-039 test suite).
import { createTranslator } from "../../harness/translate/translate.ts";
// Value import, so it needs the explicit extension for the same reason as
// above. The type-only import below does not: type imports are erased before
// Node ever resolves them.
import { assertMissionEvent } from "./missionSource.ts";
import type { ApprovalStatus, MissionEvent, ToolApprovalResume } from "../../contracts/events";
import type { MissionEventSource } from "./missionSource";

/**
 * T-039: the live `trueForgeEventSource` that `missionSource.ts`'s own
 * docstring has named as the intended swap-in since T-050.
 *
 * T-037 built the translator; nothing consumed it. `App.tsx` still plays
 * `mission-happy-path.json` back, so every panel in this app has only ever
 * rendered a recording. This module is the missing half: it opens a real
 * TrueForge turn over HTTP/SSE, feeds each raw wire event through the
 * translator, and yields the resulting `mission.*` events in the exact shape
 * `useMissionEvents` already consumes.
 *
 * DISCLOSED CROSS-FOLDER: `cockpit/` is O3's. This file is new rather than an
 * edit to `missionSource.ts`, deliberately — it adds a second event source
 * beside the fixture one without touching the fixture path, so nothing O3
 * owns changes behaviour and the two can be swapped at the call site.
 *
 * What this does NOT do, on purpose:
 *
 * - **No reconnect/resume.** `resumableStream` (T-056) is built and tested and
 *   ready, but it needs an `after_sequence_number` cursor, and nothing in
 *   TrueForge's OpenAPI spec publishes a sequence number on any event body or
 *   list wrapper — event `id` is a monotonic ULID string. The cursor is most
 *   likely the SSE `id:` frame field, but that cannot be confirmed without
 *   watching a live turn, and guessing it would bake an unverified assumption
 *   into the demo path. `parseSseFrames` below *does* surface each frame's
 *   `id`, so wiring resume is a small change once one real turn has been
 *   observed (PLAN.md §8).
 * - **No approval submission.** Sending `user.tool_approval` back is T-036's
 *   live half and belongs to the cockpit's Allow/Deny buttons, not to a
 *   read-only event source.
 */

/** One parsed SSE frame. `id` is captured but deliberately unused — see the
 *  resume note above. */
export interface SseFrame {
  id: string | null;
  event: string | null;
  data: string;
}

/**
 * Parse a chunk of SSE text into complete frames, returning any trailing
 * partial frame so the caller can prepend it to the next chunk.
 *
 * Written as a pure function because a network stream hands you arbitrary
 * byte boundaries: a frame is routinely split across two chunks, and a naive
 * "split on \n\n" loses exactly the event that straddles the seam. Kept
 * separate from the fetch so it can be tested without a socket.
 */
export function parseSseFrames(buffer: string): { frames: SseFrame[]; rest: string } {
  // Frames are separated by a blank line. Normalise CRLF first: the spec
  // allows \r\n, \n, or \r as line endings and a real server may mix them.
  const normalised = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const parts = normalised.split("\n\n");
  // The final part is only complete if the buffer ended on a separator.
  const rest = parts.pop() ?? "";

  const frames: SseFrame[] = [];
  for (const part of parts) {
    let id: string | null = null;
    let event: string | null = null;
    const dataLines: string[] = [];

    for (const line of part.split("\n")) {
      if (line === "" || line.startsWith(":")) continue; // blank or comment/keep-alive
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      // Exactly one optional leading space after the colon is stripped, per spec.
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);

      if (field === "id") id = value;
      else if (field === "event") event = value;
      else if (field === "data") dataLines.push(value);
    }

    // A frame carrying no data field at all is a keep-alive, not an event.
    if (dataLines.length === 0) continue;
    frames.push({ id, event, data: dataLines.join("\n") });
  }

  return { frames, rest };
}

export interface TrueForgeSourceOptions {
  /** e.g. "http://localhost:8790/api/v1" */
  baseUrl: string;
  /** The agent to run, as registered from harness/agent.json. */
  agentName: string;
  /** The suspicious email to triage — passed as the turn's input text. */
  input: string;
  /** Injected so tests can drive this without a socket. Defaults to global fetch. */
  fetchImpl?: typeof fetch;
  /** Correlates every emitted event; defaults to the created session id. */
  missionId?: string;
}

/** Narrow a JSON body to an object with a string `id`, without trusting it. */
function idOf(value: unknown): string | null {
  if (typeof value !== "object" || value === null) return null;
  const id = (value as Record<string, unknown>).id;
  return typeof id === "string" ? id : null;
}

/**
 * Create a session, start a streaming turn, and yield translated
 * `mission.*` events.
 *
 * Every raw frame goes through the T-037 translator, which is the only thing
 * that knows how TrueForge's 12 generic event types map onto this app's
 * mission vocabulary — and which already refuses to emit the three events
 * that have no producer (identity evidence, verdict, approval_resolved).
 * Nothing is re-derived here.
 */
/**
 * A live mission: the read-only event source, plus the one write the cockpit
 * needs — submitting a human's licence decision.
 *
 * `MissionEventSource` is deliberately one-way and stays that way: it is O3's
 * type and every consumer of it assumes read-only. The submit path is returned
 * beside it instead, so nothing that already takes a `MissionEventSource` has
 * to change.
 */
export interface TrueForgeMission {
  source: MissionEventSource;
  /**
   * Resume the paused turn with a human's decision on one gate (T-046).
   *
   * TrueForge pauses the turn on the gated tool call itself; resuming means
   * POSTing a new turn whose input is a `ToolApprovalResume`. Returns the
   * events that decision produces locally — the `mission.approval_resolved`
   * the stream can never carry, plus whichever gate `resolveGate` releases
   * next. Returns `[]` before the session exists (nothing to resume yet).
   */
  submitApproval(decision: ApprovalDecision): Promise<MissionEvent[]>;
}

export interface ApprovalDecision {
  gateIndex: 1 | 2 | 3 | 4;
  threadId: string;
  toolCallId: string;
  status: ApprovalStatus;
  reason?: string;
}

export function createTrueForgeMission(options: TrueForgeSourceOptions): TrueForgeMission {
  const doFetch = options.fetchImpl ?? fetch;

  // Per-RUN state, not per-mission. The source generator is reusable and
  // React StrictMode invokes effects twice, so two runs can overlap; sharing
  // one sessionId/translator let a gate from one run resume against another
  // run's session (Qodo, PR #85). Each invocation installs its own run, and
  // `submitApproval` always targets the newest — which is the one whose
  // events the UI is actually showing.
  interface Run {
    sessionId: string;
    translator: ReturnType<typeof createTranslator>;
  }
  let currentRun: Run | null = null;

  const source: MissionEventSource = async function* () {
    // An AbortController tied to this generator's lifetime. `useMissionEvents`
    // signals cancellation by flipping a boolean, which cannot stop an
    // in-flight fetch — and React StrictMode invokes effects twice in dev, so
    // the documented `npm run dev` path would otherwise open a second
    // TrueForge session while the first request is still running and leave
    // that discarded connection live (Qodo, PR #80). Aborting in the `finally`
    // below closes it as soon as the consumer stops iterating, which is what
    // finalises an async generator.
    const abort = new AbortController();

    const sessionResponse = await doFetch(`${options.baseUrl}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent: { type: "reference", name: options.agentName } }),
      signal: abort.signal,
    });
    if (!sessionResponse.ok) {
      throw new Error(`could not create session: HTTP ${sessionResponse.status}`);
    }
    const sessionId = idOf(await sessionResponse.json());
    if (!sessionId) throw new Error("session response carried no id");

    const activeTranslator = createTranslator({ missionId: options.missionId ?? sessionId });
    const run: Run = { sessionId, translator: activeTranslator };
    currentRun = run;

    const turnResponse = await doFetch(`${options.baseUrl}/sessions/${sessionId}/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        stream: true,
        input: [{ type: "user.message", content: options.input }],
      }),
      signal: abort.signal,
    });
    if (!turnResponse.ok) {
      throw new Error(`could not start turn: HTTP ${turnResponse.status}`);
    }
    if (!turnResponse.body) throw new Error("turn response carried no stream body");

    const reader = turnResponse.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let index = 0; // position in the mission stream, for validation messages

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const { frames, rest } = parseSseFrames(buffer);
        buffer = rest;

        for (const frame of frames) {
          // "[DONE]" is the conventional SSE end-of-stream sentinel and is not
          // JSON — treat it as the close, not as a malformed event.
          if (frame.data === "[DONE]") return;

          let raw: unknown;
          try {
            raw = JSON.parse(frame.data);
          } catch {
            // One unreadable frame must not kill the mission: the translator
            // holds the same contract, and a live stream is allowed to be
            // messy. Skip it.
            continue;
          }

          for (const event of activeTranslator.push(raw)) {
            // The SAME runtime validation the fixture path applies. Skipping
            // it here had it backwards: fixture data is authored and trusted,
            // live data is neither, yet only the fixture was checked (Qodo,
            // PR #80). The translator drops malformed *input*, but it passes
            // an approval's raw `tool_calls` through verbatim for provenance,
            // so a partly-malformed approval could still reach cockpit state
            // in violation of its own contract.
            //
            // This throws rather than skipping, deliberately: the translator
            // is the resilience layer and already never throws, so anything
            // invalid arriving here is a translator defect, not bad network
            // input. Failing loudly beats a mission that silently renders
            // incomplete — `useMissionEvents` already surfaces it as an error
            // state, exactly as it does for the fixture.
            yield assertMissionEvent(event, index++);
          }
        }
      }
    } finally {
      // Both matter on early return (the [DONE] path, or a consumer that stops
      // iterating): releasing frees the reader, aborting actually closes the
      // underlying request so a discarded StrictMode run cannot keep a live
      // turn streaming behind the app.
      reader.releaseLock();
      abort.abort();
    }
  };

  /** Read an SSE body to completion, translating every frame. Shared by the
   *  first turn and by each resumed turn, so a resume is translated exactly
   *  like the stream it continues. */
  async function drainStream(body: ReadableStream<Uint8Array>, translator: Run["translator"]): Promise<MissionEvent[]> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let index = 0;
    const out: MissionEvent[] = [];
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { frames, rest } = parseSseFrames(buffer);
        buffer = rest;
        for (const frame of frames) {
          if (frame.data === "[DONE]") return out;
          let raw: unknown;
          try {
            raw = JSON.parse(frame.data);
          } catch {
            continue;
          }
          for (const event of translator.push(raw)) out.push(assertMissionEvent(event, index++));
        }
      }
    } finally {
      reader.releaseLock();
    }
    return out;
  }

  async function submitApproval(decision: ApprovalDecision): Promise<MissionEvent[]> {
    const run = currentRun;
    if (!run) return [];
    const currentSession = run.sessionId;
    const currentTranslator = run.translator;

    const resume: ToolApprovalResume = {
      type: "user.tool_approval",
      thread_id: decision.threadId,
      tool_call_id: decision.toolCallId,
      approval: decision.reason
        ? { status: decision.status, reason: decision.reason }
        : { status: decision.status },
    };

    // stream: true, because the resumed turn is where the ALLOWED ACTION
    // ACTUALLY RUNS. A non-streaming resume threw away the executed-action
    // result, any later gate the resumed model loop produces, failures, and
    // mission completion — so after clicking Allow the cockpit would sit
    // frozen on a mission that had in fact continued (Qodo, PR #85).
    const response = await doFetch(`${options.baseUrl}/sessions/${currentSession}/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ stream: true, input: [resume] }),
    });
    if (!response.ok) {
      throw new Error(`could not submit approval: HTTP ${response.status}`);
    }

    // The stream has no wire event for "a human decided" — the 12-type union
    // has nothing between tool.approval_required and the next turn.done — so
    // this event is constructed here, by the only code that knows the decision
    // was made because it just made it.
    const resolved: MissionEvent = {
      type: "mission.approval_resolved",
      mission_id: options.missionId ?? currentSession,
      gate_index: decision.gateIndex,
      status: decision.status,
      ...(decision.reason ? { reason: decision.reason } : {}),
    };

    // Releasing the next queued gate is the whole point of resolveGate, and
    // until now nothing in the app ever called it — so a mission with more
    // than one gate outstanding would show the first and silently withhold
    // the rest. This is that missing caller.
    const released = currentTranslator.resolveGate(decision.gateIndex);
    const resumed = response.body ? await drainStream(response.body, currentTranslator) : [];
    return [resolved, ...released, ...resumed];
  }

  return { source, submitApproval };
}

/**
 * Back-compat shim: the read-only source on its own, for callers that do not
 * need the submit path.
 */
export function trueForgeEventSource(options: TrueForgeSourceOptions): MissionEventSource {
  return createTrueForgeMission(options).source;
}
