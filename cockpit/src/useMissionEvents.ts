import { useEffect, useState } from "react";
import type { MissionEvent } from "../../contracts/events";
import type { MissionEventSource } from "./missionSource";

export interface MissionConsumerState {
  events: MissionEvent[];
  status: "streaming" | "complete" | "error";
  error: string | null;
}

/**
 * Consumes a MissionEventSource in order, accumulating events as they
 * arrive. Doesn't care whether the source is fixture playback or a real
 * stream - it only ever sees MissionEvent, one at a time, in sequence.
 */
export function useMissionEvents(source: MissionEventSource): MissionConsumerState {
  const [state, setState] = useState<MissionConsumerState>({
    events: [],
    status: "streaming",
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    setState({ events: [], status: "streaming", error: null });

    (async () => {
      try {
        for await (const event of source()) {
          if (cancelled) return;
          setState((prev) => ({ ...prev, events: [...prev.events, event] }));
        }
        if (!cancelled) {
          setState((prev) => ({ ...prev, status: "complete" }));
        }
      } catch (err) {
        if (!cancelled) {
          setState((prev) => ({
            ...prev,
            status: "error",
            error: err instanceof Error ? err.message : String(err),
          }));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [source]);

  return state;
}
