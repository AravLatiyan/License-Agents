// harness/translate/translate.test.ts
//
// Tests for the raw-TrueForge-stream -> MissionEvent translator (T-037),
// written against the spec rather than against the implementation — the
// suite was authored concurrently with translate.ts, without reading it,
// so it checks the contract rather than mirroring the code. Do not
// weaken an assertion here to match what translate.ts happens to do —
// if the implementation disagrees with a test below, the implementation
// is what's wrong, per the same "shape source of truth" discipline
// contracts/events.ts documents in its own MAINTENANCE note.
//
// Two structural things this file leans on hard, both called out in
// contracts/events.ts:
//
// 1. TrueForge's `tool.approval_required` never repeats the tool name or
//    arguments — only `{id, source_event_id}`. A translator MUST resolve
//    both by walking back to the `model.message` named by `source_event_id`
//    and matching `tool_calls[].id`. Every approval-related test below
//    therefore pushes the originating `model.message` first.
//
// 2. `push()` must never throw. TrueForge is a live SSE stream; a bad frame
//    on the wire is a "drop it" problem, never a "crash the mission" one.
//    The regression tests at the bottom hammer this with garbage input.

import { test } from "node:test";
import assert from "node:assert/strict";
import { createTranslator } from "./translate.ts";
import type { MissionEvent } from "../../contracts/events.ts";

// ---------------------------------------------------------------------------
// Small builders for raw TrueForge wire shapes, so each test reads as
// "given this frame, expect this MissionEvent" rather than repeating
// boilerplate JSON.
// ---------------------------------------------------------------------------

function toolCall(id: string, name: string, args: unknown) {
  return { id, type: "function", function: { name, arguments: JSON.stringify(args) } };
}

function rawToolCall(id: string, name: string, rawArguments: string) {
  return { id, type: "function", function: { name, arguments: rawArguments } };
}

function modelMessage(id: string, threadId: string, calls: unknown[]) {
  return { type: "model.message", id, thread_id: threadId, tool_calls: calls };
}

function ref(id: string, sourceEventId: string) {
  return { id, source_event_id: sourceEventId };
}

function approvalRequired(id: string, threadId: string, refs: unknown[]) {
  return {
    type: "tool.approval_required",
    id,
    created_at: "2026-08-29T00:00:00Z",
    thread_id: threadId,
    tool_calls: refs,
  };
}

function toolResponse(id: string, threadId: string, toolCallId: string, content: string) {
  return { type: "tool.response", id, thread_id: threadId, tool_call_id: toolCallId, content };
}

function turnDone(state: unknown) {
  return { type: "turn.done", state };
}

const MISSION_ID = "mission-test-001";

// ---------------------------------------------------------------------------
// 1. Ignored event types and malformed input -> always []
// ---------------------------------------------------------------------------

test("ignored TrueForge event types translate to []", async (t) => {
  const ignoredTypes = [
    "turn.created",
    "thread.created",
    "thread.done",
    "mcp.initialize",
    "mcp.auth_required",
    "sandbox.created",
    "tool.response_required",
    "model.message.delta",
    "some.future.event.type.we.have.never.seen", // unknown type
  ];

  for (const type of ignoredTypes) {
    await t.test(`"${type}" -> []`, () => {
      const translator = createTranslator({ missionId: MISSION_ID });
      const result = translator.push({ type, id: "evt-1", thread_id: "main" });
      assert.deepEqual(result, []);
    });
  }
});

test("malformed / non-event input translates to [] instead of throwing", async (t) => {
  // These are the shapes a real SSE parser could plausibly hand back on a
  // bad frame: no `type` at all, or not an object in the first place.
  const malformed: unknown[] = [
    null,
    undefined,
    "just a string",
    42,
    {},
    { foo: "bar" }, // object with fields, but no `type` key
  ];

  for (const raw of malformed) {
    await t.test(`push(${JSON.stringify(raw)}) -> []`, () => {
      const translator = createTranslator({ missionId: MISSION_ID });
      assert.doesNotThrow(() => translator.push(raw));
      assert.deepEqual(translator.push(raw), []);
    });
  }
});

// ---------------------------------------------------------------------------
// 2. model.message: records tool calls for later resolution, emits nothing
// ---------------------------------------------------------------------------

test("model.message records tool calls but itself emits nothing", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  const result = translator.push(
    modelMessage("evt-1", "main", [toolCall("call-1", "quarantine", { message_ids: ["m1"] })]),
  );
  assert.deepEqual(result, []);
});

// ---------------------------------------------------------------------------
// 3. tool.approval_required
// ---------------------------------------------------------------------------

test("tool.approval_required resolves name+arguments from the earlier model.message", () => {
  const translator = createTranslator({ missionId: MISSION_ID });

  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "quarantine", { message_ids: ["m1"] })]));

  const result = translator.push(approvalRequired("evt-2", "main", [ref("call-1", "evt-1")]));

  assert.equal(result.length, 1);
  const event = result[0] as Extract<MissionEvent, { type: "mission.approval_required" }>;
  assert.equal(event.type, "mission.approval_required");
  assert.equal(event.mission_id, MISSION_ID);
  assert.equal(event.gate_index, 1);
  assert.equal(event.gate_count, 4);
  assert.deepEqual(event.action, { action: "quarantine", arguments: { message_ids: ["m1"] } });
  // The raw wire event is kept verbatim for provenance (contracts/events.ts
  // ApprovalRequiredEvent doc comment) — not re-derived or reshaped.
  assert.deepEqual(event.approval, approvalRequired("evt-2", "main", [ref("call-1", "evt-1")]));
});

