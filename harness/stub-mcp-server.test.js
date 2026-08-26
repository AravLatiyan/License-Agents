import { test } from "node:test";
import assert from "node:assert/strict";
import { buildQuarantineResponse } from "./stub-mcp-server.js";

const MAX_RESPONSE_BYTES = 2000;

test("short message_id round-trips untouched", () => {
  const res = buildQuarantineResponse("msg-123");
  const parsed = JSON.parse(res.content[0].text);
  assert.equal(parsed.message_id, "msg-123");
  assert.equal(parsed.truncated, false);
});

test("oversized message_id is truncated, flagged, and the serialized response stays under the 2KB cap", () => {
  const huge = "a".repeat(10_000);
  const res = buildQuarantineResponse(huge);
  const text = res.content[0].text;

  assert.ok(
    Buffer.byteLength(text, "utf8") <= MAX_RESPONSE_BYTES,
    `response was ${Buffer.byteLength(text, "utf8")} bytes, expected <= ${MAX_RESPONSE_BYTES}`
  );

  const parsed = JSON.parse(text);
  assert.equal(parsed.truncated, true);
  assert.ok(parsed.message_id.length < huge.length);
});
