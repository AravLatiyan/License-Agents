# harness (Owner 1)

TrueForge config, agent.json, sandbox job, subagents. See root `PLAN.md` for the plan and
`CLAUDE.md` for the rules.

## agent.json

`agent.json` holds the `manifest` body for `POST /api/v1/agents` (confirmed against
trueforge.dev docs — see §8 in PLAN.md for the platform blocker that stopped us
runtime-verifying it yet). To seed it into a running TrueForge server:

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

## Known issue: TrueForge segfaults on native Windows

`npx @truefoundry/trueforge` crashes (`Segmentation fault`) a moment after start on this
Windows machine, right after logging `Local sandbox fallback is unavailable (win32 not
supported)`. Reproduced twice. See PLAN.md §7/§8 for the decision on how we're working around
it (WSL2, needs Node installed inside the distro — not yet done).
