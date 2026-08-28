import { useMemo } from "react";
import missionHappyPath from "../../contracts/fixtures/mission-happy-path.json";
import { DetonationPanel } from "./DetonationPanel";
import { EvidenceLanes } from "./EvidenceLanes";
import { MissionView } from "./MissionView";
import { VerdictPanel } from "./VerdictPanel";
import { fixtureEventSource } from "./missionSource";
import { useMissionEvents } from "./useMissionEvents";

// The fixture is loaded as unknown, not assumed to already be MissionEvent[]:
// TypeScript's JSON-module inference widens string literals (e.g. "type") to
// `string`, so it can't actually prove the shape - assertMissionEvent does
// that for real, at runtime, one event at a time.
const source = fixtureEventSource(missionHappyPath as unknown[]);

function App() {
  const stableSource = useMemo(() => source, []);
  const { events, status, error } = useMissionEvents(stableSource);

  return (
    <main className="cockpit">
      <h1>UNIVERSAL IMPORTS — Cockpit</h1>
      <p className="cockpit__status">
        {status === "streaming" && `Receiving mission events… (${events.length} so far)`}
        {status === "complete" && `Mission complete — ${events.length} events`}
        {status === "error" && `Error: ${error}`}
      </p>
      <EvidenceLanes events={events} />
      <DetonationPanel events={events} />
      <VerdictPanel events={events} />
      <MissionView events={events} />
    </main>
  );
}

export default App;
