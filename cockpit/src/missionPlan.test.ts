// cockpit/src/missionPlan.test.ts
//
// First test suite for missionPlan.ts. This file is the only thing that
// turns the flat MissionEvent stream into the plan tree, the evidence lane
// panels, and the approval gate panel, and it has shipped with zero direct
// tests so far (Qodo has found three separate bugs in it across PRs #32,
// #36, #52). The tests below are grouped to mirror the module's own four
// exports, plus a fifth section for the two `findLast`-vs-`find` behaviours
// called out as most likely to regress.
//
// Small factory helpers build MissionEvents from their real contract shapes
// (contracts/events.ts) with sane defaults, overridable per test, so test
// bodies read as "here is what happened" rather than JSON walls.

import { test } from "node:test";
import assert from "node:assert/strict";
import type {
  ApprovalStatus,
  CorrespondenceHistory,
  DomainIntel,
  IdentityEvidence,
  MissionEvent,
  ParsedMessage,
  ProposedActionName,
  TurnCancelledReason,
  UrlReputation,
  VerdictLabel,
} from "../../contracts/events.ts";
import {
  buildApprovalGates,
  buildEvidenceLanes,
  buildMissionPlan,
  describeEvent,
} from "./missionPlan.ts";
import type { ApprovalGateState, EvidenceLaneState, PlanNode, StageStatus } from "./missionPlan.ts";

// ---------------------------------------------------------------------------
// Event factories
// ---------------------------------------------------------------------------

const MID = "mission-1";

function fullParsedMessage(overrides: Partial<ParsedMessage> = {}): ParsedMessage {
  return {
    message_id: "m1",
    from: "attacker@example.com",
    reply_to: null,
    return_path: null,
    display_name: null,
    authentication_results: "dmarc=fail",
    received_chain: [],
    urls: [],
    attachments: [],
    ...overrides,
  };
}

function messageReceivedEvent(overrides: Partial<ParsedMessage> = {}): MissionEvent {
  return { type: "mission.message_received", mission_id: MID, message: fullParsedMessage(overrides) };
}

function domainIntel(overrides: Partial<DomainIntel> = {}): DomainIntel {
  return {
    domain: "evil.example",
    registration_date: null,
    registrar: null,
    abuse_contact: null,
    cert_issued_at: null,
    ...overrides,
  };
}

function urlReputation(overrides: Partial<UrlReputation> = {}): UrlReputation {
  return { url: "http://evil.example/pay", listed: false, tags: [], ...overrides };
}

function infrastructureEvidence(evidence: DomainIntel | UrlReputation): MissionEvent {
  return { type: "mission.evidence", mission_id: MID, lane: "infrastructure", evidence };
}

function identityEvidence(overrides: Partial<IdentityEvidence> = {}): MissionEvent {
  return {
    type: "mission.evidence",
    mission_id: MID,
    lane: "identity",
    evidence: {
      from_address: "attacker@example.com",
      display_name: null,
      reply_to: null,
      lookalike_domain: false,
      lookalike_of: null,
      ...overrides,
    },
  };
}

function historyEvidence(overrides: Partial<CorrespondenceHistory> = {}): MissionEvent {
  return {
    type: "mission.evidence",
    mission_id: MID,
    lane: "history",
    evidence: {
      address: "attacker@example.com",
      domain: "example.com",
      prior_contact_count: 0,
      first_seen: null,
      last_seen: null,
      domains_used: [],
      ...overrides,
    },
  };
}

function detonationSuccess(summary = "1 form asking for a password"): MissionEvent {
  return {
    type: "mission.detonation",
    mission_id: MID,
    detonation: {
      url: "http://evil.example",
      redirect_chain: [],
      final_url: "http://evil.example/landing",
      forms: [],
      summary,
    },
  };
}

function detonationFailure(error = "DNS timeout"): MissionEvent {
  return {
    type: "mission.detonation",
    mission_id: MID,
    detonation: { url: "http://evil.example", redirect_chain: [], error },
  };
}

