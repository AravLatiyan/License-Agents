# T-015 approval-gate verification (throwaway)

Reproduces, from committed files, the manual steps that proved the approval
gate is wired end to end (PLAN.md §4, 2026-08-25): register the stub MCP
connector, confirm TrueForge discovered `quarantine_stub`, create a test agent
with `require_approval_for_tools: ["quarantine_stub"]`.

**Never touches `harness/agent.json`.** The gated connector only exists in
`test-agent.json` here, never the product manifest.

## Run

```bash
node harness/stub-mcp-server.js &        # starts the stub on :8901
npx @truefoundry/trueforge &             # starts TrueForge on :8790
bash harness/test/approval-gate-verification/verify-approval-gate.sh
```

Success looks like: step 1 and 3 return non-error HTTP responses, step 2's
output includes `quarantine_stub`. A 422 on step 3 for "model provider not
configured" is expected on a fresh TrueForge instance — that's the separate
live-fire blocker (PLAN.md §5), not a gate-wiring failure.

## Cleanup

The script prints exact cleanup instructions at the end. Short version: this
TrueForge instance's OpenAPI schema has no confirmed DELETE endpoint for
agents or mcp-servers, so stop the local `npx @truefoundry/trueforge` process
— its state doesn't persist across restarts. Don't skip this on a shared
instance; confirm a delete endpoint first instead.
