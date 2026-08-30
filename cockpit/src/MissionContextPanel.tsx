// cockpit/src/MissionContextPanel.tsx
//
// The "Agent investigation" drawer: a fixed-width panel docked on top of
// ReadingPane's right edge (§17 still holds), built entirely from the same
// buildEvidenceLanes/buildApprovalGates/describeEvent helpers the plan tree
// and the legacy panels already used - no new event derivation, only new
// presentation. Message identity (subject/From/Reply-To/To) now lives in
// ReadingPane, which reads it straight from Mailpit - this panel only ever
// shows what the agent found and what it's asking permission to do.
//
// Local UI state (which action is expanded, whether the full investigation
// is open) is deliberately owned here, not lifted to App - the caller
// remounts this component with a fresh `key` per selected email (App.tsx),
// so switching emails always starts clean rather than carrying one email's
// expanded action into another's panel.
import { useState } from "react";
import type { MissionEvent, ProposedActionName } from "../../contracts/events";
import { DetonationPanel } from "./DetonationPanel";
import { EvidenceLanes } from "./EvidenceLanes";
import type { ApprovalDecisionHandler } from "./ApprovalPanel";
import { buildApprovalGates, buildEvidenceLanes, describeEvent, type ApprovalGateState } from "./missionPlan";
import { MissionView } from "./MissionView";
import { SpokenVerdict } from "./SpokenVerdict";

// Presentation only - never the source of truth for what runs. The backend
// (harness/translate/translate.ts's isGatedActionName, contracts/events.ts's
// ProposedActionName) decides which actions exist and when one is proposed;
// this map only decides how to word the ones it happens to recognise. A
// `Partial` record, not the exhaustive one TypeScript would otherwise want,
// because that's the honest shape: some action id may not be in here.
const ACTION_LABEL: Partial<Record<string, string>> = {
  quarantine: "Quarantine message",
  notify_impersonated: "Notify impersonated party",
  create_block_rule: "Create block rule",
  file_abuse_report: "File abuse report",
};

const ACTION_BLURB: Partial<Record<string, string>> = {
  quarantine: "Move this message out of the inbox so it cannot be interacted with.",
  notify_impersonated: "Alert the real account owner that someone may be impersonating them.",
  create_block_rule: "Prevent future messages matching this pattern.",
  file_abuse_report: "Submit the relevant domain to the registrar abuse contact.",
};

/** "some_new_action" -> "Some new action" - the fallback for any action id
 *  this cockpit hasn't been taught a proper label for yet. Keeps an
 *  unrecognised backend action presentable instead of either crashing or
 *  silently vanishing from the list (§5). */
function humanizeActionId(id: string): string {
  const words = id.split(/[_-]+/).filter(Boolean);
  if (words.length === 0) return id;
  return [words[0][0].toUpperCase() + words[0].slice(1), ...words.slice(1)].join(" ");
}

