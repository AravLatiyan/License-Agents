import type { ApprovalStatus, MissionEvent, ProposedActionName } from "../../contracts/events";
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
 * for a gated tool call - the literal JSON request, which since T-037 means
 * the resolved tool name and decoded arguments rather than the wire event's
 * bare ToolCallRefs - in our styling, same
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
/** T-046: how a click reaches TrueForge. Optional on purpose — with no live
 *  session (fixture playback, or a clean clone with no server) there is
 *  nothing to resume, and the buttons stay honestly disabled exactly as
 *  before rather than pretending to work. */
export type ApprovalDecisionHandler = (decision: {
  gateIndex: 1 | 2 | 3 | 4;
  threadId: string;
  toolCallId: string;
  status: ApprovalStatus;
}) => void;

export function ApprovalPanel({
  events,
  onDecision,
  pendingGates,
}: {
  events: MissionEvent[];
  onDecision?: ApprovalDecisionHandler;
  /** Gates whose decision is mid-flight; their buttons lock until it lands. */
  pendingGates?: ReadonlySet<number>;
}) {
  const gates = buildApprovalGates(events);
  return (
    <section className="approval-panel" aria-label="Licence gates">
      <h2>Licence gates</h2>
      <ol className="approval-gates">
        {gates.map((gate) => (
          <ApprovalGateCard
            key={gate.gateIndex}
            gate={gate}
            onDecision={onDecision}
            pending={pendingGates?.has(gate.gateIndex) ?? false}
          />
        ))}
      </ol>
    </section>
  );
}

function ApprovalGateCard({
  gate,
  onDecision,
  pending = false,
}: {
  gate: ReturnType<typeof buildApprovalGates>[number];
  onDecision?: ApprovalDecisionHandler;
  pending?: boolean;
}) {
  // The gate can only be decided if we know which tool call it belongs to.
  // That comes from the raw approval event TrueForge sent, so a gate rebuilt
  // from a reconnect that never saw the request (missionPlan tolerates that,
  // T-056) correctly stays undecidable rather than submitting a guess.
  const toolCallId = gate.toolCallId ?? null;
  const threadId = gate.request?.thread_id ?? null;
  const canDecide = Boolean(onDecision && toolCallId && threadId) && !pending;
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
          role="status" on the whole card would announce the entire request
          JSON verbatim (and do so from four independent regions
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
          {/* T-037: the wire event's tool_calls are ToolCallRef - {id,
              source_event_id} - so rendering them verbatim would show two
              opaque ids, not the request. The literal request a judge needs
              to read is the resolved tool name plus its decoded arguments. */}
          <pre className="approval-gate__request">
            {JSON.stringify(
              { tool: gate.action ?? null, arguments: gate.requestArguments ?? {} },
              null,
              2,
            )}
          </pre>
        </>
      )}

      {status === "requested" && (
        <div className="approval-gate__actions">
          <button
            type="button"
            disabled={!canDecide}
            title={pending ? "Submitting…" : canDecide ? "Grant the licence for this action" : "No live TrueForge turn to resume"}
            onClick={() =>
              canDecide &&
              onDecision?.({ gateIndex: gate.gateIndex, threadId: threadId!, toolCallId: toolCallId!, status: "allow" })
            }
          >
            Allow
          </button>
          <button
            type="button"
            disabled={!canDecide}
            title={pending ? "Submitting…" : canDecide ? "Refuse the licence for this action" : "No live TrueForge turn to resume"}
            onClick={() =>
              canDecide &&
              onDecision?.({ gateIndex: gate.gateIndex, threadId: threadId!, toolCallId: toolCallId!, status: "deny" })
            }
          >
            Deny
          </button>
          {pending && <p className="approval-gate__note">Submitting decision…</p>}
          {!canDecide && !pending && (
            <p className="approval-gate__note">
              Presentation only — no live TrueForge turn to resume (fixture playback).
            </p>
          )}
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