test("gate_index increments 1,2,3,4 across four successive approvals, then a fifth is dropped", () => {
  const translator = createTranslator({ missionId: MISSION_ID });

  const actions: Array<[string, string, Record<string, unknown>]> = [
    ["call-1", "quarantine", { message_ids: ["m1"] }],
    ["call-2", "notify_impersonated", { address: "real@example.com" }],
    ["call-3", "create_block_rule", { pattern: "*@evil.example.com" }],
    ["call-4", "file_abuse_report", { domain: "evil.example.com" }],
  ];

  actions.forEach(([callId, name, args], i) => {
    translator.push(modelMessage(`mm-${i}`, "main", [toolCall(callId, name, args)]));
  });

  // Only one gate is ever outstanding at a time (Qodo, PR #73/#74) - each
  // approval_required still only produces an event once the previous gate
  // has been resolved via resolveGate().
  const gateIndexes: unknown[] = [];
  actions.forEach(([callId], i) => {
    const result = translator.push(approvalRequired(`appr-${i}`, "main", [ref(callId, `mm-${i}`)]));
    assert.equal(result.length, 1, `approval ${i} should produce exactly one event`);
    const gateIndex = (result[0] as { gate_index: 1 | 2 | 3 | 4 }).gate_index;
    gateIndexes.push(gateIndex);
    const released = translator.resolveGate(gateIndex);
    assert.deepEqual(released, [], `no gate ${i + 2} exists yet to release`);
  });

  assert.deepEqual(gateIndexes, [1, 2, 3, 4]);

  // A fifth gated approval has nowhere to go: ApprovalRequiredEvent.gate_index
  // is typed 1|2|3|4 in contracts/events.ts, so a translator that assigned 5
  // would be lying about the contract. The only honest move is to drop it.
  translator.push(modelMessage("mm-5", "main", [toolCall("call-5", "quarantine", { message_ids: ["m2"] })]));
  const fifth = translator.push(approvalRequired("appr-5", "main", [ref("call-5", "mm-5")]));
  assert.deepEqual(fifth, []);
});

test("one tool.approval_required carrying several gated calls emits only the first (Qodo, PR #73/#74)", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("mm-1", "main", [toolCall("call-1", "quarantine", { message_ids: ["m1"] })]));
  translator.push(modelMessage("mm-2", "main", [toolCall("call-2", "notify_impersonated", {})]));
  translator.push(modelMessage("mm-3", "main", [toolCall("call-3", "create_block_rule", {})]));

  const result = translator.push(
    approvalRequired("appr-1", "main", [
      ref("call-1", "mm-1"),
      ref("call-2", "mm-2"),
      ref("call-3", "mm-3"),
    ]),
  );

  // Gate 1 is emitted immediately; gates 2 and 3 are assigned (arrival
  // order) but queued, not emitted - the cockpit must never see more than
  // one LICENCE REQUIRED panel at a time.
  assert.equal(result.length, 1);
  assert.equal((result[0] as { gate_index: number }).gate_index, 1);

  const afterFirstResolve = translator.resolveGate(1);
  assert.equal(afterFirstResolve.length, 1);
  assert.equal((afterFirstResolve[0] as { gate_index: number }).gate_index, 2);

  const afterSecondResolve = translator.resolveGate(2);
  assert.equal(afterSecondResolve.length, 1);
  assert.equal((afterSecondResolve[0] as { gate_index: number }).gate_index, 3);

  const afterThirdResolve = translator.resolveGate(3);
  assert.deepEqual(afterThirdResolve, []); // nothing left queued
});

test("a gate arriving while another is still outstanding queues, even across separate tool.approval_required events", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("mm-1", "main", [toolCall("call-1", "quarantine", { message_ids: ["m1"] })]));
  translator.push(modelMessage("mm-2", "main", [toolCall("call-2", "notify_impersonated", {})]));

  const first = translator.push(approvalRequired("appr-1", "main", [ref("call-1", "mm-1")]));
  assert.equal(first.length, 1);
  assert.equal((first[0] as { gate_index: number }).gate_index, 1);

  // Gate 1 is still outstanding (never resolved) - a second, independent
  // approval_required arriving now must still queue, not emit.
  const second = translator.push(approvalRequired("appr-2", "main", [ref("call-2", "mm-2")]));
  assert.deepEqual(second, []);

  const released = translator.resolveGate(1);
  assert.equal(released.length, 1);
  assert.equal((released[0] as { gate_index: number }).gate_index, 2);
});

test("resolveGate with a stale or mismatched gate_index is a no-op", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("mm-1", "main", [toolCall("call-1", "quarantine", { message_ids: ["m1"] })]));
  translator.push(approvalRequired("appr-1", "main", [ref("call-1", "mm-1")]));

  // No gate 2 exists yet (nothing queued) - resolving it must not throw or
  // release the still-outstanding gate 1.
  assert.deepEqual(translator.resolveGate(2), []);
  // Gate 1 is genuinely resolved next - proves the no-op above didn't
  // silently clear activeGateIndex.
  translator.push(modelMessage("mm-2", "main", [toolCall("call-2", "notify_impersonated", {})]));
  const second = translator.push(approvalRequired("appr-2", "main", [ref("call-2", "mm-2")]));
  assert.deepEqual(second, []); // still queued - gate 1 was never actually released
  const released = translator.resolveGate(1);
  assert.equal((released[0] as { gate_index: number }).gate_index, 2);
});

test("an approval for a non-gated tool name is skipped", () => {
  // domain_intel is a real tool but never one of the four irreversible
  // actions CLAUDE.md's "four sequential gates" design calls for. If it ever
  // showed up behind tool.approval_required that would be a harness bug, not
  // something the cockpit should be asked to render a licence panel for.
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "domain_intel", { domain: "example.com" })]));
  const result = translator.push(approvalRequired("evt-2", "main", [ref("call-1", "evt-1")]));
  assert.deepEqual(result, []);
});