function verdictEvent(verdict: VerdictLabel = "malicious", summary = "Looks bad."): MissionEvent {
  return { type: "mission.verdict", mission_id: MID, verdict, summary };
}

function approvalRequired(
  gateIndex: 1 | 2 | 3 | 4,
  opts: { action?: ProposedActionName; args?: Record<string, unknown>; toolCallId?: string } = {},
): MissionEvent {
  const action = opts.action ?? "quarantine";
  const toolCallId = opts.toolCallId ?? `call-${gateIndex}`;
  return {
    type: "mission.approval_required",
    mission_id: MID,
    gate_index: gateIndex,
    gate_count: 4,
    action: { action, arguments: opts.args ?? {} },
    tool_call_id: toolCallId,
    approval: {
      type: "tool.approval_required",
      id: `appr-${gateIndex}`,
      created_at: "2026-08-30T00:00:00Z",
      thread_id: "main",
      tool_calls: [{ id: toolCallId, source_event_id: "mm-1" }],
    },
  };
}

function approvalResolved(gateIndex: 1 | 2 | 3 | 4, status: ApprovalStatus, reason?: string): MissionEvent {
  return {
    type: "mission.approval_resolved",
    mission_id: MID,
    gate_index: gateIndex,
    status,
    ...(reason !== undefined ? { reason } : {}),
  };
}

function actionExecuted(gateIndex: 1 | 2 | 3 | 4, action: ProposedActionName, resultSummary: string): MissionEvent {
  return { type: "mission.action_executed", mission_id: MID, gate_index: gateIndex, action, result_summary: resultSummary };
}

function missionComplete(spokenVerdict = "All clear."): MissionEvent {
  return { type: "mission.complete", mission_id: MID, spoken_verdict: spokenVerdict };
}

function missionFailedError(message = "boom"): MissionEvent {
  return { type: "mission.failed", mission_id: MID, cause: "error", message };
}

function missionFailedCancelled(reason: TurnCancelledReason = "abandoned"): MissionEvent {
  return { type: "mission.failed", mission_id: MID, cause: "cancelled", reason };
}

function findGate(gates: ApprovalGateState[], gateIndex: number): ApprovalGateState {
  const gate = gates.find((g) => g.gateIndex === gateIndex);
  assert.ok(gate, `gate ${gateIndex} must always be present`);
  return gate!;
}

function findLane(lanes: EvidenceLaneState[], lane: string): EvidenceLaneState {
  const found = lanes.find((l) => l.lane === lane);
  assert.ok(found, `lane ${lane} must always be present`);
  return found!;
}

function findNode(plan: PlanNode[], id: string): PlanNode {
  const node = plan.find((n) => n.id === id);
  assert.ok(node, `node ${id} must always be present`);
  return node!;
}

// ---------------------------------------------------------------------------
// A. buildApprovalGates
// ---------------------------------------------------------------------------

test("buildApprovalGates always returns four fixed slots, even with no events", () => {
  const gates = buildApprovalGates([]);
  assert.deepEqual(
    gates.map((g) => g.gateIndex),
    [1, 2, 3, 4],
  );
  for (const g of gates) {
    assert.equal(g.executed, false);
    assert.equal(g.action, undefined);
    assert.equal(g.resolved, undefined);
  }
});

test("approval_required populates action, requestArguments, and toolCallId on the right slot", () => {
  const gates = buildApprovalGates([
    approvalRequired(2, { action: "notify_impersonated", args: { to: "victim@example.com" }, toolCallId: "call-99" }),
  ]);
  const gate2 = findGate(gates, 2);
  assert.equal(gate2.action, "notify_impersonated");
  assert.deepEqual(gate2.requestArguments, { to: "victim@example.com" });
  assert.equal(gate2.toolCallId, "call-99");
  assert.equal(gate2.request?.tool_calls[0]?.id, "call-99");

  // Other slots are untouched.
  assert.equal(findGate(gates, 1).action, undefined);
});

