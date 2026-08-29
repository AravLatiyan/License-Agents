import { useMemo } from "react";
import missionHappyPath from "../../contracts/fixtures/mission-happy-path.json";
import { ApprovalPanel } from "./ApprovalPanel";
import { DetonationPanel } from "./DetonationPanel";
import { EvidenceLanes } from "./EvidenceLanes";
import { MissionView } from "./MissionView";
import { SpokenVerdict } from "./SpokenVerdict";
import { VerdictPanel } from "./VerdictPanel";
import { fixtureEventSource } from "./missionSource";
import { trueForgeEventSource } from "./trueForgeSource";
import { useMissionEvents } from "./useMissionEvents";

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

const source =
  liveBaseUrl && liveInput
    ? trueForgeEventSource({ baseUrl: liveBaseUrl, agentName: liveAgentName, input: liveInput })
    : fixtureEventSource(missionHappyPath as unknown[]);

const sourceLabel = liveBaseUrl && liveInput ? "live TrueForge" : "fixture playback";

function App() {
  const stableSource = useMemo(() => source, []);
  const { events, status, error } = useMissionEvents(stableSource);

  return (
    <main className="cockpit">
      <h1>UNIVERSAL IMPORTS — Cockpit</h1>
      <p className="cockpit__status">
        <span className="cockpit__source">{sourceLabel}</span>{" "}
        {status === "streaming" && `Receiving mission events… (${events.length} so far)`}
        {status === "complete" && `Mission complete — ${events.length} events`}
        {status === "error" && `Error: ${error}`}
      </p>
      <EvidenceLanes events={events} />
      <DetonationPanel events={events} />
      <VerdictPanel events={events} />
      <ApprovalPanel events={events} />
      <MissionView events={events} />
      <SpokenVerdict events={events} />
    </main>
  );
}

export default App;
