import type {
  ApprovalStatus,
  EvidenceLane,
  MissionEvent,
  ProposedActionName,
  ToolApprovalRequiredEvent,
} from "../../contracts/events";

/**
 * Turns the flat MissionEvent stream into the plan tree §10's architecture
 * diagram describes: message -> evidence (3 parallel subagents) -> detonation
 * -> verdict -> 4 sequential licence gates -> complete. T-051 ("plan tree
 * expanding as the agent works").
 *
 * Nothing here is fixture-specific. The six top-level stages and the three
 * evidence lanes come straight from §10's diagram (an architectural fact,
 * not a per-mission guess); the four gate slots come from the contract's
 * own `gate_index: 1 | 2 | 3 | 4` / `gate_count: 4` types. Every other detail
 * - which lane produced which evidence, which action a gate turned out to
 * be, whether it was allowed or denied - is derived purely from whichever
 * events have actually arrived, so this reads a live TrueForge stream the
 * same way it reads the fixture.
 */

export type StageStatus = "pending" | "active" | "done" | "denied";

export interface PlanNode {
  id: string;
  label: string;
  status: StageStatus;
  detail: string | null;
  children?: PlanNode[];
}

type StageId = "message" | "evidence" | "detonation" | "verdict" | "gates" | "complete";

const STAGE_ORDER: StageId[] = ["message", "evidence", "detonation", "verdict", "gates", "complete"];

const STAGE_LABEL: Record<StageId, string> = {
  message: "Message received",
  evidence: "Evidence gathering",
  detonation: "Detonation",
  verdict: "Verdict",
  gates: "Licence gates",
  complete: "Complete",
};

function stageOf(event: MissionEvent): StageId {
  switch (event.type) {
    case "mission.message_received":
      return "message";
    case "mission.evidence":
      return "evidence";
    case "mission.detonation":
      return "detonation";
    case "mission.verdict":
      return "verdict";
    case "mission.approval_required":
    case "mission.approval_resolved":
    case "mission.action_executed":
      return "gates";
    case "mission.complete":
    // A failed turn is terminal, same as a completed one - the mission is
    // over either way, so it maps to the same final stage. `missionDone` and
    // the "complete" node's own detail text (buildMissionPlan, below) both
    // derive from mission.complete OR mission.failed for the same reason
    // (Qodo, PR #71) - a failed mission now settles to "done" throughout the
    // tree instead of rendering as active forever.
    case "mission.failed":
      return "complete";
  }
}

const EVIDENCE_LANES: EvidenceLane[] = ["infrastructure", "identity", "history"];

const LANE_LABEL: Record<EvidenceLane, string> = {
  infrastructure: "Infrastructure",
  identity: "Identity",
  history: "History",
};

const GATE_INDICES = [1, 2, 3, 4] as const;

/** One line per event, built from its typed fields - not a JSON dump.
 *  Moved here from MissionView (T-050) since the plan tree is now what
 *  turns an event into human-readable detail text. */
export function describeEvent(event: MissionEvent): string {
  switch (event.type) {
    case "mission.message_received":
      return `From ${event.message.from}`;
    case "mission.evidence":
      return describeEvidence(event);
    case "mission.detonation":
      return "error" in event.detonation ? `Detonation failed: ${event.detonation.error}` : event.detonation.summary;
    case "mission.verdict":
      return `${event.verdict.toUpperCase()} — ${event.summary}`;
    case "mission.approval_required":
      return `Gate ${event.gate_index}/${event.gate_count} requested: ${event.action.action}`;
    case "mission.approval_resolved":
      return `Gate ${event.gate_index}: ${event.status}`;
    case "mission.action_executed":
      return event.result_summary;
    case "mission.complete":
      return event.spoken_verdict;
    // T-037 handoff: each branch reads the field its own TrueForge producer
    // publishes - TurnStateError has a message, TurnStateCancelled has only
    // a reason enum.
    case "mission.failed":
      return event.cause === "error"
        ? `Mission failed: ${event.message}`
        : `Mission cancelled: ${event.reason}`;
  }
}

