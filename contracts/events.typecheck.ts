// contracts/events.typecheck.ts
//
// Dev-only compile-time proof for Qodo finding #4 (T-016 remediation): lane
// and evidence type must be paired, not two independent unions. Not imported
// by app code. Run as part of any contract validation:
//   npx -p typescript tsc --noEmit --strict contracts/events.ts contracts/events.typecheck.ts

import type { EvidenceEvent, DomainIntel } from "./events";

const domainIntel: DomainIntel = {
  domain: "example.com",
  registration_date: null,
  registrar: null,
  abuse_contact: null,
  cert_issued_at: null,
};

// Valid: infrastructure lane accepts DomainIntel.
const validPairing: EvidenceEvent = {
  type: "mission.evidence",
  mission_id: "m",
  lane: "infrastructure",
  evidence: domainIntel,
};

// Invalid: history lane must only accept CorrespondenceHistory. If this line
// stops erroring, the lane/evidence narrowing has regressed.
// @ts-expect-error - history lane cannot accept DomainIntel evidence
const invalidPairing: EvidenceEvent = {
  type: "mission.evidence",
  mission_id: "m",
  lane: "history",
  evidence: domainIntel,
};

void validPairing;
void invalidPairing;