test("an approval referencing an unknown tool_call id is skipped", () => {
  // No model.message ever registered "call-ghost" — e.g. a reconnect that
  // resumed the stream after the model.message but the approval's
  // source_event_id points somewhere this translator instance never saw.
  const translator = createTranslator({ missionId: MISSION_ID });
  const result = translator.push(approvalRequired("evt-1", "main", [ref("call-ghost", "evt-missing")]));
  assert.deepEqual(result, []);
});

test("malformed arguments JSON on the model.message degrades to {} rather than throwing", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [rawToolCall("call-1", "quarantine", "{not valid json")]));

  let result: MissionEvent[] = [];
  assert.doesNotThrow(() => {
    result = translator.push(approvalRequired("evt-2", "main", [ref("call-1", "evt-1")]));
  });

  assert.equal(result.length, 1);
  const event = result[0] as Extract<MissionEvent, { type: "mission.approval_required" }>;
  assert.deepEqual(event.action, { action: "quarantine", arguments: {} });
});

// ---------------------------------------------------------------------------
// 4. tool.response: dispatch by the tool name resolved from tool_call_id
// ---------------------------------------------------------------------------

test("tool.response for parse_message -> mission.message_received", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "parse_message", {})]));

  const parsed = {
    message_id: "m1",
    from: "a@example.com",
    reply_to: null,
    return_path: null,
    display_name: null,
    authentication_results: "",
    received_chain: [],
    urls: [],
    attachments: [],
  };
  const result = translator.push(toolResponse("evt-2", "main", "call-1", JSON.stringify(parsed)));

  assert.equal(result.length, 1);
  assert.deepEqual(result[0], { type: "mission.message_received", mission_id: MISSION_ID, message: parsed });
});

test("tool.response for parse_message with a malformed payload -> [] instead of a bogus mission event", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "parse_message", {})]));

  // Missing every ParsedMessage field except message_id/from - parses as
  // JSON, but is not a well-formed ParsedMessage (Qodo, PR #73 finding #1).
  const result = translator.push(
    toolResponse("evt-2", "main", "call-1", JSON.stringify({ message_id: "m1", from: "a@example.com" })),
  );

  assert.deepEqual(result, []);
});

test("tool.response for domain_intel -> mission.evidence in the infrastructure lane", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "domain_intel", { domain: "evil.example.com" })]));

  const evidence = { domain: "evil.example.com", registration_date: null, registrar: null, abuse_contact: null, cert_issued_at: null };
  const result = translator.push(toolResponse("evt-2", "main", "call-1", JSON.stringify(evidence)));

  assert.equal(result.length, 1);
  assert.deepEqual(result[0], { type: "mission.evidence", mission_id: MISSION_ID, lane: "infrastructure", evidence });
});

test("tool.response for url_reputation -> mission.evidence in the infrastructure lane", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "url_reputation", { url: "hxxps://evil.example.com" })]));

  const evidence = { url: "hxxps://evil.example.com", listed: false, tags: [] };
  const result = translator.push(toolResponse("evt-2", "main", "call-1", JSON.stringify(evidence)));

  assert.equal(result.length, 1);
  assert.deepEqual(result[0], { type: "mission.evidence", mission_id: MISSION_ID, lane: "infrastructure", evidence });
});

test("tool.response for correspondence_history -> mission.evidence in the history lane", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "correspondence_history", { address: "a@example.com" })]));

  const evidence = { address: "a@example.com", domain: "example.com", prior_contact_count: 3, first_seen: null, last_seen: null, domains_used: [] };
  const result = translator.push(toolResponse("evt-2", "main", "call-1", JSON.stringify(evidence)));

  assert.equal(result.length, 1);
  assert.deepEqual(result[0], { type: "mission.evidence", mission_id: MISSION_ID, lane: "history", evidence });
});

test("tool.response for detonate -> mission.detonation", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "detonate", { url: "hxxps://evil.example.com" })]));

  const detonation = { url: "hxxps://evil.example.com", redirect_chain: [], error: "dns-timeout" };
  const result = translator.push(toolResponse("evt-2", "main", "call-1", JSON.stringify(detonation)));

  assert.equal(result.length, 1);
  assert.deepEqual(result[0], { type: "mission.detonation", mission_id: MISSION_ID, detonation });
});

test("tool.response for a gated action -> mission.action_executed, gate_index tied to the call's own approval (not response order)", () => {
  const translator = createTranslator({ missionId: MISSION_ID });

  // Two gated calls arrive on the same model.message...
  translator.push(
    modelMessage("evt-1", "main", [
      toolCall("call-A", "quarantine", { message_ids: ["m1"] }),
      toolCall("call-B", "notify_impersonated", { address: "real@example.com" }),
    ]),
  );

  // ...but call-B is approved (and thus gated) FIRST, so it should own
  // gate_index 1, while call-A -- approved second -- owns gate_index 2. If
  // an implementation instead numbered gates by tool.response arrival order
  // rather than by approval order, this test would catch it.
  translator.push(approvalRequired("appr-B", "main", [ref("call-B", "evt-1")]));
  translator.push(approvalRequired("appr-A", "main", [ref("call-A", "evt-1")]));

  const resultA = translator.push(toolResponse("evt-2", "main", "call-A", JSON.stringify({ note: "msg-001 moved to Quarantine." })));
  const resultB = translator.push(toolResponse("evt-3", "main", "call-B", JSON.stringify({ note: "Real owner notified." })));

  assert.equal(resultA.length, 1);
  assert.deepEqual(resultA[0], {
    type: "mission.action_executed",
    mission_id: MISSION_ID,
    gate_index: 2,
    action: "quarantine",
    result_summary: "msg-001 moved to Quarantine.",
  });

  assert.equal(resultB.length, 1);
  assert.deepEqual(resultB[0], {
    type: "mission.action_executed",
    mission_id: MISSION_ID,
    gate_index: 1,
    action: "notify_impersonated",
    result_summary: "Real owner notified.",
  });
});