test("approval_resolved sets resolved status and reason", () => {
  const gates = buildApprovalGates([approvalRequired(1), approvalResolved(1, "deny", "sender not verified")]);
  const gate1 = findGate(gates, 1);
  assert.equal(gate1.resolved, "deny");
  assert.equal(gate1.reason, "sender not verified");
});

test("action_executed sets resultSummary and executed", () => {
  const gates = buildApprovalGates([
    approvalRequired(1),
    approvalResolved(1, "allow"),
    actionExecuted(1, "quarantine", "1 message quarantined"),
  ]);
  const gate1 = findGate(gates, 1);
  assert.equal(gate1.executed, true);
  assert.equal(gate1.resultSummary, "1 message quarantined");
});

// Deliberate: a reconnect can deliver action_executed without this client
// ever having seen the matching approval_required (Qodo, PR #32 finding #1,
// see buildApprovalGates' own docstring).
test("action_executed WITHOUT a prior approval_required still populates the gate", () => {
  const gates = buildApprovalGates([actionExecuted(3, "create_block_rule", "block rule created")]);
  const gate3 = findGate(gates, 3);
  assert.equal(gate3.executed, true);
  assert.equal(gate3.resultSummary, "block rule created");
  assert.equal(gate3.action, "create_block_rule");
  // Never observed a request for this gate.
  assert.equal(gate3.toolCallId, undefined);
  assert.equal(gate3.requestArguments, undefined);
});

test("a retried gate (fresh approval_required after a denial) clears the stale outcome", () => {
  const gates = buildApprovalGates([
    approvalRequired(1, { toolCallId: "call-1" }),
    approvalResolved(1, "deny", "sender not verified"),
    approvalRequired(1, { toolCallId: "call-1-retry" }),
  ]);
  const gate1 = findGate(gates, 1);
  assert.equal(gate1.resolved, undefined, "the stale deny must not survive the retry");
  assert.equal(gate1.reason, undefined);
  assert.equal(gate1.toolCallId, "call-1-retry", "the new request's tool call id must win");
});

test("a retried gate (fresh approval_required after execution) clears executed/resultSummary too", () => {
  const gates = buildApprovalGates([
    approvalRequired(1, { toolCallId: "call-1" }),
    approvalResolved(1, "allow"),
    actionExecuted(1, "quarantine", "1 message quarantined"),
    approvalRequired(1, { toolCallId: "call-1-retry" }),
  ]);
  const gate1 = findGate(gates, 1);
  assert.equal(gate1.executed, false, "a retry must not still render as already executed");
  assert.equal(gate1.resultSummary, undefined);
  assert.equal(gate1.toolCallId, "call-1-retry");
});

// ---------------------------------------------------------------------------
// B. buildEvidenceLanes
// ---------------------------------------------------------------------------

test("buildEvidenceLanes always returns exactly the three lanes, infrastructure/identity/history", () => {
  const lanes = buildEvidenceLanes([]);
  assert.deepEqual(
    lanes.map((l) => l.lane),
    ["infrastructure", "identity", "history"],
  );
});

test("evidence items land in the lane that produced them", () => {
  const infra = infrastructureEvidence(domainIntel({ domain: "evil.example" }));
  const identity = identityEvidence({ lookalike_domain: true, lookalike_of: "bank.example" });
  const history = historyEvidence({ prior_contact_count: 3 });
  const lanes = buildEvidenceLanes([infra, identity, history]);

  assert.deepEqual(findLane(lanes, "infrastructure").items, [infra]);
  assert.deepEqual(findLane(lanes, "identity").items, [identity]);
  assert.deepEqual(findLane(lanes, "history").items, [history]);
});

test("an empty lane reads 'pending' while evidence is still the current stage", () => {
  // Evidence stage reached (an infrastructure item arrived) but identity has
  // reported nothing yet, and nothing later has happened.
  const lanes = buildEvidenceLanes([messageReceivedEvent(), infrastructureEvidence(domainIntel())]);
  assert.equal(findLane(lanes, "identity").status, "pending");
});

