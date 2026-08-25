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

## detonate.js

Text-mode detonation (§14 Slice 1, T-014): follows redirects (capped at 10 hops, refuses
non-http(s) schemes), parses the final HTML with `node-html-parser` (never regex), flags forms
that ask for a password and post to a different origin. `node --test` runs the self-tests
against a local-only fixture server — never a real domain.

## stub-mcp-server.js — throwaway, not the product

One-tool (`quarantine_stub`) MCP server used only to prove the approval-gate wiring end to end
(T-015) before `tools/imports-mcp` (T-012, owner O2) exists. Exposed over Streamable HTTP
because TrueForge only connects to `type: "remote"` (URL-based) MCP servers — no local/stdio
type in this version. Never reference it from `harness/agent.json`; that file stays pointed at
the real `imports-mcp` server once T-012 lands.

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
