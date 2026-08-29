import type { MissionEvent, ProposedActionName } from "../../contracts/events";
import { buildApprovalGates } from "./missionPlan";

const ACTION_LABEL: Record<ProposedActionName, string> = {
  quarantine: "Quarantine message",
  notify_impersonated: "Notify impersonated party",
  create_block_rule: "Create block rule",
  file_abuse_report: "File abuse report",
};

/**
 * T-036: the LICENCE REQUIRED panel (§17, 1:50-2:20) - four sequential
 * per-tool-call gates, not one modal with four checkboxes (§6, 2026-08-24).
 * Each card mirrors what TrueForge's own native approval UI already shows
 * for a gated tool call - the literal JSON request - in our styling, same
 * "configure it, don't rebuild it" relationship DetonationPanel/VerdictPanel
 * already have to their own data.
 *
 * Presentation half only (§2/§8): a real Allow/Deny click would need to
 * resume a live TrueForge turn via `user.tool_approval`, which has nowhere
 * to submit to until the undecided TrueForge->`mission.*` translation layer
 * (§8, T-056/T-036 entries) exists. Rendered as an honest disabled state
 * with that fact stated plainly, not faked - same pattern as
 * DetonationPanel's "no screenshot" state (CLAUDE.md: don't guess API
 * behavior, don't build fake functionality).
 */
export function ApprovalPanel({ events }: { events: MissionEvent[] }) {
  const gates = buildApprovalGates(events);
  return (
    <section className="approval-panel" aria-label="Licence gates">
      <h2>Licence gates</h2>
      <ol className="approval-gates">
        {gates.map((gate) => (
          <ApprovalGateCard key={gate.gateIndex} gate={gate} />
        ))}
      </ol>
    </section>
  );
}

function ApprovalGateCard({ gate }: { gate: ReturnType<typeof buildApprovalGates>[number] }) {
  const label = gate.action ? ACTION_LABEL[gate.action] : null;

  let status: "pending" | "requested" | "allowed" | "denied" | "executed";
  if (gate.executed) status = "executed";
  else if (gate.resolved === "deny") status = "denied";
  else if (gate.resolved === "allow") status = "allowed";
  else if (gate.request) status = "requested";
  else status = "pending";

  return (
    <li className={`approval-gate approval-gate--${status}`}>
      {/* A concise, textual live region separate from the visible card -
          role="status" on the whole card would announce the entire raw
          tool_calls JSON verbatim (and do so from four independent regions
          at once) instead of a short state change (Qodo, PR #52 finding
          #3). This element carries only the short summary text; the JSON
          and visible UI below stay out of the live region entirely. */}
      <span className="sr-only" role="status">
        {statusAnnouncement(gate.gateIndex, status, label, gate.reason)}
      </span>
      <div className="approval-gate__header">
        <span className="approval-gate__index">
          Gate {gate.gateIndex}/4
        </span>
        <span className="approval-gate__title">{label ?? "Awaiting request…"}</span>
      </div>

      {gate.request && (
        <>
          <p className="approval-gate__banner">LICENCE REQUIRED</p>
          <pre className="approval-gate__request">
            {JSON.stringify(gate.request.tool_calls, null, 2)}
          </pre>
        </>
      )}

      {status === "requested" && (
        <div className="approval-gate__actions">
          <button type="button" disabled title="Live submission not wired yet — see PLAN.md §8">
            Allow
          </button>
          <button type="button" disabled title="Live submission not wired yet — see PLAN.md §8">
            Deny
          </button>
          <p className="approval-gate__note">
            Presentation only — no live TrueForge turn to resume yet (§8).
          </p>
        </div>
      )}

      {status === "allowed" && <p className="approval-gate__outcome">Allowed — executing…</p>}
      {status === "denied" && (
        <p className="approval-gate__outcome">DENIED{gate.reason ? ` — ${gate.reason}` : ""}</p>
      )}
      {status === "executed" && (
        <p className="approval-gate__outcome">
          Executed: {gate.resultSummary}
          {gate.reason ? ` — ${gate.reason}` : ""}
        </p>
      )}
      {status === "pending" && <p className="approval-gate__outcome approval-gate__outcome--empty">Waiting…</p>}
    </li>
  );
}

/** Short text for the sr-only live region above - never the raw JSON. */
function statusAnnouncement(
  gateIndex: number,
  status: "pending" | "requested" | "allowed" | "denied" | "executed",
  label: string | null,
  reason: string | undefined,
): string {
  const prefix = `Gate ${gateIndex}${label ? ` (${label})` : ""}`;
  switch (status) {
    case "pending":
      return `${prefix}: waiting`;
    case "requested":
      return `${prefix}: licence required`;
    case "allowed":
      return `${prefix}: allowed, executing`;
    case "denied":
      return `${prefix}: denied${reason ? ` — ${reason}` : ""}`;
    case "executed":
      return `${prefix}: executed`;
  }
}
