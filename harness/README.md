# harness (Owner 1)

TrueForge config, agent.json, sandbox job, subagents. See root `PLAN.md` for the plan and
`CLAUDE.md` for the rules.

## agent.json

`agent.json` is the full request payload for `POST /api/v1/agents` — top-level `name` plus a
`manifest` object (model, instructions, mcp_servers, config). Schema confirmed against
trueforge.dev docs and runtime-verified against a live server (see below) — the server accepted
it fully, the only rejection was the expected 422 for an unconfigured model provider. To seed it
into a running TrueForge server:

```bash
curl -X POST http://localhost:8790/api/v1/agents \
  -H "Content-Type: application/json" \
  -d @harness/agent.json
```

`mcp_servers` (T-034) points at the `imports-mcp` connector and marks four tools
approval-required:

```json
{
  "name": "imports-mcp",
  "require_approval_for_tools": [
    "quarantine",
    "notify_impersonated",
    "create_block_rule",
    "file_abuse_report"
  ]
}
```

Those four names are the **four sequential licence gates** (§10, §17) — everything else on the
MCP server stays ungated. `name` refers to a connector registered separately in TrueForge
(Settings → Connectors, `POST /api/v1/settings/mcp-servers`); this manifest only references it by
name, it does not carry the URL. Naming the four gates explicitly **replaces** the field's default
of `["@write", "@destructive"]` — that's deliberate: it gates exactly these four and leaves
`parse_message`/`domain_intel`/`url_reputation` ungated regardless of how they're annotated,
matching §10's tool table. `enable_tools` is left at its `["@all"]` default.

**The prompt must not pre-empt the gate.** `instructions` used to end "propose the action and
wait, never assume consent" — correct while `mcp_servers` was empty and prompt-level restraint was
the only safety, but actively wrong now: the harness pauses *on the tool call*, so an agent that
stops to ask in chat first never emits the call and the native gate never fires. Caught by Qodo on
this PR. The wording now tells the model to call the gated tool directly and let the harness stop
it, and adds that a denial is final and must not be routed around via another tool.

**None of the four gated tools exist yet** — they're T-030–T-033 (O2), and
`tools/imports_mcp/server.py` currently serves only `parse_message`, `domain_intel`, and
`url_reputation`. Gating a not-yet-existing tool is schema-valid and was verified live (below),
but the gates cannot actually *fire* until those four tools ship.

**Live-verified for T-034** against a real TrueForge instance (WSL2), with the real
`imports-mcp` server registered as a throwaway connector:
- registration returned `201`, and `GET /api/v1/mcp-servers/{name}/tools` listed exactly
  `parse_message`, `domain_intel`, `url_reputation` — confirming the four gate targets are
  genuinely absent;
- a throwaway agent carrying this exact `require_approval_for_tools` list was **not** rejected for
  naming nonexistent tools — it reached the expected `422 "provider not configured"` (the §5
  live-fire blocker);
- two deliberate controls *were* rejected at `400` with precise schema errors
  (`manifest.mcp_servers[0].require_approval_for_tools[0]` for an empty name,
  `manifest.mcp_servers[0].name` for a missing name), proving manifest validation really does run
  and really would have caught a malformed gate list.

So the configuration is proven accepted; **an actual `tool.approval_required` event has not been
observed** and cannot be until T-030–T-033 exist *and* a model provider is configured (§5).