// T-052 fix (cockpit commit f9a19bd): a lane the stream moves past without
// ever reporting is "done", not stuck "pending" forever just because it
// happens to be empty.
test("an empty lane reads 'done' once the stage advances past evidence", () => {
  const lanes = buildEvidenceLanes([
    messageReceivedEvent(),
    infrastructureEvidence(domainIntel()),
    detonationSuccess(),
  ]);
  assert.equal(findLane(lanes, "identity").status, "done");
});

test("an empty lane reads 'done' once the mission ends, even with no other progress", () => {
  const lanes = buildEvidenceLanes([missionComplete()]);
  assert.equal(findLane(lanes, "identity").status, "done");
  assert.deepEqual(findLane(lanes, "identity").items, []);
});

test("identity evidence being absent for an entire finished mission is a normal 'done, nothing reported' state", () => {
  const lanes = buildEvidenceLanes([
    messageReceivedEvent(),
    infrastructureEvidence(domainIntel()),
    historyEvidence(),
    verdictEvent(),
    missionComplete(),
  ]);
  const identity = findLane(lanes, "identity");
  assert.equal(identity.status, "done");
  assert.deepEqual(identity.items, []);
});

// ---------------------------------------------------------------------------
// C. buildMissionPlan
// ---------------------------------------------------------------------------

test("buildMissionPlan returns the six stages, in order", () => {
  const plan = buildMissionPlan([messageReceivedEvent()]);
  assert.deepEqual(
    plan.map((n) => n.id),
    ["message", "evidence", "detonation", "verdict", "gates", "complete"],
  );
});

test("stage status advances as events arrive", () => {
  // Only a message: message is active, everything after is pending.
  let plan = buildMissionPlan([messageReceivedEvent()]);
  assert.equal(findNode(plan, "message").status, "active");
  assert.equal(findNode(plan, "evidence").status, "pending");

  // Evidence starts arriving: message is done, evidence becomes active.
  plan = buildMissionPlan([messageReceivedEvent(), infrastructureEvidence(domainIntel())]);
  assert.equal(findNode(plan, "message").status, "done");
  assert.equal(findNode(plan, "evidence").status, "active");
  assert.equal(findNode(plan, "detonation").status, "pending");

  // Detonation happens: evidence is done, detonation is active.
  plan = buildMissionPlan([messageReceivedEvent(), infrastructureEvidence(domainIntel()), detonationSuccess()]);
  assert.equal(findNode(plan, "evidence").status, "done");
  assert.equal(findNode(plan, "detonation").status, "active");
  assert.equal(findNode(plan, "verdict").status, "pending");
});

test("mission.failed makes the plan terminal exactly as mission.complete does", () => {
  const completedPlan = buildMissionPlan([messageReceivedEvent(), missionComplete()]);
  const failedPlan = buildMissionPlan([messageReceivedEvent(), missionFailedError("crashed")]);

  for (const id of ["message", "evidence", "detonation", "verdict", "gates", "complete"]) {
    assert.equal(findNode(completedPlan, id).status, "done", `completed plan node ${id}`);
    assert.equal(findNode(failedPlan, id).status, "done", `failed plan node ${id}`);
  }
});

// ---------------------------------------------------------------------------
// D. describeEvent — one case per event type
// ---------------------------------------------------------------------------

test("describeEvent: mission.message_received", () => {
  assert.equal(describeEvent(messageReceivedEvent({ from: "a@example.com" })), "From a@example.com");
});

test("describeEvent: mission.evidence, infrastructure lane, DomainIntel", () => {
  const e = infrastructureEvidence(domainIntel({ domain: "evil.example", registration_date: "2026-08-01", cert_issued_at: "2026-08-02" }));
  assert.equal(describeEvent(e), "evil.example — registered 2026-08-01, cert 2026-08-02");
});

