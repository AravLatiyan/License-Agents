import type { MissionEvent } from "../../contracts/events";

/** One short, human-readable line per event, built from its typed fields -
 *  not a JSON dump. Each case only exists because T-050 needs to prove the
 *  event stream is distinguishable; the real evidence/detonation/verdict
 *  panels are later tasks (T-052/T-053/T-054), not this. */
function describe(event: MissionEvent): string {
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

const LANE_LABEL: Record<string, string> = {
  infrastructure: "INFRASTRUCTURE",
  identity: "IDENTITY",
  history: "HISTORY",
};

function label(event: MissionEvent): string {
  if (event.type === "mission.evidence") return `Evidence — ${LANE_LABEL[event.lane]}`;
  return event.type.replace("mission.", "").replace(/_/g, " ");
}

export function MissionView({ events }: { events: MissionEvent[] }) {
  return (
    <ol className="mission-view">
      {events.map((event, i) => (
        <li key={i} className={`mission-event mission-event--${event.type}`}>
          <span className="mission-event__label">{label(event)}</span>
          <span className="mission-event__detail">{describe(event)}</span>
        </li>
      ))}
    </ol>
  );
}