`instructions` (T-023) **asks** the root agent to delegate to three named subagents — INFRASTRUCTURE
(`domain_intel`, `url_reputation`, `detonate`), IDENTITY (display-name vs. Reply-To/Return-Path and
lookalike-domain checks on fields the parser already extracted), HISTORY (`correspondence_history`)
— matching §10's architecture table. **This is prompt guidance, not enforced configuration.**
`dynamic_sub_agents` has no support for pre-defined named subagents or per-agent tool scopes: per
TrueForge's own docs (`trueforge.dev/key-features/subagents`), the root agent's model decides at
runtime whether and how to delegate, generating its own focused instructions via the built-in
`create_sub_agent` tool — not from this prose — and every spawned subagent receives the **full**
tool set the root has, identical to root, with no restriction mechanism. So "IDENTITY: no tool call"
is a request we're making of the model, not a boundary the platform enforces — nothing stops an
IDENTITY-labeled subagent from calling `domain_intel` if the model chooses to. Likewise "exactly
three subagents" is what we're asking for, not a guarantee of what gets spawned.
**Structured evidence (T-024):** each subagent reports back to the lead as a small JSON object
built from its own tool call's own field names (INFRASTRUCTURE: one object per tool it actually
called — `domain_intel`/`url_reputation`/`detonate`'s own result fields, omitting a key entirely
for a tool it didn't call; IDENTITY: `from_address`/`display_name`/`reply_to`/`return_path`/
`lookalike_domain`/`lookalike_of`, computed from the parsed message, no tool call; HISTORY:
`correspondence_history`'s own result fields, `domain` included) — never prose, and never an
invented schema. "Own remit" is about judgment, not field names: a shared key name across two
tools' own outputs (e.g. `domain_intel` and `correspondence_history` both happen to have a
`domain` field) is never a reason to drop or rename either one — each stays exactly as its own
tool returned it. IDENTITY's shape matches `contracts/events.ts`'s `IdentityEvidence` exactly
(including the required `from_address` Qodo's PR #17 review caught missing from the first draft),
since that type has no separate real producer to diverge from — it's derived straight from parsed-
message fields, same as this prompt. INFRASTRUCTURE reports `domain_intel`/`url_reputation`'s own
result fields verbatim, nested `rdap`/`cert` sections included — `domain_intel.py` also carries flat
top-level `registration_date`/`registrar`/`abuse_contact`/`cert_issued_at` mirrors of those same
values (added in `tools/`'s PR #19 second Qodo-fix pass, commit `3f169b3`) specifically so its real
output satisfies `contracts/events.ts`'s `DomainIntel` shape; `url_reputation.py`'s own fields
already did. The earlier contract-drift note (PLAN.md §8, 2026-08-27) is resolved. The lead, not
the subagents, turns that structured evidence into the final plain-English
verdict. Same enforcement caveat as above: this is prompt guidance the model can diverge from,
not a schema the platform validates.

**Written, not yet runtime-verified** — no local TrueForge instance was running this session, so
none of the above (whether the root actually spawns three subagents matching these names/remits,
whether IDENTITY in practice stays tool-free, or whether reports actually come back as JSON instead
of prose) has been observed. The `instructions` field itself is the same accepted schema as
T-013/T-017 (low risk there); the open question is the model's actual delegation and reporting
*behavior*, not whether the JSON is accepted.

## detonate.js

Text-mode detonation (§14 Slice 1, T-014): follows redirects (capped at 10 hops, refuses
non-http(s) schemes), parses the final HTML with `node-html-parser` (never regex), flags forms
that ask for a password and post to a different origin. `node --test` runs the self-tests
against a local-only fixture server — never a real domain.

**SSRF guard:** the initial URL and every redirect hop are resolved and refused if they land on
loopback, RFC1918, link-local (incl. cloud-metadata `169.254.169.254`), or unspecified addresses
— checked against the *resolved* IP, not just the hostname string, so a domain that resolves to
an internal address is also caught. `allowPrivateNetworkTargets: true` opts back in and exists
only for `detonate.test.js`'s own local fixture server; never set it for a real detonation.

## stub-mcp-server.js — throwaway, not the product

One-tool (`quarantine_stub`) MCP server used only to prove the approval-gate wiring end to end
(T-015) before `tools/imports-mcp` (T-012, owner O2) exists. Exposed over Streamable HTTP
because TrueForge only connects to `type: "remote"` (URL-based) MCP servers — no local/stdio
type in this version. Never reference it from `harness/agent.json`; that file stays pointed at
the real `imports-mcp` server once T-012 lands. The tool response caps `message_id` so the
serialized reply stays under the ~2KB MCP response limit, flagging `truncated: true` if the
caller-supplied id had to be cut — see `stub-mcp-server.test.js`.

**Reproducing the approval-gate proof:** `harness/test/approval-gate-verification/` has a
committed throwaway test-agent payload and script that replay the exact registration →
discovery → gated-agent-creation steps from a clean checkout, plus exact cleanup instructions.
See that directory's README. `harness/agent.json` is never touched by it.

**If running this (or anything under `harness/`) from WSL2:** don't run it against `/mnt/c`
directly — this repo is OneDrive-synced, and WSL's cross-filesystem access to it stalls badly on
anything touching `node_modules` (a plain `import()` hung 8+ seconds with zero output). Copy the
directory to WSL's native filesystem first and run from there. TrueForge itself is unaffected —
its `npx` cache lives in the WSL user profile, not `/mnt/c`.

## Known issue: TrueForge segfaults on native Windows — fixed, run it under WSL2

`npx @truefoundry/trueforge` crashes (`Segmentation fault`) a moment after start on native
Windows, right after logging `Local sandbox fallback is unavailable (win32 not supported)`.
Reproduced twice.

**Fixed:** install Node inside WSL2 Ubuntu itself (not native Windows, and not WSL falling
through to the Windows `node.exe` via interop) and run TrueForge from there. Confirmed working:
the server started clean under WSL2, returned HTTP 200, and `harness/agent.json` was POSTed to
its live `/api/v1/agents` and accepted. See PLAN.md §7/§8 for the full writeup.
