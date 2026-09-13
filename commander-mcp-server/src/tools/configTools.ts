import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { getConfig, setAllowedDirectories, addBlockedPattern, getAllowedRoot } from "../security.js";

export function registerConfigTools(server: McpServer): void {
  server.registerTool(
    "config_get",
    {
      title: "Get Server Config",
      description: `View this server's current security configuration: which directories are accessible, which command patterns are blocked, and the default shell.

Returns: { allowedRoot, allowedDirectories, blockedCommandPatterns, defaultShell }.
allowedRoot is a hard ceiling set at server startup (ALLOWED_ROOT env var) and can never be widened at runtime.`,
      inputSchema: {},
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      const cfg = getConfig();
      const output = { allowedRoot: getAllowedRoot(), ...cfg };
      return { content: [{ type: "text", text: JSON.stringify(output, null, 2) }], structuredContent: output };
    }
  );

  server.registerTool(
    "config_set_allowed_directories",
    {
      title: "Set Allowed Directories",
      description: `Narrow (or reset) which directories filesystem/process tools can touch. Every directory must already be inside the hard ALLOWED_ROOT ceiling set at server startup — this tool can restrict access further, never widen it beyond that root.

Args:
  - directories (string[]): Absolute paths, all must resolve inside ALLOWED_ROOT.

Returns: { accepted: string[], rejected: string[] } — rejected entries were outside ALLOWED_ROOT and were ignored.`,
      inputSchema: { directories: z.array(z.string()).min(1).describe("Absolute directory paths") },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ directories }) => {
      const result = setAllowedDirectories(directories);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }], structuredContent: result };
    }
  );

  server.registerTool(
    "config_add_blocked_command_pattern",
    {
      title: "Add Blocked Command Pattern",
      description: `Add a regex pattern to the command blocklist checked by proc_start. Patterns are additive and case-insensitive; there's no tool to remove the built-in defaults, by design.

Args:
  - pattern (string): A valid regular expression (JavaScript syntax) to block.

Returns: { added: true, pattern } or an error if the pattern doesn't compile.`,
      inputSchema: { pattern: z.string().min(1).describe("Regex pattern to add to the blocklist") },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ pattern }) => {
      try {
        addBlockedPattern(pattern);
        return { content: [{ type: "text", text: JSON.stringify({ added: true, pattern }) }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Invalid regex: ${(err as Error).message}` }], isError: true };
      }
    }
  );
}