// A gated call is the one place where silence is the WORST answer.
//
// Qodo, PR #75 finding #2 established the first half of this: a payload
// without a string `note` must never be reported as a plain success, because
// `result_summary: ""` reads as "the irreversible action ran, and said
// nothing". That fix chose silence - return [] - which T-074 then found to be
// the other half of the same bug. Once a human has granted the licence the
// cockpit's gate sits at "Allowed - executing..." (cockpit/src/ApprovalPanel.tsx
// :161, and missionPlan.ts:354's `resolved === "allow"` branch) until a
// terminal mission.action_executed arrives for that gate index. Nothing else
// ever clears it: mission.approval_resolved is already past, and a tool error
// does not end the turn. So a dropped result leaves the operator watching a
// spinner for an action that already failed - the failure never reaches the
// person who is accountable for it, which is the one outcome this project
// exists to prevent.
//
// Both halves therefore have to hold at once: never claim success, and always
// terminate the gate. The tests below assert exactly that pair.
test("a gated-action result without a string .note is reported as a FAILURE, never as success and never dropped", async (t) => {
  // The realistic producer of this, verified 2026-08-30: three of the four
  // gated wrappers in tools/imports_mcp/server.py validate their arguments by
  // raising ToolError (quarantine server.py:292-301, notify_impersonated
  // :319-330, file_abuse_report :351-358). That raise happens INSIDE the tool
  // call, i.e. after TrueForge's approval gate has already been granted, so
  // the licence has been spent and the tool still did not run. Whatever that
  // error looks like on the wire, it is not `{"note": "..."}`.
  const failureSummary = (result: MissionEvent[]): string => {
    assert.equal(result.length, 1, "a gated call that was allowed must always produce a terminal event");
    const event = result[0] as { type: string; gate_index: number; action: string; result_summary: string };
    assert.equal(event.type, "mission.action_executed");
    assert.equal(event.gate_index, 1);
    // The summary must read as a failure to a human. This is the whole point:
    // the cockpit prefixes it with the fixed words "Executed: ", so the text
    // itself is what stops an operator believing an irreversible action ran.
    assert.match(event.result_summary, /^FAILED/, `summary must announce failure, got: ${event.result_summary}`);
    return event.result_summary;
  };

  const gatedTranslator = () => {
    const translator = createTranslator({ missionId: MISSION_ID });
    translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "create_block_rule", { pattern: "*@evil.example.com" })]));
    translator.push(approvalRequired("appr-1", "main", [ref("call-1", "evt-1")]));
    return translator;
  };

  await t.test("no note field at all", () => {
    const summary = failureSummary(gatedTranslator().push(toolResponse("evt-2", "main", "call-1", JSON.stringify({ ok: true }))));
    assert.match(summary, /create_block_rule/, "the summary names the action that failed");
    assert.match(summary, /\{"ok":true\}/, "the summary quotes what the tool actually replied");
  });

  await t.test("note field present but not a string", () => {
    const summary = failureSummary(gatedTranslator().push(toolResponse("evt-2", "main", "call-1", JSON.stringify({ note: 12345 }))));
    assert.match(summary, /\{"note":12345\}/);
  });

  await t.test("content that is not JSON at all - the shape an MCP ToolError arrives in", () => {
    // The likeliest real failure of the three raising wrappers. A tool error
    // is a message, not a JSON document, so it fails JSON.parse - which is
    // why parse failure cannot mean "drop it" for a gated call the way it
    // does for every read-only tool.
    const raw = "Error executing tool quarantine: message_ids must be a non-empty list";
    const summary = failureSummary(gatedTranslator().push(toolResponse("evt-2", "main", "call-1", raw)));
    assert.match(summary, /message_ids must be a non-empty list/, "the operator sees the actual reason");
  });

  await t.test("a JSON payload that is not an object", () => {
    const summary = failureSummary(gatedTranslator().push(toolResponse("evt-2", "main", "call-1", '"just a string"')));
    assert.match(summary, /just a string/);
  });

  await t.test("an empty response body still terminates the gate", () => {
    const summary = failureSummary(gatedTranslator().push(toolResponse("evt-2", "main", "call-1", "")));
    assert.ok(summary.length > 0, "a summary is still written when there is nothing to quote");
  });

  await t.test("an unreadably long error is truncated, not passed through whole", () => {
    // Rule 2880706 caps tool responses at ~2KB, but that is a rule our own
    // tools follow, not one the wire enforces - and this string is rendered
    // straight into a licence-gate panel. The summary stays a summary.
    const summary = failureSummary(gatedTranslator().push(toolResponse("evt-2", "main", "call-1", "x".repeat(5000))));
    assert.ok(summary.length < 500, `summary must stay short, was ${summary.length} chars`);
    assert.match(summary, /…$/, "truncation is marked, so nobody reads a cut-off reason as the whole reason");
  });

  await t.test("a genuine string note still produces the event, unchanged", () => {
    const result = gatedTranslator().push(toolResponse("evt-2", "main", "call-1", JSON.stringify({ note: "rule created" })));
    assert.deepEqual(result[0], {
      type: "mission.action_executed",
      mission_id: MISSION_ID,
      gate_index: 1,
      action: "create_block_rule",
      result_summary: "rule created",
    });
  });

  await t.test("a failed result for a call that never became a licence gate is still dropped", () => {
    // No approval_required was ever seen for this call, so there is no gate
    // index to attach the failure to and no stuck panel to clear. Inventing
    // one would put an outcome on a gate the human was never shown.
    const translator = createTranslator({ missionId: MISSION_ID });
    translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "quarantine", { message_ids: [] })]));
    assert.deepEqual(translator.push(toolResponse("evt-2", "main", "call-1", "Error executing tool quarantine")), []);
  });
});

