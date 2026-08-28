import type { EvidenceLane, MissionEvent } from "../../contracts/events";

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

interface GateState {
  action?: string;
  resolved?: "allow" | "deny";
  resultSummary?: string;
  executed: boolean; // tracked separately from resultSummary - "" is a valid, real summary
}

export function buildMissionPlan(events: MissionEvent[]): PlanNode[] {
  const missionDone = events.some((e) => e.type === "mission.complete");
  const seenStages = new Set(events.map(stageOf));
  let currentIndex = -1;
  STAGE_ORDER.forEach((stage, i) => {
    if (seenStages.has(stage)) currentIndex = i;
  });
  const indexOf = (stage: StageId) => STAGE_ORDER.indexOf(stage);

  // --- message -----------------------------------------------------------
  const messageEvent = events.find(
    (e): e is Extract<MissionEvent, { type: "mission.message_received" }> => e.type === "mission.message_received",
  );
  const messageNode: PlanNode = {
    id: "message",
    label: STAGE_LABEL.message,
    status: stageStatus(indexOf("message"), currentIndex, missionDone),
    detail: messageEvent ? describeEvent(messageEvent) : null,
  };

  // --- evidence: 3 fixed lanes, populated by whatever evidence arrived ---
  const evidenceByLane = new Map<EvidenceLane, Extract<MissionEvent, { type: "mission.evidence" }>[]>();
  for (const e of events) {
    if (e.type === "mission.evidence") {
      const list = evidenceByLane.get(e.lane) ?? [];
      list.push(e);
      evidenceByLane.set(e.lane, list);
    }
  }
  const evidenceStageIndex = indexOf("evidence");
  const laneChildren: PlanNode[] = EVIDENCE_LANES.map((lane) => {
    const laneEvents = evidenceByLane.get(lane) ?? [];
    const hasEvents = laneEvents.length > 0;
    const status: StageStatus = !hasEvents
      ? "pending"
      : currentIndex > evidenceStageIndex || missionDone
        ? "done"
        : "active";
    return {
      id: `evidence:${lane}`,
      label: LANE_LABEL[lane],
      status,
      detail: hasEvents ? laneEvents.map(describeEvent).join("; ") : null,
    };
  });
  const evidenceNode: PlanNode = {
    id: "evidence",
    label: STAGE_LABEL.evidence,
    status: stageStatus(evidenceStageIndex, currentIndex, missionDone),
    detail: null,
    children: laneChildren,
  };

  // --- detonation / verdict: single events --------------------------------
  const detonationEvent = events.find(
    (e): e is Extract<MissionEvent, { type: "mission.detonation" }> => e.type === "mission.detonation",
  );
  const detonationNode: PlanNode = {
    id: "detonation",
    label: STAGE_LABEL.detonation,
    status: stageStatus(indexOf("detonation"), currentIndex, missionDone),
    detail: detonationEvent ? describeEvent(detonationEvent) : null,
  };

  const verdictEvent = events.find(
    (e): e is Extract<MissionEvent, { type: "mission.verdict" }> => e.type === "mission.verdict",
  );
  const verdictNode: PlanNode = {
    id: "verdict",
    label: STAGE_LABEL.verdict,
    status: stageStatus(indexOf("verdict"), currentIndex, missionDone),
    detail: verdictEvent ? describeEvent(verdictEvent) : null,
  };

  // --- licence gates: 4 fixed slots, revealed as each gate is requested --
  //
  // Each of the three gate events is independently valid on its own per the
  // shared contract/runtime validator - a resumed or reconnected stream
  // (T-056) can genuinely deliver `approval_resolved`/`action_executed`
  // without this client ever having seen the matching `approval_required`
  // (Qodo, PR #32 finding #1). So state is built from whichever events
  // arrived, not gated behind `approval_required` specifically - both
  // `approval_required` and `action_executed` carry the action name, either
  // one is enough to label the gate.
  const gates = new Map<number, GateState>();
  const gateState = (gateIndex: number): GateState => {
    const existing = gates.get(gateIndex);
    if (existing) return existing;
    const created: GateState = { executed: false };
    gates.set(gateIndex, created);
    return created;
  };
  for (const e of events) {
    if (e.type === "mission.approval_required") {
      gateState(e.gate_index).action = e.action.action;
    } else if (e.type === "mission.approval_resolved") {
      gateState(e.gate_index).resolved = e.status;
    } else if (e.type === "mission.action_executed") {
      const g = gateState(e.gate_index);
      g.action ??= e.action;
      g.resultSummary = e.result_summary;
      g.executed = true;
    }
  }
  const gateChildren: PlanNode[] = GATE_INDICES.map((gateIndex) => {
    const g = gates.get(gateIndex);
    const label = g?.action ? `Gate ${gateIndex} — ${g.action}` : `Gate ${gateIndex}`;
    if (!g) {
      return { id: `gate:${gateIndex}`, label, status: "pending", detail: null };
    }
    // "" is a genuine, valid result_summary (Qodo finding #2) - `executed`
    // tracks whether the event happened at all, not the text it carried.
    if (g.executed) {
      return { id: `gate:${gateIndex}`, label, status: "done", detail: `Executed: ${g.resultSummary}` };
    }
    if (g.resolved === "deny") {
      return { id: `gate:${gateIndex}`, label, status: "denied", detail: "DENIED" };
    }
    if (g.resolved === "allow") {
      return { id: `gate:${gateIndex}`, label, status: "active", detail: "Allowed — executing…" };
    }
    if (!g.action) {
      // Resolved (somehow) with no action ever observed - genuinely unusual,
      // but every field here is independently optional per the contract, so
      // render what's known rather than assume a shape that isn't there.
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
  const completeEvent = events.find(
    (e): e is Extract<MissionEvent, { type: "mission.complete" }> => e.type === "mission.complete",
  );
  const completeNode: PlanNode = {
    id: "complete",
    label: STAGE_LABEL.complete,
    status: stageStatus(indexOf("complete"), currentIndex, missionDone),
    detail: completeEvent ? describeEvent(completeEvent) : null,
  };

  return [messageNode, evidenceNode, detonationNode, verdictNode, gatesNode, completeNode];
}
