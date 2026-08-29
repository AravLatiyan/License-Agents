// cockpit/src/trueForgeSource.test.ts
//
// Tests for T-039's `trueForgeEventSource` and its `parseSseFrames` helper.
// Two things are exercised separately, on purpose:
//
// 1. `parseSseFrames` is a pure string -> frames function. It gets hammered
//    directly with no fetch involved, because the one bug that actually
//    matters here - losing a frame that straddles a chunk boundary - is
//    entirely a string-parsing concern.
// 2. `trueForgeEventSource` is driven end-to-end through an injected
//    `fetchImpl`, the same seam the module was built with so it never needs
//    a socket. The translator underneath (harness/translate/translate.ts,
//    see its own test file for tone) is trusted to do its own job correctly;
//    these tests only check that raw frames actually reach it and that its
//    output actually reaches the consumer, missionId gets stamped right, and
//    the fetch/stream plumbing (chunk splitting, [DONE], bad JSON, non-ok
//    responses) fails the way the module's own comments say it should.

import { test } from "node:test";
import assert from "node:assert/strict";
import type { MissionEvent } from "../../contracts/events.ts";

// --- module load: see the dedicated test just below before reading further ---
//
// trueForgeSource.ts imports its translator as
// `../../harness/translate/translate` - no file extension. Node's native
// ESM loader (which is what `--experimental-strip-types` runs on top of)
// requires every relative specifier to carry its extension; it does not
// fall back to trying `.ts`. That makes this a real, load-time bug in the
// module under test: as of this writing it cannot be imported at all by
// the exact runner this suite is required to use, independent of anything
// this test file does. It is not something a test file can work around
// (there is no supported way to tell Node's loader to guess the
// extension) and it is not this suite's bug to fix - see the docstring at
// the top of this file's task brief: report it, don't patch it.
//
// The import is therefore done dynamically and defensively here, once, so
// that (a) the failure itself becomes one clear, named, passing assertion
// instead of aborting the whole file with no test output at all, and (b)
// every other test below - which still exercises real, meaningful
// contracts of this module's source - can report itself as "skipped
// because of the load bug" rather than failing in a way that looks like a
// problem with that individual test.
let parseSseFrames: typeof import("./trueForgeSource.ts").parseSseFrames;
let trueForgeEventSource: typeof import("./trueForgeSource.ts").trueForgeEventSource;
let loadError: unknown;
try {
  const mod = await import("./trueForgeSource.ts");
  parseSseFrames = mod.parseSseFrames;
  trueForgeEventSource = mod.trueForgeEventSource;
} catch (err) {
  loadError = err;
}

// The module must stay importable by Node's type stripper, not just by Vite
// and tsc. It briefly was not: the import of the T-037 translator omitted the
// .ts extension, which bundlers resolve happily and --experimental-strip-types
// refuses outright, so this whole suite could not load. `allowImportingTsExtensions`
// is already on in tsconfig.app.json, so the explicit extension costs nothing
// and keeps the module testable.
test("trueForgeSource.ts is importable under --experimental-strip-types", () => {
  assert.equal(loadError, undefined, `module failed to load: ${String(loadError)}`);
  assert.equal(typeof parseSseFrames, "function");
  assert.equal(typeof trueForgeEventSource, "function");
});

// ---------------------------------------------------------------------------
// A. parseSseFrames
// ---------------------------------------------------------------------------

test("a single complete frame yields one frame and empty rest", () => {
  const { frames, rest } = parseSseFrames('data: {"a":1}\n\n');
  assert.equal(frames.length, 1);
  assert.equal(frames[0].data, '{"a":1}');
  assert.equal(rest, "");
});

test("two frames in one buffer yield two frames in order", () => {
  const { frames, rest } = parseSseFrames('data: {"a":1}\n\ndata: {"a":2}\n\n');
  assert.equal(frames.length, 2);
  assert.equal(frames[0].data, '{"a":1}');
  assert.equal(frames[1].data, '{"a":2}');
  assert.equal(rest, "");
});

test("a trailing partial frame is returned as rest, not emitted", () => {
  // The important case: a network chunk can split mid-frame. A naive
  // "split on \n\n" would either drop the straddling event or emit it half
  // -formed. parseSseFrames must hold it back as `rest` instead.
  const { frames, rest } = parseSseFrames('data: {"a":1}\n\ndata: {"a":2}');
  assert.equal(frames.length, 1);
  assert.equal(frames[0].data, '{"a":1}');
  assert.equal(rest, 'data: {"a":2}');

  // Feeding rest + the rest of the frame back in must recover it intact.
  const second = parseSseFrames(rest + '\n\n');
  assert.equal(second.frames.length, 1);
  assert.equal(second.frames[0].data, '{"a":2}');
  assert.equal(second.rest, "");
});

