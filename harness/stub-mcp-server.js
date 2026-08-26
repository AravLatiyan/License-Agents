import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";
import http from "node:http";

/**
 * T-015: the smallest possible gated action, so we can prove the approval
 * gate itself is wired end to end without waiting on tools/imports-mcp
 * (T-012, owner O2). Exposed over Streamable HTTP because TrueForge only
 * connects to remote (URL-based) MCP servers — no local/stdio type exists
 * in this version (confirmed against its own OpenAPI schema).
 *
 * Never register this as a product connector — it's throwaway, for wiring
 * verification only. tools/imports-mcp is the real thing.
 */
// Rule 2880706 caps MCP tool responses at ~2KB. message_id is caller-controlled
// and otherwise unbounded, so it's truncated (never the field name/envelope) to
// keep the serialized response under the cap, with a `truncated` flag so a
// caller can tell the id was cut.
const MAX_RESPONSE_BYTES = 2000;

export function buildQuarantineResponse(message_id) {
  const envelopeOverhead = Buffer.byteLength(
    JSON.stringify({ status: "quarantined (stub)", message_id: "", truncated: false }),
    "utf8"
  );
  const idBudget = MAX_RESPONSE_BYTES - envelopeOverhead;

  let id = message_id;
  let truncated = false;
  if (Buffer.byteLength(id, "utf8") > idBudget) {
    id = Buffer.from(id, "utf8").subarray(0, idBudget).toString("utf8");
    truncated = true;
  }

  const text = JSON.stringify({ status: "quarantined (stub)", message_id: id, truncated });
  return { content: [{ type: "text", text }] };
}

function buildServer() {
  const server = new McpServer({ name: "imports-mcp-stub", version: "0.0.1" });

  server.registerTool(
    "quarantine_stub",
    {
      description: "Stub for the quarantine action — does nothing but confirm the approval gate fired.",
      inputSchema: { message_id: z.string() },
    },
    async ({ message_id }) => buildQuarantineResponse(message_id)
  );

  return server;
}

function startHttpServer() {
  const PORT = process.env.PORT ?? 8901;

  const httpServer = http.createServer(async (req, res) => {
    if (req.url !== "/mcp") {
      res.writeHead(404).end();
      return;
    }
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    const server = buildServer();
    res.on("close", () => {
      transport.close();
      server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res);
  });

  httpServer.listen(PORT, "127.0.0.1", () => {
    console.log(`stub MCP server listening on http://127.0.0.1:${PORT}/mcp`);
  });
}

// Only start listening when run directly (`node stub-mcp-server.js`), not when
// imported by the test file — importing must never bind a port as a side effect.
if (import.meta.url === `file://${process.argv[1]}`) {
  startHttpServer();
}
