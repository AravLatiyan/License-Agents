import type { CorrespondenceHistory, DomainIntel, IdentityEvidence, MissionEvent, UrlReputation } from "../../contracts/events";
import { buildEvidenceLanes, type EvidenceLaneState } from "./missionPlan";

/**
 * T-052: the three subagent lanes side by side, each with its own real
 * evidence fields (not the plan tree's one-line join) - the panel that
 * makes the parallel subagents visible, per §17's 0:20-0:45 demo beat.
 * Reuses buildEvidenceLanes (missionPlan.ts) for lane grouping/status, so
 * this can never disagree with the plan tree about a lane's state.
 */
export function EvidenceLanes({ events }: { events: MissionEvent[] }) {
  const lanes = buildEvidenceLanes(events);
  return (
    <div className="evidence-lanes">
      {lanes.map((lane) => (
        <LaneColumn key={lane.lane} lane={lane} />
      ))}
    </div>
  );
}

function LaneColumn({ lane }: { lane: EvidenceLaneState }) {
  return (
    <section className={`evidence-lane evidence-lane--${lane.status}`} aria-label={`${lane.label} lane`}>
      <header className="evidence-lane__header">
        <span className="sr-only">{lane.status}: </span>
        <h3>{lane.label}</h3>
      </header>
      {lane.items.length === 0 ? (
        <p className="evidence-lane__empty">Waiting…</p>
      ) : (
        <dl className="evidence-lane__items">
          {lane.items.map((item, i) => (
            <EvidenceItem key={i} event={item} />
          ))}
        </dl>
      )}
    </section>
  );
}

function EvidenceItem({ event }: { event: Extract<MissionEvent, { type: "mission.evidence" }> }) {
  switch (event.lane) {
    case "infrastructure":
      return "domain" in event.evidence ? (
        <DomainIntelFields evidence={event.evidence} />
      ) : (
        <UrlReputationFields evidence={event.evidence} />
      );
    case "identity":
      return <IdentityFields evidence={event.evidence} />;
    case "history":
      return <HistoryFields evidence={event.evidence} />;
  }
}

/** One <dt>/<dd> pair, skipped entirely when the value is null - "not
 *  published" (§12) reads as an absent field, not a blank one. */
function Field({ term, value }: { term: string; value: string | number | null }) {
  if (value === null) return null;
  return (
    <>
      <dt>{term}</dt>
      <dd>{value}</dd>
    </>
  );
}

function DomainIntelFields({ evidence }: { evidence: DomainIntel }) {
  return (
    <div className="evidence-item">
      <p className="evidence-item__title">{evidence.domain}</p>
      <Field term="Registered" value={evidence.registration_date} />
      <Field term="Registrar" value={evidence.registrar} />
      <Field term="Cert issued" value={evidence.cert_issued_at} />
      <Field term="Abuse contact" value={evidence.abuse_contact} />
    </div>
  );
}

function UrlReputationFields({ evidence }: { evidence: UrlReputation }) {
  return (
    <div className="evidence-item">
      <p className="evidence-item__title">{evidence.url}</p>
      <Field term="URLhaus" value={evidence.listed ? "Listed" : "Not listed (weak signal only)"} />
      {evidence.tags.length > 0 && <Field term="Tags" value={evidence.tags.join(", ")} />}
    </div>
  );
}

function IdentityFields({ evidence }: { evidence: IdentityEvidence }) {
  return (
    <div className="evidence-item">
      <p className="evidence-item__title">{evidence.display_name ?? evidence.from_address}</p>
      <Field term="From" value={evidence.from_address} />
      <Field term="Reply-To" value={evidence.reply_to} />
      <Field
        term="Lookalike"
        value={evidence.lookalike_domain ? `Yes — of ${evidence.lookalike_of ?? "a known domain"}` : "No"}
      />
    </div>
  );
}

function HistoryFields({ evidence }: { evidence: CorrespondenceHistory }) {
  return (
    <div className="evidence-item">
      <p className="evidence-item__title">{evidence.domain}</p>
      <Field term="Address" value={evidence.address} />
      <Field term="Prior contacts" value={evidence.prior_contact_count} />
      <Field term="First seen" value={evidence.first_seen} />
      <Field term="Last seen" value={evidence.last_seen} />
      {evidence.domains_used.length > 0 && <Field term="Domains used" value={evidence.domains_used.join(", ")} />}
    </div>
  );
}
