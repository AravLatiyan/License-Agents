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
function buildServer() {
  const server = new McpServer({ name: "imports-mcp-stub", version: "0.0.1" });

  server.registerTool(
    "quarantine_stub",
    {
      description: "Stub for the quarantine action — does nothing but confirm the approval gate fired.",
      inputSchema: { message_id: z.string() },
    },
    async ({ message_id }) => ({
      content: [{ type: "text", text: JSON.stringify({ status: "quarantined (stub)", message_id }) }],
    })
  );

  return server;
}

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