test("an unreadable result from a NON-gated tool is still dropped, not turned into a failure event", () => {
  // The new failure path is deliberately narrow. A read-only tool that
  // returns nonsense is "not determined", which contracts/events.ts and this
  // file both represent as absence - there is no gate waiting on it, and no
  // human decision it could misreport.
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "domain_intel", { domain: "evil.example.com" })]));
  assert.deepEqual(translator.push(toolResponse("evt-2", "main", "call-1", "Error executing tool domain_intel")), []);
});

test("tool.approval_required missing id/created_at/thread_id is dropped entirely (Qodo, PR #75 finding #1)", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "quarantine", { message_ids: ["m1"] })]));

  const missingId = { type: "tool.approval_required", created_at: "2026-08-29T00:00:00Z", thread_id: "main", tool_calls: [ref("call-1", "evt-1")] };
  assert.deepEqual(translator.push(missingId), []);

  const missingCreatedAt = { type: "tool.approval_required", id: "appr-1", thread_id: "main", tool_calls: [ref("call-1", "evt-1")] };
  assert.deepEqual(translator.push(missingCreatedAt), []);

  const missingThreadId = { type: "tool.approval_required", id: "appr-1", created_at: "2026-08-29T00:00:00Z", tool_calls: [ref("call-1", "evt-1")] };
  assert.deepEqual(translator.push(missingThreadId), []);

  // Same call, now with a genuinely complete event - proves the drops above
  // were about the missing metadata, not something else about this call.
  const complete = translator.push(approvalRequired("appr-1", "main", [ref("call-1", "evt-1")]));
  assert.equal(complete.length, 1);
});

test("a url_reputation-shaped result is rejected for domain_intel and vice versa (Qodo, PR #75 finding #3)", () => {
  const urlReputationShape = JSON.stringify({ url: "hxxps://evil.example.com", listed: false, tags: [] });
  const domainIntelShape = JSON.stringify({
    domain: "evil.example.com",
    registration_date: null,
    registrar: null,
    abuse_contact: null,
    cert_issued_at: null,
  });

  const t1 = createTranslator({ missionId: MISSION_ID });
  t1.push(modelMessage("evt-1", "main", [toolCall("call-1", "domain_intel", { domain: "evil.example.com" })]));
  assert.deepEqual(t1.push(toolResponse("evt-2", "main", "call-1", urlReputationShape)), []);

  const t2 = createTranslator({ missionId: MISSION_ID });
  t2.push(modelMessage("evt-1", "main", [toolCall("call-1", "url_reputation", { url: "hxxps://evil.example.com" })]));
  assert.deepEqual(t2.push(toolResponse("evt-2", "main", "call-1", domainIntelShape)), []);
});

test("tool.response for an unknown tool name -> []", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "some_tool_nobody_defined", {})]));
  const result = translator.push(toolResponse("evt-2", "main", "call-1", JSON.stringify({ anything: true })));
  assert.deepEqual(result, []);
});

test("tool.response for an unresolvable tool_call_id -> []", () => {
  // The model.message that would have named this call was never pushed
  // (e.g. dropped by a reconnect gap) -- there is nothing to dispatch on.
  const translator = createTranslator({ missionId: MISSION_ID });
  const result = translator.push(toolResponse("evt-1", "main", "call-nobody-registered", JSON.stringify({ anything: true })));
  assert.deepEqual(result, []);
});

test("tool.response with unparseable content JSON -> [] instead of throwing", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "parse_message", {})]));

  let result: MissionEvent[] = [];
  assert.doesNotThrow(() => {
    result = translator.push(toolResponse("evt-2", "main", "call-1", "{ this is not json"));
  });
  assert.deepEqual(result, []);
});

// ---------------------------------------------------------------------------
// 5. turn.done
// ---------------------------------------------------------------------------

test("turn.done with status error -> one mission.failed with cause error", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  const result = translator.push(turnDone({ status: "error", message: "boom", completed_at: "2026-08-29T00:00:00Z" }));
  assert.deepEqual(result, [{ type: "mission.failed", mission_id: MISSION_ID, cause: "error", message: "boom" }]);
});

test("turn.done with status cancelled -> one mission.failed with cause cancelled", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  const result = translator.push(
    turnDone({ status: "cancelled", reason: "client-cancelled", completed_at: "2026-08-29T00:00:00Z" }),
  );
  assert.deepEqual(result, [{ type: "mission.failed", mission_id: MISSION_ID, cause: "cancelled", reason: "client-cancelled" }]);
});

test("turn.done with status done but non-empty required_actions means PAUSED, not finished -> []", () => {
  // This is the subtlest rule in the spec: `done` is TrueForge's terminal
  // status name, but a `done` turn that is still waiting on an approval
  // (required_actions non-empty) has not actually finished the mission.
  // Emitting mission.complete here would make the cockpit's missionDone
  // flip true while a licence gate is still open -- the opposite of
  // "control and safety" (CLAUDE.md's judging criteria; this is exactly
  // the class of bug the qualifying test is watching for: the harness must
  // *stop for a person*, and a false mission.complete papers over that stop).
  const translator = createTranslator({ missionId: MISSION_ID });
  const result = translator.push(
    turnDone({
      status: "done",
      required_actions: [{ type: "tool.approval_required" }],
      output: null,
      completed_at: "2026-08-29T00:00:00Z",
    }),
  );
  assert.deepEqual(result, []);
});

test("turn.done with status done, empty required_actions, and no output -> [] (no final message yet)", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  const result = translator.push(
    turnDone({ status: "done", required_actions: [], output: null, completed_at: "2026-08-29T00:00:00Z" }),
  );
  assert.deepEqual(result, []);
});