test("id: and event: fields are captured onto the frame", () => {
  const { frames } = parseSseFrames("id: evt-1\nevent: model.message\ndata: {}\n\n");
  assert.equal(frames.length, 1);
  assert.equal(frames[0].id, "evt-1");
  assert.equal(frames[0].event, "model.message");
  assert.equal(frames[0].data, "{}");
});

test("exactly one leading space after the colon is stripped, a second is kept", () => {
  const oneSpace = parseSseFrames("data: x\n\n");
  assert.equal(oneSpace.frames[0].data, "x");

  const twoSpaces = parseSseFrames("data:  x\n\n");
  assert.equal(twoSpaces.frames[0].data, " x");
});

test("CRLF and bare CR line endings parse the same as LF", () => {
  const crlf = parseSseFrames('data: {"a":1}\r\n\r\n');
  assert.equal(crlf.frames.length, 1);
  assert.equal(crlf.frames[0].data, '{"a":1}');

  const cr = parseSseFrames('data: {"a":1}\r\r');
  assert.equal(cr.frames.length, 1);
  assert.equal(cr.frames[0].data, '{"a":1}');
});

test("comment / keep-alive lines starting with a colon are ignored", () => {
  const { frames } = parseSseFrames(": keep-alive\ndata: {}\n\n");
  assert.equal(frames.length, 1);
  assert.equal(frames[0].data, "{}");
});

test("a frame with no data field at all is skipped entirely", () => {
  const commentOnly = parseSseFrames(": keep-alive\n\n");
  assert.deepEqual(commentOnly.frames, []);

  const idOnly = parseSseFrames("id: evt-1\n\n");
  assert.deepEqual(idOnly.frames, []);
});

test("multi-line data: fields are joined with a newline", () => {
  const { frames } = parseSseFrames("data: line one\ndata: line two\n\n");
  assert.equal(frames.length, 1);
  assert.equal(frames[0].data, "line one\nline two");
});

test("an empty buffer yields no frames and empty rest", () => {
  const { frames, rest } = parseSseFrames("");
  assert.deepEqual(frames, []);
  assert.equal(rest, "");
});

// ---------------------------------------------------------------------------
// B. trueForgeEventSource
// ---------------------------------------------------------------------------

/** Build a ReadableStream<Uint8Array> from string chunks, mirroring what a
 *  real fetch() response body would hand back piece by piece. */
function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

/** Turn a series of {event?, data} frame descriptions into raw SSE text,
 *  so test bodies read as "here are the frames" rather than raw wire text. */
function sseText(frames: Array<{ event?: string; data: unknown }>): string {
  return frames
    .map((f) => {
      const lines: string[] = [];
      if (f.event) lines.push(`event: ${f.event}`);
      const data = typeof f.data === "string" ? f.data : JSON.stringify(f.data);
      lines.push(`data: ${data}`);
      return lines.join("\n") + "\n\n";
    })
    .join("");
}

function okJsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

function okStreamResponse(body: ReadableStream<Uint8Array>): Response {
  return { ok: true, status: 200, body } as unknown as Response;
}

/** A complete ParsedMessage (all nine fields) - the translator's own guard
 *  (isParsedMessage in harness/translate/translate.ts) drops anything
 *  short of this, so the happy-path fixture has to be fully-formed to
 *  actually produce a mission.message_received event. */
const FULL_PARSED_MESSAGE = {
  message_id: "m1",
  from: "a@example.com",
  reply_to: null,
  return_path: null,
  display_name: null,
  authentication_results: "dmarc=fail",
  received_chain: [],
  urls: [],
  attachments: [],
};

/** Fetch stub factory: first call is the session POST, second is the turn
 *  POST whose body is the given stream. Records calls made so a test can
 *  assert on request shape if it needs to (none currently do, but the shape
 *  mirrors how the module actually calls fetch). */
function fetchStub(sessionBody: unknown, turnResponse: Response) {
  let call = 0;
  const fetchImpl = (async () => {
    call += 1;
    if (call === 1) return okJsonResponse(sessionBody);
    if (call === 2) return turnResponse;
    throw new Error(`fetchStub called more than twice (call ${call})`);
  }) as unknown as typeof fetch;
  return fetchImpl;
}

async function collect(source: () => AsyncIterable<MissionEvent>): Promise<MissionEvent[]> {
  const out: MissionEvent[] = [];
  for await (const event of source()) out.push(event);
  return out;
}

