import { useEffect, useState } from "react";
import type { MissionEvent } from "../../contracts/events";

/**
 * T-043: the demo's closing beat (§17, 2:40-3:00) - "A phone. Plain
 * English, spoken." `mission.complete`'s `spoken_verdict` field is already
 * exactly this text (contracts/events.ts's own comment names T-043) - this
 * panel's only job is to speak it on demand via the Web Speech API and
 * show the text alongside, not to write it.
 *
 * Deliberately a manual "Speak it" button, not autoplay: firing speech
 * synthesis the moment the event arrives would talk over whatever the
 * presenter is saying at that exact second in a live demo, and autoplay
 * policies in some browsers block unprompted audio anyway - a user
 * gesture is the reliable path either way.
 */
export function SpokenVerdict({ events }: { events: MissionEvent[] }) {
  // findLast: same "current, not first" reasoning as every other panel's
  // event lookup here (§7) - a re-emitted mission.complete would otherwise
  // leave this stuck speaking a stale verdict.
  const event = events.findLast(
    (e): e is Extract<MissionEvent, { type: "mission.complete" }> => e.type === "mission.complete",
  );
  const [speaking, setSpeaking] = useState(false);
  const synth = getSpeechSynthesis();

  // Cancel any in-flight utterance if the text changes out from under it or
  // the component unmounts - never leave a stale utterance talking over a
  // newer verdict.
  useEffect(() => {
    return () => {
      synth?.cancel();
    };
  }, [event?.spoken_verdict, synth]);

  function speak() {
    if (!synth || !event) return;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(event.spoken_verdict);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    synth.speak(utterance);
  }

  return (
    <section className="spoken-verdict" aria-label="Spoken verdict">
      <h2>Spoken verdict</h2>
      <div role="status">
        {!event ? (
          <p className="spoken-verdict__empty">Waiting…</p>
        ) : (
          <>
            <p className="spoken-verdict__text">{event.spoken_verdict}</p>
            {synth ? (
              <button type="button" onClick={speak} disabled={speaking}>
                {speaking ? "Speaking…" : "Speak it"}
              </button>
            ) : (
              <p className="spoken-verdict__unsupported">
                Speech synthesis isn't available in this browser — text shown above instead.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function getSpeechSynthesis(): SpeechSynthesis | null {
  // Guards both non-browser rendering (e.g. this file's own
  // renderToStaticMarkup verification, which runs in Node) and a real
  // browser that simply doesn't implement the Web Speech API.
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  return window.speechSynthesis;
}
