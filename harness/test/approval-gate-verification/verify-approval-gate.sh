#!/usr/bin/env bash
# T-015: reproduces the exact manual steps that proved the approval gate is
# wired end to end (PLAN.md §4). Throwaway verification only — never touches
# harness/agent.json, never runs a real turn. Requires:
#   - TrueForge running locally (`npx @truefoundry/trueforge`, localhost:8790)
#   - the stub MCP server running (`node harness/stub-mcp-server.js`, :8901)
set -euo pipefail

BASE="${TRUEFORGE_URL:-http://localhost:8790}"
STUB_URL="${STUB_MCP_URL:-http://127.0.0.1:8901/mcp}"
MCP_NAME="imports-mcp-stub-verify-$$"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "1. Registering the throwaway MCP connector ($MCP_NAME)..."
curl -sf -X POST "$BASE/settings/mcp-servers" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"$MCP_NAME\", \"type\": \"remote\", \"url\": \"$STUB_URL\"}"
echo

echo "2. Confirming TrueForge discovered quarantine_stub..."
curl -sf "$BASE/mcp-servers/$MCP_NAME/tools" | tee /tmp/t015-mcp-tools.json
grep -q quarantine_stub /tmp/t015-mcp-tools.json || { echo "FAIL: quarantine_stub not discovered"; exit 1; }
echo

echo "3. Creating the throwaway test agent with the gate on quarantine_stub..."
sed "s/__MCP_NAME__/$MCP_NAME/" "$HERE/test-agent.json" > /tmp/t015-agent-payload.json
curl -sf -X POST "$BASE/api/v1/agents" \
  -H "Content-Type: application/json" \
  -d @/tmp/t015-agent-payload.json
echo
echo
echo "Gate wiring confirmed if steps 1-3 above returned success responses and"
echo "step 2 listed quarantine_stub. (A 422 on step 3 for 'model provider not"
echo "configured' is expected and fine — that's the separate live-fire blocker,"
echo "PLAN.md §5, not a gate-wiring failure.)"
echo
echo "CLEANUP — this test agent and connector are throwaway, remove them:"
echo "  This TrueForge OpenAPI schema does not expose a confirmed DELETE"
echo "  endpoint for agents or mcp-servers (checked, see PLAN.md §6). The"
echo "  guaranteed-safe cleanup for a local dev instance is to stop the"
echo "  TrueForge process (Ctrl+C the \`npx @truefoundry/trueforge\` terminal)"
echo "  — its state does not persist across restarts. If your instance is"
echo "  long-running/shared, do NOT skip this: confirm a delete endpoint in"
echo "  its live OpenAPI schema first, rather than leaving $MCP_NAME registered."