test("turn.done with status done, empty required_actions, and string output -> mission.complete", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  const result = translator.push(
    turnDone({
      status: "done",
      required_actions: [],
      output: { type: "model.message", content: "All clear." },
      completed_at: "2026-08-29T00:00:00Z",
    }),
  );
  assert.deepEqual(result, [{ type: "mission.complete", mission_id: MISSION_ID, spoken_verdict: "All clear." }]);
});

test("turn.done final output as an array of text parts joins into one spoken_verdict", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  const result = translator.push(
    turnDone({
      status: "done",
      required_actions: [],
      output: {
        type: "model.message",
        content: [
          { type: "text", text: "All " },
          { type: "text", text: "clear." },
        ],
      },
      completed_at: "2026-08-29T00:00:00Z",
    }),
  );
  assert.deepEqual(result, [{ type: "mission.complete", mission_id: MISSION_ID, spoken_verdict: "All clear." }]);
});

// ---------------------------------------------------------------------------
// 6. Regression tests: events the stream must NEVER produce.
//
// Each of these encodes a real design decision from contracts/events.ts
// that a careless implementation could easily undo by "helpfully" filling
// in a gap. Run across one realistic full-mission sequence so a producer
// added anywhere in the pipeline (not just the obvious spot) would trip it.
// ---------------------------------------------------------------------------

function runFullMissionSequence(translator: ReturnType<typeof createTranslator>): MissionEvent[] {
  const out: MissionEvent[] = [];
  const push = (raw: unknown) => out.push(...translator.push(raw));

  // Evidence gathering.
  push(modelMessage("mm-parse", "main", [toolCall("call-parse", "parse_message", {})]));
  push(toolResponse("tr-parse", "main", "call-parse", JSON.stringify({
    message_id: "m1", from: "a.morgan@northgate-trust-finance.com", reply_to: null, return_path: null,
    display_name: "Alex Morgan, CFO", authentication_results: "dmarc=fail", received_chain: [], urls: [], attachments: [],
  })));

  push(modelMessage("mm-domain", "main", [toolCall("call-domain", "domain_intel", { domain: "northgate-trust-finance.com" })]));
  push(toolResponse("tr-domain", "main", "call-domain", JSON.stringify({
    domain: "northgate-trust-finance.com", registration_date: "2026-08-24", registrar: null, abuse_contact: null, cert_issued_at: "2026-08-25",
  })));

  push(modelMessage("mm-url", "main", [toolCall("call-url", "url_reputation", { url: "hxxps://northgate-trust-finance.com/wire-portal" })]));
  push(toolResponse("tr-url", "main", "call-url", JSON.stringify({ url: "hxxps://northgate-trust-finance.com/wire-portal", listed: false, tags: [] })));

  push(modelMessage("mm-hist", "main", [toolCall("call-hist", "correspondence_history", { address: "a.morgan@northgate-trust.com" })]));
  push(toolResponse("tr-hist", "main", "call-hist", JSON.stringify({
    address: "a.morgan@northgate-trust.com", domain: "northgate-trust.com", prior_contact_count: 214, first_seen: "2023-02-11", last_seen: "2026-08-20", domains_used: ["northgate-trust.com"],
  })));

  push(modelMessage("mm-det", "main", [toolCall("call-det", "detonate", { url: "hxxps://northgate-trust-finance.com/wire-portal" })]));
  push(toolResponse("tr-det", "main", "call-det", JSON.stringify({
    url: "hxxps://northgate-trust-finance.com/wire-portal", redirect_chain: [], final_url: "hxxps://northgate-trust-finance.com/secure/confirm",
    forms: [], summary: "Redirects to a credential form.",
  })));

  // Four gated actions, in order, each approved and executed.
  const gated: Array<[string, string, string, Record<string, unknown>]> = [
    ["mm-g1", "call-g1", "quarantine", { message_ids: ["m1"] }],
    ["mm-g2", "call-g2", "notify_impersonated", { address: "a.morgan@northgate-trust.com" }],
    ["mm-g3", "call-g3", "create_block_rule", { pattern: "*@northgate-trust-finance.com" }],
    ["mm-g4", "call-g4", "file_abuse_report", { domain: "northgate-trust-finance.com" }],
  ];
  for (const [mmId, callId, name, args] of gated) {
    push(modelMessage(mmId, "main", [toolCall(callId, name, args)]));
    push(approvalRequired(`appr-${callId}`, "main", [ref(callId, mmId)]));
    push(toolResponse(`tr-${callId}`, "main", callId, JSON.stringify({ note: `${name} done.` })));
  }

  // Final turn.
  push(turnDone({
    status: "done",
    required_actions: [],
    output: { type: "model.message", content: "This is fake. Do not click it." },
    completed_at: "2026-08-29T00:10:00Z",
  }));

  return out;
}

test("regression: a full mission never emits mission.evidence in the identity lane", () => {
  // contracts/events.ts is explicit: no tool computes lookalike_domain /
  // lookalike_of, and emitting `lookalike_domain: false` when nothing was
  // actually checked would assert a clean security finding that was never
  // made. The only honest translation of "not computed" is silence.
  const translator = createTranslator({ missionId: MISSION_ID });
  const events = runFullMissionSequence(translator);
  const identityLaneEvents = events.filter((e) => e.type === "mission.evidence" && (e as { lane?: string }).lane === "identity");
  assert.deepEqual(identityLaneEvents, []);
});

test("regression: a full mission never emits mission.verdict", () => {
  // VerdictEvent exists in the contract for a future producer, but the raw
  // TrueForge stream carries only the model's prose (turn.done's output),
  // never a structured malicious|suspicious|legitimate label. Synthesizing
  // one here would be putting words a judge could quote in the model's
  // mouth that the model never actually said in a structured way.
  const translator = createTranslator({ missionId: MISSION_ID });
  const events = runFullMissionSequence(translator);
  assert.deepEqual(events.filter((e) => e.type === "mission.verdict"), []);
});