function describeEvidence(event: Extract<MissionEvent, { type: "mission.evidence" }>): string {
  switch (event.lane) {
    case "infrastructure": {
      const e = event.evidence;
      if ("domain" in e) {
        return `${e.domain} — registered ${e.registration_date ?? "not published"}, cert ${e.cert_issued_at ?? "unknown"}`;
      }
      return `${e.url} — ${e.listed ? "listed on URLhaus" : "not listed on URLhaus (weak signal only)"}`;
    }
    case "identity":
      return event.evidence.lookalike_domain
        ? `Reply-To looks like a lookalike of ${event.evidence.lookalike_of ?? "a known domain"}`
        : "No lookalike domain detected";
    case "history":
      return `${event.evidence.prior_contact_count} prior contacts from ${event.evidence.domain}`;
  }
}

function stageStatus(stageIndex: number, currentIndex: number, missionDone: boolean): StageStatus {
  if (missionDone) return "done";
  if (currentIndex < 0) return "pending";
  if (stageIndex < currentIndex) return "done";
  if (stageIndex === currentIndex) return "active";
  return "pending";
}

function currentStageIndex(events: MissionEvent[]): number {
  const seenStages = new Set(events.map(stageOf));
  let index = -1;
  STAGE_ORDER.forEach((stage, i) => {
    if (seenStages.has(stage)) index = i;
  });
  return index;
}

export interface EvidenceLaneState {
  lane: EvidenceLane;
  label: string;
  status: StageStatus;
  items: Extract<MissionEvent, { type: "mission.evidence" }>[];
}

/**
 * The three evidence lanes on their own, with full typed evidence items
 * (not the plan tree's collapsed one-line join) - what T-052's dedicated
 * lane panels render. Status derivation is shared with buildMissionPlan
 * (both call this) so the tree and the lane panels can never disagree
 * about whether a lane is pending/active/done.
 */
export function buildEvidenceLanes(events: MissionEvent[]): EvidenceLaneState[] {
  const missionDone = events.some((e) => e.type === "mission.complete");
  const currentIndex = currentStageIndex(events);
  const evidenceStageIndex = STAGE_ORDER.indexOf("evidence");

  const byLane = new Map<EvidenceLane, Extract<MissionEvent, { type: "mission.evidence" }>[]>();
  for (const e of events) {
    if (e.type === "mission.evidence") {
      const list = byLane.get(e.lane) ?? [];
      list.push(e);
      byLane.set(e.lane, list);
    }
  }

  return EVIDENCE_LANES.map((lane) => {
    const items = byLane.get(lane) ?? [];
    // Stage advancement/mission completion is checked first, not item
    // count: a lane the stream moves past (or the mission finishes)
    // without ever reporting is done - it isn't still "pending" just
    // because it happens to be empty (Qodo, PR #36 finding #1). Only
    // while evidence is still the current stage does an empty lane mean
    // "hasn't reported yet" rather than "reported nothing."
    const status: StageStatus =
      currentIndex > evidenceStageIndex || missionDone ? "done" : items.length === 0 ? "pending" : "active";
    return { lane, label: LANE_LABEL[lane], status, items };
  });
}

export interface ApprovalGateState {
  gateIndex: 1 | 2 | 3 | 4;
  action?: ProposedActionName;
  /** The literal TrueForge approval request, once `approval_required`
   *  arrives - kept for provenance (event id, timestamp, thread, and the
   *  tool-call ids awaiting a decision).
   *
   *  T-037: this is NO LONGER what the panel displays. The real wire event's
   *  `tool_calls` are `ToolCallRef` - `{id, source_event_id}` only - so
   *  rendering them verbatim would show a judge two opaque ids instead of
   *  the request. The displayable request is `requestArguments` below,
   *  paired with `action`. */
  request?: ToolApprovalRequiredEvent;
  /** The decoded arguments of the gated call, from
   *  `ApprovalRequiredEvent.action.arguments` - the half of "shows the
   *  literal request" (CLAUDE.md) that survives T-037's correction. */
  requestArguments?: Record<string, unknown>;
  /** The tool call THIS gate is about, straight from the event. Never derived
   *  from `request.tool_calls[0]` - see ApprovalRequiredEvent.tool_call_id. */
  toolCallId?: string;
  resolved?: ApprovalStatus;
  reason?: string;
  resultSummary?: string;
  executed: boolean; // tracked separately from resultSummary - "" is a valid, real summary
}

