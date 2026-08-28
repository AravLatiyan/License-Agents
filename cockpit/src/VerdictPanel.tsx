import type { MissionEvent, VerdictLabel } from "../../contracts/events";

const VERDICT_TEXT: Record<VerdictLabel, string> = {
  malicious: "Malicious",
  suspicious: "Suspicious",
  legitimate: "Legitimate",
};

/**
 * T-054: the verdict panel - plain English, <=4 sentences, no jargon (§17,
 * 1:25-1:50). The sentence-count/plain-language constraint is on whoever
 * writes `summary` (the harness prompt, T-024's remit) - this panel's job
 * is to render it prominently and clearly, the mission's one moment of
 * plain-language judgment before the licence gates fire.
 */
export function VerdictPanel({ events }: { events: MissionEvent[] }) {
  // findLast, not find: a re-emitted verdict is the current judgment, not
  // a duplicate to ignore - same lesson T-053 already had to learn once
  // for detonation (§7), applied here from the start instead of waiting
  // for a second finding on the same pattern.
  const event = events.findLast(
    (e): e is Extract<MissionEvent, { type: "mission.verdict" }> => e.type === "mission.verdict",
  );

  return (
    <section className="verdict-panel" aria-label="Verdict">
      <h2>Verdict</h2>
      {/* role="status" implies aria-live="polite" + aria-atomic="true" - the
          verdict arrives asynchronously and replaces "Waiting…" in place, so
          without a live region a screen-reader user gets no notification
          that this mission's most critical result just appeared (Qodo,
          PR #43 finding #2). One stable element so the swap fires as a
          single announcement, not a diff of loose text nodes. */}
      <div role="status">
        {!event ? (
          <p className="verdict-panel__empty">Waiting…</p>
        ) : (
          <div className={`verdict verdict--${event.verdict}`}>
            <p className="verdict__label">{VERDICT_TEXT[event.verdict]}</p>
            <p className="verdict__summary">{event.summary}</p>
          </div>
        )}
      </div>
    </section>
  );
}
