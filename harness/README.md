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

`mcp_servers` is empty for now — `tools/imports-mcp` (T-012) doesn't exist yet. Once it does,
add an entry here:

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
MCP server stays ungated.

`instructions` (T-023) delegates to three named subagents run in parallel via `dynamic_sub_agents`
(no separate config needed — that's a TrueForge-native mechanism, we only describe the remits in
prose): **INFRASTRUCTURE** (`domain_intel`, `url_reputation`, `detonate`), **IDENTITY** (no tool —
display-name vs. Reply-To/Return-Path and lookalike-domain checks on fields the parser already
extracted), **HISTORY** (`correspondence_history`). Matches §10's architecture table exactly.
Structured (non-prose) evidence output is T-024's job, not this one — each subagent still just
reports back in prose for now. **Written, not yet runtime-verified** — no local TrueForge instance
was running this session to confirm against a live server the way T-013/T-017 did; same schema/field
(`instructions`) already accepted there, so low risk, but flagging it rather than claiming proof we
don't have.

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