test("regression: a full mission never emits mission.approval_resolved", () => {
  // ApprovalResolvedEvent exists in the contract, but nothing in TrueForge's
  // turn stream echoes back the user.tool_approval we POST to resume a
  // gated call -- that's an outbound resume payload, not an inbound stream
  // event. A translator that fabricated this event on approval would be
  // inventing wire traffic that never happened.
  const translator = createTranslator({ missionId: MISSION_ID });
  const events = runFullMissionSequence(translator);
  assert.deepEqual(events.filter((e) => e.type === "mission.approval_resolved"), []);
});

test("every emitted event across a full mission carries the translator's mission_id", () => {
  const translator = createTranslator({ missionId: MISSION_ID });
  const events = runFullMissionSequence(translator);
  assert.ok(events.length > 0, "sanity check: the sequence should actually produce events");
  for (const event of events) {
    assert.equal((event as { mission_id?: string }).mission_id, MISSION_ID);
  }
});

// ---------------------------------------------------------------------------
// 7. Robustness: push() must never throw, no matter what arrives.
// ---------------------------------------------------------------------------

test("push() never throws across a long sequence of hostile and malformed input", () => {
  const translator = createTranslator({ missionId: MISSION_ID });

  const hostileInputs: unknown[] = [
    null,
    undefined,
    "",
    "not an object",
    0,
    -1,
    NaN,
    [],
    [1, 2, 3],
    {},
    { type: null },
    { type: 123 },
    { type: "model.message" }, // missing tool_calls entirely
    { type: "model.message", tool_calls: null },
    { type: "model.message", tool_calls: "not-an-array" },
    { type: "model.message", tool_calls: [{}] }, // tool call with no id/function
    { type: "model.message", tool_calls: [{ id: "x", function: null }] },
    { type: "model.message", tool_calls: [{ id: "x", function: { name: "quarantine" } }] }, // missing arguments
    { type: "tool.approval_required" }, // missing tool_calls
    { type: "tool.approval_required", tool_calls: null },
    { type: "tool.approval_required", tool_calls: "nope" },
    { type: "tool.approval_required", tool_calls: [{}] }, // no id/source_event_id
    { type: "tool.approval_required", tool_calls: [{ id: null, source_event_id: null }] },
    { type: "tool.response" }, // missing tool_call_id/content
    { type: "tool.response", tool_call_id: null, content: null },
    { type: "tool.response", tool_call_id: "call-1", content: 12345 }, // content not a string
    { type: "tool.response", tool_call_id: "call-1", content: "{ broken json" },
    { type: "turn.done" }, // missing state
    { type: "turn.done", state: null },
    { type: "turn.done", state: {} }, // missing status
    { type: "turn.done", state: { status: "unknown-future-status" } },
    { type: "turn.done", state: { status: "done", required_actions: "not-an-array", output: null } },
    { type: "turn.done", state: { status: "done", required_actions: [], output: { type: "model.message", content: null } } },
    { type: "turn.done", state: { status: "done", required_actions: [], output: { type: "model.message", content: [null, 1, {}] } } },
    { type: "turn.done", state: { status: "error" } }, // missing message
    { type: "turn.done", state: { status: "cancelled" } }, // missing reason
    Symbol("weird"),
    () => {},
    new Date(),
    { type: "model.message", id: 1, thread_id: {}, tool_calls: [{ id: 1, type: 2, function: 3 }] },
  ];

  for (const raw of hostileInputs) {
    assert.doesNotThrow(() => translator.push(raw), `push() threw on: ${String(raw)}`);
  }
});

// A cancellation whose reason is outside TrueForge's four-value enum must
// still terminate the mission. Dropping it would reintroduce the exact bug
// mission.failed exists to fix - the cockpit deriving "still running" from
// the absence of a terminal event and rendering in-progress forever. No enum
// value is fabricated: it degrades to the free-text error branch instead.
test("a cancellation with an unrecognised reason still terminates the mission", () => {
  const translator = createTranslator({ missionId: "mission-001" });

  const events = translator.push({
    type: "turn.done",
    state: { status: "cancelled", reason: "some-future-reason", completed_at: "2026-08-30T00:00:00Z" },
  });

  assert.equal(events.length, 1, "an unrecognised cancellation reason must not be silently dropped");
  const event = events[0];
  assert.equal(event.type, "mission.failed");
  assert.equal(event.mission_id, "mission-001");
  if (event.type !== "mission.failed") return;
  assert.equal(event.cause, "error", "no TurnCancelledReason value may be fabricated");
  if (event.cause !== "error") return;
  assert.match(event.message, /some-future-reason/, "the raw reason must be reported verbatim");
});

// Qodo found (PRs #73/#74) that the translator joined a ToolCallRef to its
// model.message on tool-call id alone, ignoring source_event_id. Tool-call
// ids are only unique within the message that issued them, so a stale or
// reused id could put one action in front of the human while a different one
// was actually approved. These tests fail against that behaviour.
test("an approval whose source_event_id does not match the recorded message is refused", () => {
  const translator = createTranslator({ missionId: "mission-001" });

  translator.push({
    type: "model.message",
    id: "evt-real",
    thread_id: "main",
    tool_calls: [
      { id: "call-1", type: "function", function: { name: "quarantine", arguments: '{"message_ids":["m1"]}' } },
    ],
  });

  const events = translator.push({
    type: "tool.approval_required",
    id: "evt-approval",
    created_at: "2026-08-30T00:00:00Z",
    thread_id: "main",
    // Same tool-call id, but pointing at a different model.message.
    tool_calls: [{ id: "call-1", source_event_id: "evt-someone-else" }],
  });

  assert.deepEqual(events, [], "a mismatched source_event_id must not resolve to a gate");
});