test("describeEvent: mission.evidence, infrastructure lane, UrlReputation", () => {
  const listed = infrastructureEvidence(urlReputation({ listed: true }));
  assert.equal(describeEvent(listed), "http://evil.example/pay — listed on URLhaus");

  const notListed = infrastructureEvidence(urlReputation({ listed: false }));
  assert.equal(describeEvent(notListed), "http://evil.example/pay — not listed on URLhaus (weak signal only)");
});

test("describeEvent: mission.evidence, identity lane", () => {
  const lookalike = identityEvidence({ lookalike_domain: true, lookalike_of: "bank.example" });
  assert.equal(describeEvent(lookalike), "Reply-To looks like a lookalike of bank.example");

  const clean = identityEvidence({ lookalike_domain: false });
  assert.equal(describeEvent(clean), "No lookalike domain detected");
});

test("describeEvent: mission.evidence, history lane", () => {
  const e = historyEvidence({ prior_contact_count: 5, domain: "example.com" });
  assert.equal(describeEvent(e), "5 prior contacts from example.com");
});

test("describeEvent: mission.detonation, success", () => {
  assert.equal(describeEvent(detonationSuccess("1 form asking for a password")), "1 form asking for a password");
});

test("describeEvent: mission.detonation, error", () => {
  assert.equal(describeEvent(detonationFailure("DNS timeout")), "Detonation failed: DNS timeout");
});

test("describeEvent: mission.verdict", () => {
  assert.equal(describeEvent(verdictEvent("malicious", "Credential phishing.")), "MALICIOUS — Credential phishing.");
});

test("describeEvent: mission.approval_required", () => {
  const e = approvalRequired(2, { action: "file_abuse_report" });
  assert.equal(describeEvent(e), "Gate 2/4 requested: file_abuse_report");
});

test("describeEvent: mission.approval_resolved", () => {
  assert.equal(describeEvent(approvalResolved(3, "allow")), "Gate 3: allow");
});

test("describeEvent: mission.action_executed", () => {
  assert.equal(describeEvent(actionExecuted(1, "quarantine", "1 message quarantined")), "1 message quarantined");
});

test("describeEvent: mission.complete", () => {
  assert.equal(describeEvent(missionComplete("All clear, no action needed.")), "All clear, no action needed.");
});

test("describeEvent: mission.failed, cause 'error' reads message", () => {
  assert.equal(describeEvent(missionFailedError("sandbox crashed")), "Mission failed: sandbox crashed");
});

test("describeEvent: mission.failed, cause 'cancelled' reads reason", () => {
  assert.equal(describeEvent(missionFailedCancelled("client-cancelled")), "Mission cancelled: client-cancelled");
});

// ---------------------------------------------------------------------------
// E. The two findLast-vs-find behaviours most likely to regress
//
// A resumed turn genuinely re-emits events, so a second occurrence of
// mission.message_received or a terminal event is the current truth, not a
// duplicate to ignore first-and-discard. Both tests below assert the
// CORRECT behaviour (findLast semantics) regardless of what the current
// source does — see this file's final report for which way they actually
// came out on this run.
// ---------------------------------------------------------------------------

test("buildMissionPlan's message node reflects the SECOND mission.message_received, not the first", () => {
  const events = [
    messageReceivedEvent({ message_id: "m1", from: "first@example.com" }),
    messageReceivedEvent({ message_id: "m2", from: "second@example.com" }),
  ];
  const plan = buildMissionPlan(events);
  assert.equal(findNode(plan, "message").detail, "From second@example.com");
});

test("buildMissionPlan's complete node reflects a mission.failed that arrives AFTER a mission.complete", () => {
  const events = [messageReceivedEvent(), missionComplete("All clear."), missionFailedError("crashed after completing")];
  const plan = buildMissionPlan(events);
  assert.equal(findNode(plan, "complete").detail, "Mission failed: crashed after completing");
});