test("happy path: raw TrueForge frames translate into mission.message_received then mission.complete", async () => {
  const modelMessage = {
    type: "model.message",
    id: "evt-1",
    thread_id: "main",
    tool_calls: [
      {
        id: "call-1",
        type: "function",
        // NOTE: function.arguments is a JSON-encoded STRING on the wire, not
        // an object - the translator only accepts it in that shape.
        function: { name: "parse_message", arguments: "{}" },
      },
    ],
  };
  const toolResponse = {
    type: "tool.response",
    id: "evt-2",
    thread_id: "main",
    tool_call_id: "call-1",
    content: JSON.stringify(FULL_PARSED_MESSAGE),
  };
  const turnDone = {
    type: "turn.done",
    state: {
      status: "done",
      required_actions: [],
      output: { type: "model.message", content: "All clear." },
    },
  };

  const body = streamOf([sseText([{ data: modelMessage }, { data: toolResponse }, { data: turnDone }])]);
  const fetchImpl = fetchStub({ id: "sess-1" }, okStreamResponse(body));

  const source = trueForgeEventSource({
    baseUrl: "http://localhost:8790/api/v1",
    agentName: "triage",
    input: "suspicious email text",
    fetchImpl,
  });

  const events = await collect(source);

  assert.deepEqual(events, [
    { type: "mission.message_received", mission_id: "sess-1", message: FULL_PARSED_MESSAGE },
    { type: "mission.complete", mission_id: "sess-1", spoken_verdict: "All clear." },
  ]);
});

test("mission_id defaults to the session id when no missionId option is passed", async () => {
  const turnDone = {
    type: "turn.done",
    state: { status: "done", required_actions: [], output: { type: "model.message", content: "done" } },
  };
  const body = streamOf([sseText([{ data: turnDone }])]);
  const fetchImpl = fetchStub({ id: "sess-abc" }, okStreamResponse(body));

  const source = trueForgeEventSource({ baseUrl: "http://x", agentName: "a", input: "i", fetchImpl });
  const events = await collect(source);

  assert.equal(events.length, 1);
  assert.equal(events[0].mission_id, "sess-abc");
});

test("mission_id uses the override when a missionId option is passed", async () => {
  const turnDone = {
    type: "turn.done",
    state: { status: "done", required_actions: [], output: { type: "model.message", content: "done" } },
  };
  const body = streamOf([sseText([{ data: turnDone }])]);
  const fetchImpl = fetchStub({ id: "sess-abc" }, okStreamResponse(body));

  const source = trueForgeEventSource({
    baseUrl: "http://x",
    agentName: "a",
    input: "i",
    fetchImpl,
    missionId: "mission-override",
  });
  const events = await collect(source);

  assert.equal(events.length, 1);
  assert.equal(events[0].mission_id, "mission-override");
});

test("a frame split across two network chunks still produces its event", async () => {
  const turnDone = {
    type: "turn.done",
    state: { status: "done", required_actions: [], output: { type: "model.message", content: "split ok" } },
  };
  const whole = sseText([{ data: turnDone }]);
  // Split mid-frame, at an arbitrary point well inside the data line.
  const cut = Math.floor(whole.length / 2);
  const body = streamOf([whole.slice(0, cut), whole.slice(cut)]);
  const fetchImpl = fetchStub({ id: "sess-1" }, okStreamResponse(body));

  const source = trueForgeEventSource({ baseUrl: "http://x", agentName: "a", input: "i", fetchImpl });
  const events = await collect(source);

  assert.deepEqual(events, [{ type: "mission.complete", mission_id: "sess-1", spoken_verdict: "split ok" }]);
});

test("data: [DONE] ends the stream cleanly without error", async () => {
  const turnDone = {
    type: "turn.done",
    state: { status: "done", required_actions: [], output: { type: "model.message", content: "wrapped up" } },
  };
  // [DONE] arrives after a real event but before the stream's own close -
  // the module must treat it as the end of iteration, not a parse failure.
  const body = streamOf([sseText([{ data: turnDone }]) + "data: [DONE]\n\n"]);
  const fetchImpl = fetchStub({ id: "sess-1" }, okStreamResponse(body));

  const source = trueForgeEventSource({ baseUrl: "http://x", agentName: "a", input: "i", fetchImpl });
  const events = await collect(source);

  assert.deepEqual(events, [{ type: "mission.complete", mission_id: "sess-1", spoken_verdict: "wrapped up" }]);
});

test("a frame whose data is not valid JSON is skipped; later valid frames still arrive", async () => {
  const turnDone = {
    type: "turn.done",
    state: { status: "done", required_actions: [], output: { type: "model.message", content: "still fine" } },
  };
  // One malformed frame must not kill the mission - the module's own
  // comment says exactly this ("one unreadable frame must not kill the
  // mission").
  const body = streamOf(["data: { not valid json at all\n\n", sseText([{ data: turnDone }])]);
  const fetchImpl = fetchStub({ id: "sess-1" }, okStreamResponse(body));

  const source = trueForgeEventSource({ baseUrl: "http://x", agentName: "a", input: "i", fetchImpl });
  const events = await collect(source);

  assert.deepEqual(events, [{ type: "mission.complete", mission_id: "sess-1", spoken_verdict: "still fine" }]);
});

