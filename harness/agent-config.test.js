// Deterministic checks on agent.json's approval-gate configuration (T-034).
// No network, no TrueForge, no MCP server — this only asserts what the
// committed manifest says.
//
// Why this file exists: a typo in a gate name does not fail loudly. TrueForge
// accepts require_approval_for_tools entries for tools that do not exist
// (verified live, see README) — so "quarentine" would be schema-valid, silently
// ungate the real `quarantine` tool, and let an irreversible action run with no
// human in the loop. That is exactly the failure this project cannot ship
// (CLAUDE.md: the judge must see the harness stop for a person), and it is
// invisible until a live run. Hence: pin the names.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const manifest = JSON.parse(
  readFileSync(new URL("./agent.json", import.meta.url), "utf8")
).manifest;

/** §10 architecture table / §17 demo — the four sequential licence gates, in order. */
const GATES = ["quarantine", "notify_impersonated", "create_block_rule", "file_abuse_report"];

/** Read-only tools that must never be gated — gating these would stall the evidence phase. */
const UNGATED = ["parse_message", "domain_intel", "url_reputation", "correspondence_history", "detonate"];

test("agent.json declares exactly one MCP server, the imports-mcp connector", () => {
  assert.ok(Array.isArray(manifest.mcp_servers), "mcp_servers must be an array");
  assert.equal(manifest.mcp_servers.length, 1);
  assert.equal(manifest.mcp_servers[0].name, "imports-mcp");
});

test("the four licence gates are named exactly, and in §10's order", () => {
  assert.deepEqual(manifest.mcp_servers[0].require_approval_for_tools, GATES);
});

test("no read-only tool is marked approval-required", () => {
  const gated = manifest.mcp_servers[0].require_approval_for_tools;
  for (const tool of UNGATED) {
    assert.ok(!gated.includes(tool), `${tool} is read-only and must not be gated`);
  }
});

test("gate names are non-empty strings — an empty entry is rejected by TrueForge (400)", () => {
  for (const gate of manifest.mcp_servers[0].require_approval_for_tools) {
    assert.equal(typeof gate, "string");
    assert.ok(gate.length > 0);
  }
});

test("no selector shorthand is used — the gates are literal tool names", () => {
  // "@all"/"@write"/"@destructive" are valid selectors, but they would make the
  // gate set depend on how each tool happens to be annotated. Four named gates
  // is what §10/§17 promise, so keep it explicit rather than inferred.
  for (const gate of manifest.mcp_servers[0].require_approval_for_tools) {
    assert.ok(!gate.startsWith("@"), `${gate} is a selector, not a literal tool name`);
  }
});