/**
 * The four licence gates on their own, one fixed slot per `gate_index`,
 * populated by whichever of the three gate events actually arrived - not
 * gated behind `approval_required` specifically, since a resumed or
 * reconnected stream (T-056) can genuinely deliver `approval_resolved`/
 * `action_executed` without this client ever having seen the matching
 * request (Qodo, PR #32 finding #1). Shared by the plan tree's gate nodes
 * and T-036's ApprovalPanel so the two can't disagree about a gate's state,
 * same reasoning as buildEvidenceLanes above (T-052).
 */
export function buildApprovalGates(events: MissionEvent[]): ApprovalGateState[] {
  const gates = new Map<number, ApprovalGateState>();
  const gateState = (gateIndex: 1 | 2 | 3 | 4): ApprovalGateState => {
    const existing = gates.get(gateIndex);
    if (existing) return existing;
    const created: ApprovalGateState = { gateIndex, executed: false };
    gates.set(gateIndex, created);
    return created;
  };
  for (const e of events) {
    if (e.type === "mission.approval_required") {
      const g = gateState(e.gate_index);
      g.action = e.action.action;
      g.requestArguments = e.action.arguments;
      g.toolCallId = e.tool_call_id;
      g.request = e.approval;
      // A fresh request for a gate index that already carries a prior
      // outcome (a retried tool call, same pattern as T-053's retried
      // detonation) supersedes that outcome - without this, the terminal
      // fields from the earlier attempt would outrank the new `request`
      // in every consumer's status derivation and the retry would render
      // as still denied/executed instead of newly requested (Qodo, PR #52
      // finding #2).
      g.resolved = undefined;
      g.reason = undefined;
      g.resultSummary = undefined;
      g.executed = false;
    } else if (e.type === "mission.approval_resolved") {
      const g = gateState(e.gate_index);
      g.resolved = e.status;
      g.reason = e.reason;
    } else if (e.type === "mission.action_executed") {
      const g = gateState(e.gate_index);
      g.action ??= e.action;
      g.resultSummary = e.result_summary;
      g.executed = true;
    }
  }
  return GATE_INDICES.map((gateIndex) => gates.get(gateIndex) ?? { gateIndex, executed: false });
}