test("a non-ok session response throws with a message mentioning the status", async () => {
  const fetchImpl = (async () => ({ ok: false, status: 503 }) as unknown as Response) as unknown as typeof fetch;

  const source = trueForgeEventSource({ baseUrl: "http://x", agentName: "a", input: "i", fetchImpl });
  await assert.rejects(collect(source), /503/);
});

test("a non-ok turn response throws", async () => {
  let call = 0;
  const fetchImpl = (async () => {
    call += 1;
    if (call === 1) return okJsonResponse({ id: "sess-1" });
    return { ok: false, status: 500 } as unknown as Response;
  }) as unknown as typeof fetch;

  const source = trueForgeEventSource({ baseUrl: "http://x", agentName: "a", input: "i", fetchImpl });
  await assert.rejects(collect(source), /500/);
});

test("a session response with no string id throws", async () => {
  const fetchImpl = (async () => okJsonResponse({ notAnId: 123 })) as unknown as typeof fetch;

  const source = trueForgeEventSource({ baseUrl: "http://x", agentName: "a", input: "i", fetchImpl });
  await assert.rejects(collect(source));
});

// ---------------------------------------------------------------------------
// C. The two defects Qodo found on PR #80
// ---------------------------------------------------------------------------

/** A fetch that records the AbortSignal it was handed, so a test can observe
 *  whether the source actually cancels its own request. */
function recordingFetch(sse: string, seen: { signals: (AbortSignal | undefined)[] }) {
  let call = 0;
  return (async (_url: string, init?: RequestInit) => {
    seen.signals.push(init?.signal ?? undefined);
    call += 1;
    if (call === 1) {
      return { ok: true, status: 200, json: async () => ({ id: "sess-1" }) } as unknown as Response;
    }
    return { ok: true, status: 200, body: streamOf([sse]) } as unknown as Response;
  }) as unknown as typeof fetch;
}

// React StrictMode invokes effects twice in dev, and useMissionEvents cancels
// by flipping a boolean, which cannot stop an in-flight fetch. Without a
// signal the discarded run keeps a real TrueForge turn streaming behind the
// app - and on a metered model provider that is a second billed run.
test("the request carries an AbortSignal and is aborted when iteration stops early", async () => {
  const seen: { signals: (AbortSignal | undefined)[] } = { signals: [] };
  const sse = sseText([
    { data: { type: "turn.created", id: "e0", turn_id: "t1", previous_turn_id: null, state: { status: "running" }, thread_id: null } },
    { data: { type: "turn.done", state: { status: "done", required_actions: [], output: { type: "model.message", content: "done" }, completed_at: "t" } } },
  ]);

  const source = trueForgeEventSource({
    baseUrl: "http://x/api/v1",
    agentName: "universal-imports",
    input: "raw email",
    fetchImpl: recordingFetch(sse, seen),
  });

  // Stop after the first event, the way an unmounting consumer does.
  for await (const _event of source()) break;

  assert.ok(seen.signals.length >= 1, "fetch should have been called");
  for (const signal of seen.signals) {
    assert.ok(signal instanceof AbortSignal, "every request must carry an abort signal");
  }
  assert.ok(
    seen.signals.every((s) => s?.aborted),
    "leaving the loop early must abort the in-flight request, not leave it streaming",
  );
});

// Fixture playback runs every event through assertMissionEvent; the live path
// did not. That had it backwards - fixture data is authored and trusted, live
// data is neither. The translator drops malformed *input*, but it passes an
// approval's raw tool_calls through verbatim for provenance, so a partly
// malformed approval could still reach cockpit state.
test("live events are validated at the boundary, like fixture events are", async () => {
  // An approval whose tool_calls array carries a valid ref plus a malformed
  // sibling. The translator resolves the good one and emits, keeping the raw
  // array on `approval` - which the cockpit's own validator rejects.
  const sse = sseText([
    {
      data: {
        type: "model.message",
        id: "mm-1",
        thread_id: "main",
        tool_calls: [{ id: "call-1", type: "function", function: { name: "quarantine", arguments: "{}" } }],
      },
    },
    {
      data: {
        type: "tool.approval_required",
        id: "appr-1",
        created_at: "2026-08-30T00:00:00Z",
        thread_id: "main",
        tool_calls: [{ id: "call-1", source_event_id: "mm-1" }, { nonsense: true }],
      },
    },
  ]);

  const source = trueForgeEventSource({
    baseUrl: "http://x/api/v1",
    agentName: "universal-imports",
    input: "raw email",
    fetchImpl: recordingFetch(sse, { signals: [] }),
  });

  await assert.rejects(
    async () => {
      for await (const _event of source()) {
        // drain
      }
    },
    /approval\.tool_calls/,
    "a malformed approval payload must be caught by the same validator the fixture path uses",
  );
});