test("an approval with no source_event_id is refused rather than resolved on id alone", () => {
  const translator = createTranslator({ missionId: "mission-001" });

  translator.push({
    type: "model.message",
    id: "evt-real",
    thread_id: "main",
    tool_calls: [
      { id: "call-1", type: "function", function: { name: "quarantine", arguments: "{}" } },
    ],
  });

  const events = translator.push({
    type: "tool.approval_required",
    id: "evt-approval",
    created_at: "2026-08-30T00:00:00Z",
    thread_id: "main",
    tool_calls: [{ id: "call-1" }],
  });

  assert.deepEqual(events, [], "a ref without source_event_id cannot be safely resolved");
});

// The positive case: a matching pair still resolves, so the guard above is a
// correctness check and not simply refusing everything.
test("a matching source_event_id still resolves the gate normally", () => {
  const translator = createTranslator({ missionId: "mission-001" });

  translator.push({
    type: "model.message",
    id: "evt-real",
    thread_id: "main",
    tool_calls: [
      { id: "call-1", type: "function", function: { name: "quarantine", arguments: '{"message_ids":["m1"]}' } },
    ],
  });

  const events = translator.push({
    type: "tool.approval_required",
    id: "evt-approval",
    created_at: "2026-08-30T00:00:00Z",
    thread_id: "main",
    tool_calls: [{ id: "call-1", source_event_id: "evt-real" }],
  });

  assert.equal(events.length, 1);
  const event = events[0];
  assert.equal(event.type, "mission.approval_required");
  if (event.type !== "mission.approval_required") return;
  assert.equal(event.action.action, "quarantine");
  assert.deepEqual(event.action.arguments, { message_ids: ["m1"] });
});

// The malformed-payload test above covers a partial object — an object of the
// right kind missing required fields. This covers the other shape of bad tool
// output: JSON that parses to the wrong *type* entirely. Distinct path,
// because a guard written as "check these fields" can pass an array (whose
// named properties are all undefined) if it never first proves the value is a
// plain object. Every one must be dropped, never cast into a typed payload.
test("a tool result whose JSON is the wrong type entirely is dropped", () => {
  const wrongTypes = ["[]", '"a string"', "42", "null", "true", "[{}]"];

  for (const body of wrongTypes) {
    const translator = createTranslator({ missionId: MISSION_ID });
    translator.push(modelMessage("evt-1", "main", [toolCall("call-1", "detonate", {})]));
    const result = translator.push(toolResponse("evt-2", "main", "call-1", body));
    assert.deepEqual(result, [], `JSON ${body} must not become a mission.detonation`);
  }
});

test("the same wrong-type results are dropped for every producing tool", () => {
  const producers = ["parse_message", "domain_intel", "url_reputation", "correspondence_history"];

  for (const tool of producers) {
    const translator = createTranslator({ missionId: MISSION_ID });
    translator.push(modelMessage("evt-1", "main", [toolCall("call-1", tool, {})]));
    const result = translator.push(toolResponse("evt-2", "main", "call-1", "[]"));
    assert.deepEqual(result, [], `an array result from ${tool} must not become a mission event`);
  }
});

// --- queued gates must not be lost when the turn terminates (O1 review, PR #73) ---

/** Queue three gates behind one active gate, without resolving any. */
function queueFourGates() {
  const translator = createTranslator({ missionId: MISSION_ID });
  const actions: Array<[string, string]> = [
    ["call-1", "quarantine"],
    ["call-2", "notify_impersonated"],
    ["call-3", "create_block_rule"],
    ["call-4", "file_abuse_report"],
  ];
  const emitted: MissionEvent[] = [];
  actions.forEach(([callId, name], i) => {
    translator.push(modelMessage(`mm-${i}`, "main", [toolCall(callId, name, {})]));
    emitted.push(...translator.push(approvalRequired(`appr-${i}`, "main", [ref(callId, `mm-${i}`)])));
  });
  // Serialisation means only the first gate is out; three are queued.
  assert.equal(emitted.length, 1, "only one gate should be outstanding at a time");
  return translator;
}

test("a terminal error releases gates still queued instead of dropping them", () => {
  const translator = queueFourGates();
  const out = translator.push(turnDone({ status: "error", message: "boom", completed_at: "t" }));

  const gates = out.filter((e) => e.type === "mission.approval_required");
  assert.equal(gates.length, 3, "the three queued gates must be released, not silently dropped");
  assert.deepEqual(
    gates.map((g) => (g as { gate_index: number }).gate_index),
    [2, 3, 4],
    "released in gate order",
  );
  assert.equal(out[out.length - 1].type, "mission.failed", "the terminal event comes last");
});

test("a cancelled turn also releases queued gates", () => {
  const translator = queueFourGates();
  const out = translator.push(turnDone({ status: "cancelled", reason: "abandoned", completed_at: "t" }));
  assert.equal(out.filter((e) => e.type === "mission.approval_required").length, 3);
  assert.equal(out[out.length - 1].type, "mission.failed");
});

test("a completed turn releases queued gates before mission.complete", () => {
  const translator = queueFourGates();
  const out = translator.push(
    turnDone({ status: "done", required_actions: [], output: { type: "model.message", content: "done" }, completed_at: "t" }),
  );
  assert.equal(out.filter((e) => e.type === "mission.approval_required").length, 3);
  assert.equal(out[out.length - 1].type, "mission.complete");
});

// The one case that must NOT flush: a turn ending *paused* is the harness
// waiting on exactly these gates, so the queue is still live and a human
// decision is still coming.
test("a turn ending PAUSED does not flush the queue", () => {
  const translator = queueFourGates();
  const out = translator.push(
    turnDone({ status: "done", required_actions: [{ type: "tool.approval_required" }], output: null, completed_at: "t" }),
  );
  assert.deepEqual(out, [], "a paused turn emits nothing and keeps its queue");
});
