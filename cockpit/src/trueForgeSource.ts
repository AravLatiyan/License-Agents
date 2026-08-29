// Explicit .ts extension: `allowImportingTsExtensions` is on in
// tsconfig.app.json, Vite resolves it, and Node's --experimental-strip-types
// REQUIRES it — without the extension this module cannot be imported by the
// test runner at all (found by the T-039 test suite).
import { createTranslator } from "../../harness/translate/translate.ts";
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
export function trueForgeEventSource(options: TrueForgeSourceOptions): MissionEventSource {
  const doFetch = options.fetchImpl ?? fetch;

  return async function* () {
    const sessionResponse = await doFetch(`${options.baseUrl}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent: { type: "reference", name: options.agentName } }),
    });
    if (!sessionResponse.ok) {
      throw new Error(`could not create session: HTTP ${sessionResponse.status}`);
    }
    const sessionId = idOf(await sessionResponse.json());
    if (!sessionId) throw new Error("session response carried no id");

    const translator = createTranslator({ missionId: options.missionId ?? sessionId });

    const turnResponse = await doFetch(`${options.baseUrl}/sessions/${sessionId}/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        stream: true,
        input: [{ type: "user.message", content: options.input }],
      }),
    });
    if (!turnResponse.ok) {
      throw new Error(`could not start turn: HTTP ${turnResponse.status}`);
    }
    if (!turnResponse.body) throw new Error("turn response carried no stream body");

    const reader = turnResponse.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

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

          for (const event of translator.push(raw)) {
            yield event;
          }
        }
      }
    } finally {
      // Releasing matters on early return (the [DONE] path, or a consumer that
      // stops iterating) — without it the socket stays open behind the app.
      reader.releaseLock();
    }
  };
}
