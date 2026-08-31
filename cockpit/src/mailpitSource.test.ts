// Tests for cockpit/src/mailpitSource.ts.
//
// Written for Qodo's PR #100 findings #1 and #2, both of which were invisible
// to the suite because this module had no test file at all:
//
//   #2 "Inbox truncates after fifty" - one unparameterised GET returns
//      Mailpit's default first page, not the mailbox. Client-side search and
//      tag filtering run over this array, so anything past the first page
//      could not be found.
//   #1 "Wrong message marked investigated" - the inbox row carried no stable
//      identifier, so App.tsx matched a mission to a message by sender
//      address alone. MessageSummary.MessageID is what makes identity
//      provable; these tests pin that it survives parsing.
//
// No network: `fetchImpl` is injected, exactly as the production signature
// already allows.

import { test } from "node:test";
import assert from "node:assert/strict";

import { fetchMailpitInbox } from "./mailpitSource.ts";

/** One Mailpit MessageSummary row, shaped as its own vendored spec defines
 *  it (range/mailpit-api.json). */
function row(n: number, overrides: Record<string, unknown> = {}) {
  return {
    ID: `row-${n}`,
    MessageID: `msg-${n}@mailpit`,
    From: { Name: `Sender ${n}`, Address: `sender${n}@example.test` },
    Subject: `Subject ${n}`,
    Created: "2026-08-30T16:42:01.087Z",
    Snippet: `snippet ${n}`,
    Tags: [],
    Read: false,
    ...overrides,
  };
}

/** A fetch stub that serves `total` rows in Mailpit's own paged shape and
 *  records every URL it was asked for. */
function pagedFetch(total: number, pageSize = 200) {
  const urls: string[] = [];
  const impl = (async (input: string | URL) => {
    const url = String(input);
    urls.push(url);
    const start = Number(new URL(url, "http://x").searchParams.get("start") ?? 0);
    const limit = Number(new URL(url, "http://x").searchParams.get("limit") ?? pageSize);
    const messages = [];
    for (let i = start; i < Math.min(start + limit, total); i++) messages.push(row(i));
    return {
      ok: true,
      json: async () => ({ messages, total, messages_count: total, start, tags: [], unread: 0 }),
    } as unknown as Response;
  }) as unknown as typeof fetch;
  return { impl, urls };
}

test("an inbox larger than one page is returned complete, not truncated", async () => {
  const { impl, urls } = pagedFetch(450);

  const messages = await fetchMailpitInbox("http://mailpit.test", impl);

  assert.equal(messages?.length, 450, "every message must be returned, not just the first page");
  assert.ok(urls.length > 1, "more than one page must have been requested");
  assert.equal(new Set(messages?.map((m) => m.id)).size, 450, "no row may be duplicated across pages");
});

test("pagination requests carry explicit start and limit", async () => {
  const { impl, urls } = pagedFetch(450);

  await fetchMailpitInbox("http://mailpit.test", impl);

  assert.match(urls[0], /[?&]start=0(&|$)/);
  assert.match(urls[0], /[?&]limit=\d+/);
  assert.match(urls[1], /[?&]start=[1-9]\d*(&|$)/, "the second request must move the offset forward");
});

test("a mailbox that fits in one page costs exactly one request", async () => {
  const { impl, urls } = pagedFetch(3);

  const messages = await fetchMailpitInbox("http://mailpit.test", impl);

  assert.equal(messages?.length, 3);
  assert.equal(urls.length, 1, "a short page is the last page - no speculative extra request");
});

test("an empty mailbox is an empty list, not a failure", async () => {
  const { impl } = pagedFetch(0);

  assert.deepEqual(await fetchMailpitInbox("http://mailpit.test", impl), []);
});

test("the RFC Message-ID survives parsing - the only cross-system identifier", async () => {
  const { impl } = pagedFetch(2);

  const messages = await fetchMailpitInbox("http://mailpit.test", impl);

  assert.equal(messages?.[0].messageId, "msg-0@mailpit");
  assert.notEqual(messages?.[0].messageId, messages?.[0].id, "Message-ID and Mailpit's row id are different things");
});

test("a message with no Message-ID reports null rather than inventing one", async () => {
  const impl = (async () => ({
    ok: true,
    json: async () => ({ messages: [row(1, { MessageID: undefined }), row(2, { MessageID: "" })], total: 2 }),
  })) as unknown as typeof fetch;

  const messages = await fetchMailpitInbox("http://mailpit.test", impl);

  assert.equal(messages?.[0].messageId, null, "absent Message-ID must be null - identity unknown");
  assert.equal(messages?.[1].messageId, null, "an empty Message-ID is no identifier either");
});

test("a page that fails partway through returns null, never a partial mailbox", async () => {
  let call = 0;
  const impl = (async () => {
    call++;
    if (call === 1) {
      return {
        ok: true,
        json: async () => ({ messages: Array.from({ length: 200 }, (_, i) => row(i)), total: 400 }),
      } as unknown as Response;
    }
    return { ok: false, json: async () => ({}) } as unknown as Response;
  }) as unknown as typeof fetch;

  assert.equal(
    await fetchMailpitInbox("http://mailpit.test", impl),
    null,
    "half a mailbox presented as the whole mailbox is the bug this guards",
  );
});

test("an unreachable server degrades to null, never throws", async () => {
  const impl = (async () => {
    throw new Error("ECONNREFUSED");
  }) as unknown as typeof fetch;

  assert.equal(await fetchMailpitInbox("http://mailpit.test", impl), null);
});

test("a non-2xx response degrades to null", async () => {
  const impl = (async () => ({ ok: false, json: async () => ({}) })) as unknown as typeof fetch;

  assert.equal(await fetchMailpitInbox("http://mailpit.test", impl), null);
});

test("a body that is not the documented shape degrades to null", async () => {
  const impl = (async () => ({ ok: true, json: async () => ({ notMessages: [] }) })) as unknown as typeof fetch;

  assert.equal(await fetchMailpitInbox("http://mailpit.test", impl), null);
});

test("a server that never reports a short page still terminates", async () => {
  // A `total` larger than anything the server actually delivers must not spin
  // the paging loop forever - it degrades to a truncated inbox instead.
  const impl = (async () => ({
    ok: true,
    json: async () => ({ messages: Array.from({ length: 200 }, (_, i) => row(i)), total: 10_000_000 }),
  })) as unknown as typeof fetch;

  const messages = await fetchMailpitInbox("http://mailpit.test", impl);

  assert.ok(messages !== null);
  assert.ok(messages.length > 0 && messages.length < 10_000_000, "bounded, not unbounded");
});