export function MissionContextPanel({
  events,
  missionId,
  onDecision,
  pendingGates,
  onDismiss,
}: {
  events: MissionEvent[];
  /** Shown in the drawer header as this investigation's id - the mission's
   *  own message_id (App.tsx), never invented. */
  missionId: string | null;
  onDecision?: ApprovalDecisionHandler;
  pendingGates?: ReadonlySet<number>;
  onDismiss: () => void;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  // Which gate's detail is currently expanded. Only one at a time - the
  // sequential-gate design (§6/CLAUDE.md) means at most one gate is ever
  // actually outstanding anyway, but this also governs an already-resolved
  // action a user wants to re-open and read.
  const [expandedGate, setExpandedGate] = useState<number | null>(null);
  // Gates the user has actually clicked at least once. A "recommended"
  // action must not reveal its real state (requested/allowed/executed/
  // denied) until the user selects it - otherwise a fixture (or any stream
  // that already contains a resolved history by the time this panel opens)
  // renders every action as already DONE before anyone asked for anything.
  // Sticky, not tied to `expandedGate`: once revealed, a collapsed row still
  // shows its true status rather than reverting to "Recommended".
  const [revealedGates, setRevealedGates] = useState<ReadonlySet<number>>(new Set());

  const revealGate = (gateIndex: number) => {
    setRevealedGates((prev) => (prev.has(gateIndex) ? prev : new Set(prev).add(gateIndex)));
    setExpandedGate((prev) => (prev === gateIndex ? null : gateIndex));
  };

  const verdictEvent = events.findLast((e): e is Extract<MissionEvent, { type: "mission.verdict" }> => e.type === "mission.verdict");
  const failedEvent = events.findLast((e): e is Extract<MissionEvent, { type: "mission.failed" }> => e.type === "mission.failed");
  const lanes = buildEvidenceLanes(events);
  const allGates = buildApprovalGates(events);
  const gates = allGates.filter((g): g is ApprovalGateState & { action: ProposedActionName } => g.action !== undefined);
  const grantedCount = allGates.filter((g) => g.executed).length;

  const detonationEvent = events.findLast((e): e is Extract<MissionEvent, { type: "mission.detonation" }> => e.type === "mission.detonation");
  const completeEvent = events.findLast((e): e is Extract<MissionEvent, { type: "mission.complete" }> => e.type === "mission.complete");

  const findings: string[] = [];
  for (const lane of lanes) {
    for (const item of lane.items) findings.push(describeEvent(item));
  }
  if (detonationEvent) findings.push(describeEvent(detonationEvent));

  const verdict = verdictEvent?.verdict ?? null;
  const investigating = !verdictEvent && !failedEvent;

  return (
    <aside className="investigation-drawer" aria-label="Message investigation" role="dialog" aria-modal="false">
      <div className="investigation-drawer__header">
        <span className="investigation-drawer__title">Agent investigation</span>
        <span className="investigation-drawer__spacer" />
        {missionId && <span className="investigation-drawer__id">{missionId}</span>}
        <button type="button" className="investigation-drawer__dismiss" onClick={onDismiss} aria-label="Close investigation panel">
          ×
        </button>
      </div>

      <div className="investigation-drawer__body">
        {investigating && (
          <p className="mission-panel__investigating" role="status">
            Investigating… ({events.length} events so far)
          </p>
        )}

        {failedEvent && (
          <p className="mission-panel__failed" role="status">
            {failedEvent.cause === "error" ? `Investigation failed: ${failedEvent.message}` : `Investigation cancelled: ${failedEvent.reason}`}
          </p>
        )}

        {verdictEvent && <VerdictSummary verdict={verdictEvent.verdict} summary={verdictEvent.summary} />}

        {findings.length > 0 && (
          <section className="mission-panel__findings">
            <h3>{verdict === "legitimate" ? "What we checked" : "Why this looks suspicious"}</h3>
            <ul>
              {findings.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </section>
        )}

        {verdictEvent && (
          <section className="mission-panel__actions">
            <div className="mission-panel__actions-header">
              <h3>{gates.length > 0 ? "What should you do?" : "No action needed"}</h3>
              {gates.length > 0 && <span className="mission-panel__actions-count">{grantedCount} of {allGates.length} granted</span>}
            </div>
            {gates.length === 0 && verdict === "legitimate" && <p className="mission-panel__note">Nothing here needs a response.</p>}
            {gates.length > 0 && (
              <ul className="mission-panel__action-list">
                {gates.map((gate) => (
                  <ActionRow
                    key={gate.gateIndex}
                    gate={gate}
                    open={expandedGate === gate.gateIndex}
                    revealed={revealedGates.has(gate.gateIndex)}
                    onToggle={() => revealGate(gate.gateIndex)}
                    onDecision={onDecision}
                    pending={pendingGates?.has(gate.gateIndex) ?? false}
                  />
                ))}
              </ul>
            )}
          </section>
        )}

        {completeEvent && <SpokenVerdict events={events} />}

        {detailsOpen && (
          <div className="mission-panel__details">
            <EvidenceLanes events={events} />
            <DetonationPanel events={events} />
            <MissionView events={events} />
          </div>
        )}
      </div>

      <div className="investigation-drawer__footer">
        <button type="button" className="mission-panel__toggle-details" onClick={() => setDetailsOpen((v) => !v)} aria-expanded={detailsOpen}>
          {detailsOpen ? "Hide full investigation" : "View full investigation"}
        </button>
      </div>
    </aside>
  );
}

function VerdictSummary({ verdict, summary }: { verdict: "malicious" | "suspicious" | "legitimate"; summary: string }) {
  return (
    <div className={`mission-panel__verdict mission-panel__verdict--${verdict}`}>
      <p className="mission-panel__verdict-label">{verdict === "legitimate" ? "Looks legitimate" : verdict === "malicious" ? "Malicious" : "Suspicious"}</p>
      <p className="mission-panel__verdict-summary">{summary}</p>
    </div>
  );
}

/** Every state this row can actually be in. "recommended" is a frontend-only
 *  concept layered on top of the real ones below it (§7/§8: distinct states,
 *  not collapsed into one) - it means "the backend has proposed this action,
 *  but the user hasn't looked at it yet," and is what keeps an
 *  already-resolved history (a fixture, a reconnect) from rendering as
 *  already-DONE before anyone asked. The other four come straight from the
 *  gate's own event data, unchanged. There is deliberately no "failed" state
 *  here: ActionExecutedEvent (contracts/events.ts) carries only
 *  `result_summary: string`, no success/failure field, so a genuine
 *  execution failure cannot be distinguished from a success by this
 *  contract today - inventing one by guessing from the summary text would
 *  be exactly the fabricated behaviour this component exists to avoid. */
type ActionState = "recommended" | "requested" | "allowed" | "denied" | "executed";

function ActionRow({
  gate,
  open,
  revealed,
  onToggle,
  onDecision,
  pending,
}: {
  gate: ApprovalGateState & { action: ProposedActionName };
  open: boolean;
  /** Has the user clicked this row at least once? Until they do, its real
   *  state stays hidden - see the module comment on ActionState. */
  revealed: boolean;
  onToggle: () => void;
  onDecision?: ApprovalDecisionHandler;
  pending: boolean;
}) {
  const label = ACTION_LABEL[gate.action] ?? humanizeActionId(gate.action);
  const blurb = ACTION_BLURB[gate.action] ?? "Recommended based on the investigation's findings.";

  const realState: Exclude<ActionState, "recommended"> = gate.executed
    ? "executed"
    : gate.resolved === "deny"
      ? "denied"
      : gate.resolved === "allow"
        ? "allowed"
        : "requested";
  const state: ActionState = revealed ? realState : "recommended";

  const toolCallId = gate.toolCallId ?? null;
  const threadId = gate.request?.thread_id ?? null;
  const canDecide = Boolean(onDecision && toolCallId && threadId) && !pending;

  return (
    <li className={`action-row action-row--${state}`}>
      <button type="button" className="action-row__summary" onClick={onToggle} aria-expanded={open}>
        <span className="action-row__label">
          {gate.gateIndex}. {label}
        </span>
        <span className="action-row__status">
          {state === "recommended" && "Recommended ▸"}
          {state === "requested" && "Licence required"}
          {state === "allowed" && "Executing…"}
          {state === "denied" && "Denied"}
          {state === "executed" && "Executed"}
        </span>
      </button>
      {!open ? (
        state === "executed" && <p className="action-row__inline-result">✓ {gate.resultSummary}</p>
      ) : (
        <div className="action-row__detail">
          <p className="action-row__blurb">{blurb}</p>

          {state === "recommended" && <p className="action-row__note">Select to review and decide.</p>}

          {state === "requested" && (
            <>
              <p className="action-row__banner">LICENCE REQUIRED</p>
              <pre className="action-row__request">{JSON.stringify(gate.requestArguments ?? {}, null, 2)}</pre>
              <div className="action-row__buttons">
                <button
                  type="button"
                  disabled={!canDecide}
                  onClick={() => canDecide && onDecision?.({ gateIndex: gate.gateIndex, threadId: threadId!, toolCallId: toolCallId!, status: "allow" })}
                >
                  Approve
                </button>
                <button
                  type="button"
                  disabled={!canDecide}
                  onClick={() => canDecide && onDecision?.({ gateIndex: gate.gateIndex, threadId: threadId!, toolCallId: toolCallId!, status: "deny" })}
                >
                  Deny
                </button>
              </div>
              {pending && <p className="action-row__note">Submitting…</p>}
              {!canDecide && !pending && <p className="action-row__note">Presentation only — no live TrueForge turn to resume (fixture playback).</p>}
            </>
          )}

          {state === "allowed" && <p className="action-row__progress">{label}…</p>}
          {state === "denied" && <p className="action-row__outcome">Denied{gate.reason ? ` — ${gate.reason}` : ""}</p>}
          {state === "executed" && <p className="action-row__outcome">✓ {gate.resultSummary}</p>}
        </div>
      )}
    </li>
  );
}
