import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express from "express";
import type { Request, Response, NextFunction } from "express";
import { timingSafeEqual } from "node:crypto";
import { registerFilesystemTools } from "./tools/filesystem.js";
import { registerProcessTools } from "./tools/process.js";
import { registerConfigTools } from "./tools/configTools.js";
import { getAllowedRoot } from "./security.js";

/**
 * This server hands out filesystem read/write and arbitrary shell command
 * execution (proc_start) within ALLOWED_ROOT to anyone who can reach
 * /mcp. There is no other gate in front of it in HTTP mode — fail closed
 * if COMMANDER_API_KEY isn't set, same posture as FusionAL's own
 * MCP_EXTERNAL_API_KEY (see core/main.py MCPExternalApiKeyMiddleware).
 */
function requireApiKey(req: Request, res: Response, next: NextFunction): void {
  const expected = process.env.COMMANDER_API_KEY;
  if (!expected) {
    res.status(503).json({ detail: "Server misconfigured: COMMANDER_API_KEY is not set. Refusing all requests." });
    return;
  }
  const provided = req.header("x-api-key") || "";
  const expectedBuf = Buffer.from(expected, "utf8");
  const providedBuf = Buffer.from(provided, "utf8");
  const match = expectedBuf.length === providedBuf.length && timingSafeEqual(expectedBuf, providedBuf);
  if (!match) {
    res.status(401).json({ detail: "Invalid or missing X-API-Key." });
    return;
  }
  next();
}

function buildServer(): McpServer {
  const server = new McpServer({
    name: "commander-mcp-server",
    version: "1.0.0",
  });

  registerFilesystemTools(server);
  registerProcessTools(server);
  registerConfigTools(server);

  return server;
}

async function runStdio(): Promise<void> {
  const server = buildServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`commander-mcp-server running on stdio (root: ${getAllowedRoot()})`);
}

async function runHTTP(): Promise<void> {
  const app = express();
  app.use(express.json({ limit: "10mb" }));

  app.get("/health", (_req, res) => {
    res.json({ status: "ok", server: "commander-mcp-server", allowedRoot: getAllowedRoot() });
  });

  app.post("/mcp", requireApiKey, async (req, res) => {
    // New server + transport per request: stateless, avoids request-id
    // collisions across concurrent callers hitting the gateway.
    const server = buildServer();
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
    });
    res.on("close", () => {
      transport.close();
      server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  });

  // 8107 is already FusionAL-Recall in your compose.yaml — defaulting to
  // 8108 (next open slot after gateway/bi/api/content/intel/github/recall).
  const port = parseInt(process.env.PORT || "8108", 10);
  // Bind to loopback unless explicitly told otherwise — this server
  // grants filesystem write and shell exec within ALLOWED_ROOT, so
  // exposing it beyond localhost must be an opt-in, not a default.
  const host = process.env.HOST || "127.0.0.1";
  if (!process.env.COMMANDER_API_KEY) {
    console.error("FATAL: COMMANDER_API_KEY is not set. Refusing to start in HTTP mode without it.");
    process.exit(1);
  }
  app.listen(port, host, () => {
    console.error(`commander-mcp-server running on http://${host}:${port}/mcp (root: ${getAllowedRoot()})`);
  });
}

const transportMode = process.env.TRANSPORT || "stdio";
if (transportMode === "http") {
  runHTTP().catch((err) => {
    console.error("Fatal server error:", err);
    process.exit(1);
  });
} else {
  runStdio().catch((err) => {
    console.error("Fatal server error:", err);
    process.exit(1);
  });
}
