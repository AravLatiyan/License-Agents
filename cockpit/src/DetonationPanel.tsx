import type { DetonationForm, DetonationResult, MissionEvent, RedirectHop } from "../../contracts/events";

/**
 * T-053: the detonation panel - redirect chain, then the screenshot of the
 * fake portal (§17, 0:45-1:25). The screenshot half has no real data source
 * yet: `screenshot_id` is a documented stretch goal (contracts/events.ts)
 * that `harness/detonate.js` never sets, and no image-serving mechanism
 * (endpoint, static path convention) has been decided anywhere in PLAN.md.
 * Rendered as an honest "not available" state instead of guessing at an
 * API that doesn't exist (CLAUDE.md: "don't guess API behavior") - the
 * moment `screenshot_id` does start arriving, only the one branch below
 * needs to change, everything else already renders it.
 */
export function DetonationPanel({ events }: { events: MissionEvent[] }) {
  // findLast, not find: a retried/re-emitted detonation is a later, more
  // current result, not a duplicate to ignore - the panel must track the
  // stream's current state the same way gate/lane state does everywhere
  // else in this app, not freeze on whichever result happened first
  // (Qodo, PR #41 finding #1).
  const event = events.findLast(
    (e): e is Extract<MissionEvent, { type: "mission.detonation" }> => e.type === "mission.detonation",
  );

  return (
    <section className="detonation-panel" aria-label="Detonation">
      <h2>Detonation</h2>
      {!event ? (
        <p className="detonation-panel__empty">Waiting…</p>
      ) : "error" in event.detonation ? (
        <DetonationError detonation={event.detonation} />
      ) : (
        <DetonationSuccess detonation={event.detonation} />
      )}
    </section>
  );
}

function DetonationError({ detonation }: { detonation: Extract<DetonationResult, { error: string }> }) {
  return (
    <div className="detonation-result detonation-result--error">
      <p className="detonation-result__url">{detonation.url}</p>
      <p className="detonation-result__error">Detonation failed: {detonation.error}</p>
    </div>
  );
}

function DetonationSuccess({ detonation }: { detonation: Extract<DetonationResult, { summary: string }> }) {
  return (
    <div className="detonation-result">
      <RedirectChain chain={detonation.redirect_chain} finalUrl={detonation.final_url} />
      <Forms forms={detonation.forms} />
      <Screenshot screenshotId={detonation.screenshot_id} />
      <p className="detonation-result__summary">{detonation.summary}</p>
    </div>
  );
}

function RedirectChain({ chain, finalUrl }: { chain: RedirectHop[]; finalUrl: string }) {
  return (
    <ol className="redirect-chain">
      {chain.map((hop, i) => (
        <li key={i} className="redirect-chain__hop">
          <span className="redirect-chain__status">{hop.status}</span>
          <span className="redirect-chain__url">{hop.url}</span>
        </li>
      ))}
      <li className="redirect-chain__hop redirect-chain__hop--final">
        <span className="redirect-chain__status">→</span>
        <span className="redirect-chain__url">{finalUrl}</span>
      </li>
    </ol>
  );
}

function Forms({ forms }: { forms: DetonationForm[] }) {
  if (forms.length === 0) {
    return <p className="detonation-forms__empty">No forms found on the final page.</p>;
  }
  return (
    <ul className="detonation-forms">
      {forms.map((form, i) => (
        <FormItem key={i} form={form} />
      ))}
    </ul>
  );
}

function FormItem({ form }: { form: DetonationForm }) {
  // The exact "smoking gun" §17 calls out: a form that asks for a password
  // and posts it to a different origin than the page it's on.
  const isDangerous = form.asks_password && form.cross_domain === true;
  return (
    <li className={`detonation-form${isDangerous ? " detonation-form--dangerous" : ""}`}>
      <p className="detonation-form__action">{form.method} → {form.action}</p>
      {form.action_invalid ? (
        <p className="detonation-form__note">Form action could not be resolved to an origin.</p>
      ) : (
        <p className="detonation-form__note">
          {form.cross_domain ? "Posts to a different domain" : "Posts to the same domain"}
          {form.asks_password && " · asks for a password"}
        </p>
      )}
      {isDangerous && <p className="detonation-form__warning">Asks for a password, posts elsewhere</p>}
    </li>
  );
}

function Screenshot({ screenshotId }: { screenshotId: string | undefined }) {
  return (
    <div className="detonation-screenshot">
      {screenshotId ? (
        // No image-serving mechanism exists yet (see file header) - shown as
        // an identifier, not a guessed <img src>, until one is decided.
        <p className="detonation-screenshot__id">Screenshot captured: {screenshotId}</p>
      ) : (
        <p className="detonation-screenshot__empty">No screenshot — text-mode detonation (T-001/T-035, §5).</p>
      )}
    </div>
  );
}