export function buildMissionPlan(events: MissionEvent[]): PlanNode[] {
  // T-037 handoff (Qodo, PR #71): a mission.failed event is terminal, same as
  // mission.complete (stageOf above already maps both to "complete") - but
  // this line only checked mission.complete, so a failed mission never
  // settled to "done" anywhere in the tree and stayed rendered as active
  // forever.
  const missionDone = events.some((e) => e.type === "mission.complete" || e.type === "mission.failed");
  const currentIndex = currentStageIndex(events);
  const indexOf = (stage: StageId) => STAGE_ORDER.indexOf(stage);

  // --- message -----------------------------------------------------------
  // findLast, not find (T-047, on §7's standing note from T-053). A re-emitted
  // message is the CURRENT one; taking the first would pin the panel to a
  // stale parse. §7 recorded this as having no known trigger — T-039/T-046
  // created one, since a resumed turn genuinely re-emits events.
  const messageEvent = events.findLast(
    (e): e is Extract<MissionEvent, { type: "mission.message_received" }> => e.type === "mission.message_received",
  );
  const messageNode: PlanNode = {
    id: "message",
    label: STAGE_LABEL.message,
    status: stageStatus(indexOf("message"), currentIndex, missionDone),
    detail: messageEvent ? describeEvent(messageEvent) : null,
  };

  // --- evidence: collapsed from the same per-lane state buildEvidenceLanes
  // exposes in full, so the tree and T-052's lane panels can't disagree ---
  const laneChildren: PlanNode[] = buildEvidenceLanes(events).map(({ lane, label, status, items }) => ({
    id: `evidence:${lane}`,
    label,
    status,
    detail: items.length > 0 ? items.map(describeEvent).join("; ") : null,
  }));
  const evidenceNode: PlanNode = {
    id: "evidence",
    label: STAGE_LABEL.evidence,
    status: stageStatus(indexOf("evidence"), currentIndex, missionDone),
    detail: null,
    children: laneChildren,
  };

  // --- detonation / verdict: single events --------------------------------
  // findLast: a retried/re-emitted detonation is a later, more current
  // result, not a duplicate to ignore (Qodo, PR #41 finding #1, DetonationPanel.tsx).
  const detonationEvent = events.findLast(
    (e): e is Extract<MissionEvent, { type: "mission.detonation" }> => e.type === "mission.detonation",
  );
  const detonationNode: PlanNode = {
    id: "detonation",
    label: STAGE_LABEL.detonation,
    status: stageStatus(indexOf("detonation"), currentIndex, missionDone),
    detail: detonationEvent ? describeEvent(detonationEvent) : null,
  };

  // findLast: a re-emitted verdict is the current judgment, not a
  // duplicate (§7, same class as T-053's detonationEvent fix).
  const verdictEvent = events.findLast(
    (e): e is Extract<MissionEvent, { type: "mission.verdict" }> => e.type === "mission.verdict",
  );
  const verdictNode: PlanNode = {
    id: "verdict",
    label: STAGE_LABEL.verdict,
    status: stageStatus(indexOf("verdict"), currentIndex, missionDone),
    detail: verdictEvent ? describeEvent(verdictEvent) : null,
  };

  // --- licence gates: 4 fixed slots, revealed as each gate is requested --
  // State comes from the shared buildApprovalGates (above) so this tree and
  // T-036's ApprovalPanel can't disagree about a gate's status.
  const gateChildren: PlanNode[] = buildApprovalGates(events).map((g) => {
    const gateIndex = g.gateIndex;
    const label = g.action ? `Gate ${gateIndex} — ${g.action}` : `Gate ${gateIndex}`;
    // "" is a genuine, valid result_summary (Qodo finding #2) - `executed`
    // tracks whether the event happened at all, not the text it carried.
    // `reason` is the human's stated reason for the allow/deny decision -
    // optional per the contract, kept visible when present rather than
    // dropped in favour of the generic status text (Qodo, PR #34 finding #1).
    const withReason = (text: string) => (g.reason ? `${text} — ${g.reason}` : text);
    if (g.executed) {
      return { id: `gate:${gateIndex}`, label, status: "done", detail: withReason(`Executed: ${g.resultSummary}`) };
    }
    if (g.resolved === "deny") {
      return { id: `gate:${gateIndex}`, label, status: "denied", detail: withReason("DENIED") };
    }
    if (g.resolved === "allow") {
      return { id: `gate:${gateIndex}`, label, status: "active", detail: withReason("Allowed — executing…") };
    }
    if (!g.action) {
      // No `approval_required` observed yet (or resolved with no action ever
      // observed, genuinely unusual) - every field here is independently
      // optional per the contract, so render what's known rather than
      // assume a shape that isn't there.
      return { id: `gate:${gateIndex}`, label, status: "pending", detail: null };
    }
    return {
      id: `gate:${gateIndex}`,
      label,
      status: "active",
      detail: "Awaiting approval",
    };
  });
  const gatesNode: PlanNode = {
    id: "gates",
    label: STAGE_LABEL.gates,
    status: stageStatus(indexOf("gates"), currentIndex, missionDone),
    detail: null,
    children: gateChildren,
  };

  // --- complete ------------------------------------------------------------
  // Same handoff as missionDone above: the "complete" node's own detail text
  // must come from whichever terminal event actually happened, not just the
  // success one - describeEvent already renders both.
  // findLast for the same reason, and it matters more here than anywhere else
  // in this file: this lookup matches TWO event types, so with `find` a
  // mission that completed and then failed would render the earlier SUCCESS
  // and hide the failure. That is the worst possible direction for this
  // particular node to be wrong in (T-047).
  const completeEvent = events.findLast(
    (e): e is Extract<MissionEvent, { type: "mission.complete" | "mission.failed" }> =>
      e.type === "mission.complete" || e.type === "mission.failed",
  );
  const completeNode: PlanNode = {
    id: "complete",
    label: STAGE_LABEL.complete,
    status: stageStatus(indexOf("complete"), currentIndex, missionDone),
    detail: completeEvent ? describeEvent(completeEvent) : null,
  };

  return [messageNode, evidenceNode, detonationNode, verdictNode, gatesNode, completeNode];
}
