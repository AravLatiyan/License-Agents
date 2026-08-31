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

// ---------------------------------------------------------------------------
// Output budget (T-042, 2026-08-30)
//
// Why this file also pins max_tokens now: the manifest shipped with 4096, and
// that is not a loud failure either. The second live evaluation fixture
// (sample-10.eml, 24KB) died with finish_reason "length" on the call where the
// root agent composes its three sub-agent prompts - the turn ended
// `{"status":"error","message":"max_tokens breached"}`, no sub-agent was ever
// created, and no approval gate was reached. Measured, not inferred: the same
// call on the smaller sample-1.eml (15.7KB) completed at 3675 output tokens,
// so the ceiling sat barely above what a normal turn already needs, and a
// thinking model's reasoning counts against it.
// ---------------------------------------------------------------------------

/** Largest single-call output actually observed completing a real turn (sample-1.eml). */
const OBSERVED_PEAK_OUTPUT_TOKENS = 3675;

/** The ceiling that truncated sample-10.eml's sub-agent-spawning call. */
const OBSERVED_TRUNCATION_CEILING = 4096;

/**
 * TrueForge's own catalog for the registered model:
 * GET /api/v1/models -> anthropic/claude-sonnet-5 ->
 *   properties.max_output_tokens = 128000
 */
const MODEL_MAX_OUTPUT_TOKENS = 128000;

test("max_tokens clears the ceiling that truncated a real evaluation turn", () => {
  const maxTokens = manifest.model.params.max_tokens;
  assert.equal(typeof maxTokens, "number");
  assert.ok(
    maxTokens > OBSERVED_TRUNCATION_CEILING,
    `max_tokens ${maxTokens} must exceed the ${OBSERVED_TRUNCATION_CEILING} ceiling that ` +
      "ended a real turn with finish_reason 'length'",
  );
});

test("max_tokens leaves real headroom over the largest observed completing call", () => {
  // 4x the only peak we have actually measured. Two live fixtures is a small
  // sample and the corpus runs to 114KB, so the margin is deliberate - and it
  // costs nothing: max_tokens is a ceiling, not a target. Spend is driven by
  // tokens actually generated.
  assert.ok(
    manifest.model.params.max_tokens >= OBSERVED_PEAK_OUTPUT_TOKENS * 4,
    "max_tokens must keep at least 4x headroom over the observed peak",
  );
});

test("max_tokens stays within what the registered model actually supports", () => {
  assert.ok(
    manifest.model.params.max_tokens <= MODEL_MAX_OUTPUT_TOKENS,
    `max_tokens must not exceed ${MODEL_MAX_OUTPUT_TOKENS}, the max_output_tokens ` +
      "TrueForge's own /api/v1/models catalog advertises for anthropic/claude-sonnet-5",
  );
});

test("the model itself is unchanged - only the output budget moved", () => {
  assert.equal(manifest.model.name, "anthropic/claude-sonnet-5");
  assert.equal(manifest.model.params.temperature, 0.2);
});
