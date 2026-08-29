import { useCallback, useMemo, useState } from "react";
import missionHappyPath from "../../contracts/fixtures/mission-happy-path.json";
import { ApprovalPanel } from "./ApprovalPanel";
import { DetonationPanel } from "./DetonationPanel";
import { EvidenceLanes } from "./EvidenceLanes";
import { MissionView } from "./MissionView";
import { SpokenVerdict } from "./SpokenVerdict";
import { VerdictPanel } from "./VerdictPanel";
import { fixtureEventSource } from "./missionSource";
import { createTrueForgeMission } from "./trueForgeSource";
import { useMissionEvents } from "./useMissionEvents";
import type { ApprovalDecisionHandler } from "./ApprovalPanel";
import type { MissionEvent } from "../../contracts/events";

// The fixture is loaded as unknown, not assumed to already be MissionEvent[]:
// TypeScript's JSON-module inference widens string literals (e.g. "type") to
// `string`, so it can't actually prove the shape - assertMissionEvent does
// that for real, at runtime, one event at a time.

// T-039: the live source is opt-in, not the default. Point VITE_TRUEFORGE_URL
// at a running TrueForge (e.g. http://localhost:8790/api/v1) and this app
// drives a real turn through the T-037 translator instead of replaying the
// fixture. Left opt-in deliberately: a clean clone with no server running
// must still show the full mission (rule 5 / T-065), and §17's demo depends
// on that fallback existing. Everything downstream only ever sees
// MissionEvent and cannot tell which source produced it.
const liveBaseUrl = import.meta.env.VITE_TRUEFORGE_URL;
const liveAgentName = import.meta.env.VITE_TRUEFORGE_AGENT ?? "universal-imports";
const liveInput = import.meta.env.VITE_TRUEFORGE_INPUT;

// T-046: the live mission carries a submit path beside its event source. On
// the fixture path there is no mission and no handler, so the Allow/Deny
// buttons stay disabled exactly as they were.
const liveMission =
  liveBaseUrl && liveInput
    ? createTrueForgeMission({ baseUrl: liveBaseUrl, agentName: liveAgentName, input: liveInput })
    : null;

const source = liveMission ? liveMission.source : fixtureEventSource(missionHappyPath as unknown[]);

const sourceLabel = liveBaseUrl && liveInput ? "live TrueForge" : "fixture playback";

function App() {
  const stableSource = useMemo(() => source, []);
  const { events, status, error } = useMissionEvents(stableSource);

  // A human's decision produces events the stream itself can never carry:
  // TrueForge's turn stream has nothing between tool.approval_required and the
  // next turn.done, so `mission.approval_resolved` (and whichever gate that
  // releases) is constructed locally by the code that made the decision.
  // Held beside the streamed events rather than pushed into useMissionEvents,
  // which stays a read-only consumer.
  const [decisionEvents, setDecisionEvents] = useState<MissionEvent[]>([]);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  // Gates with a decision already in flight. Without this, the buttons stay
  // live during the async POST, so a double-click (or an Allow then a Deny)
  // sends two resumes for the same gate and appends two resolution events,
  // leaving the displayed outcome dependent on response order (Qodo, PR #85).
  // A licence decision is exactly the wrong thing to let race.
  const [pendingGates, setPendingGates] = useState<ReadonlySet<number>>(new Set());

  const onDecision = useCallback<ApprovalDecisionHandler>((decision) => {
    if (!liveMission) return;
    let alreadyPending = false;
    setPendingGates((prev) => {
      if (prev.has(decision.gateIndex)) {
        alreadyPending = true;
        return prev;
      }
      return new Set(prev).add(decision.gateIndex);
    });
    if (alreadyPending) return;

    void liveMission
      .submitApproval(decision)
      .then((produced) => setDecisionEvents((prev) => [...prev, ...produced]))
      .catch((err: unknown) => setDecisionError(err instanceof Error ? err.message : String(err)))
      .finally(() =>
        setPendingGates((prev) => {
          const next = new Set(prev);
          next.delete(decision.gateIndex);
          return next;
        }),
      );
  }, []);

  const allEvents = decisionEvents.length === 0 ? events : [...events, ...decisionEvents];

  return (
    <main className="cockpit">
      <h1>UNIVERSAL IMPORTS — Cockpit</h1>
      <p className="cockpit__status">
        <span className="cockpit__source">{sourceLabel}</span>{" "}
        {status === "streaming" && `Receiving mission events… (${events.length} so far)`}
        {status === "complete" && `Mission complete — ${events.length} events`}
        {status === "error" && `Error: ${error}`}
        {decisionError && ` · licence decision failed: ${decisionError}`}
      </p>
      <EvidenceLanes events={allEvents} />
      <DetonationPanel events={allEvents} />
      <VerdictPanel events={allEvents} />
      <ApprovalPanel events={allEvents} onDecision={liveMission ? onDecision : undefined} pendingGates={pendingGates} />
      <MissionView events={allEvents} />
      <SpokenVerdict events={allEvents} />
    </main>
  );
}

export default App;
