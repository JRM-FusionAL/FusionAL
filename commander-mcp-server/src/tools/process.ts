import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { exec } from "node:child_process";
import { promisify } from "node:util";
import {
  startProcess,
  readProcessOutput,
  writeProcessInput,
  terminateProcess,
  listSessions,
  getSession,
} from "../services/processManager.js";
import { resolveSafePath, assertCommandAllowed, CommandBlockedError, getConfig } from "../security.js";
import { CHARACTER_LIMIT, MAX_PROCESS_TIMEOUT_MS } from "../constants.js";

const execAsync = promisify(exec);

function truncate(text: string, limit = CHARACTER_LIMIT): string {
  if (text.length <= limit) return text;
  return text.slice(0, limit) + `\n\n[...truncated: ${text.length - limit} more characters.]`;
}

export function registerProcessTools(server: McpServer): void {
  server.registerTool(
    "proc_start",
    {
      title: "Start Process",
      description: `Start a shell command as a persistent, trackable session — like opening a terminal and typing a command, not a one-shot exec. Use this for anything that might be long-running, interactive (REPLs, installers), or produce streaming output.

For quick one-off commands where you just want the final result, this still works: pass a short timeout and read the returned output directly.

Args:
  - command (string): The shell command to run.
  - cwd (string, optional): Working directory (must be inside allowed directories; default is the allowed root).
  - timeout_ms (number, optional): How long to wait for initial output before returning (default 5000, hard max ${MAX_PROCESS_TIMEOUT_MS}ms total lifetime).
  - shell (string, optional): Shell to use (default from config).

Returns: { pid, status, command, cwd, stdout, stderr } — pid is the session handle for proc_read_output / proc_write_input / proc_terminate.

Error Handling:
  - "Command blocked by security policy" for anything matching a dangerous pattern (rm -rf /, fork bombs, disk-wiping dd, etc.) — see config_get for the current blocklist.
  - "Access denied" if cwd is outside the allowed directories.
  - If status is still "running" when this returns, the command is still going — poll with proc_read_output using the returned pid.`,
      inputSchema: {
        command: z.string().min(1).describe("Shell command to execute"),
        cwd: z.string().optional().describe("Working directory"),
        timeout_ms: z.number().int().min(100).max(MAX_PROCESS_TIMEOUT_MS).default(5000).describe("Initial wait for output, ms"),
        shell: z.string().optional().describe("Shell binary to use"),
      },
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: true },
    },
    async ({ command, cwd, timeout_ms, shell }) => {
      try {
        assertCommandAllowed(command);
        const cfg = getConfig();
        const resolvedCwd = cwd ? resolveSafePath(cwd) : cfg.allowedDirectories[0];
        // timeout_ms controls how long THIS CALL waits before returning —
        // it is NOT the process's kill timer. Interactive/long-running
        // sessions (proc_write_input, polling proc_read_output) need the
        // process to stay alive well past a short initial wait, so the
        // process itself gets the full MAX_PROCESS_TIMEOUT_MS budget and
        // is only cut off early if it exits naturally or is proc_terminate'd.
        const session = startProcess({
          command,
          cwd: resolvedCwd,
          shell: shell || cfg.defaultShell,
          timeoutMs: MAX_PROCESS_TIMEOUT_MS,
        });

        // Give the process `timeout_ms` to produce initial output before we
        // hand control back, so short commands feel synchronous.
        await new Promise((r) => setTimeout(r, Math.min(timeout_ms, 5000)));
        const out = readProcessOutput(session.pid);

        const output = {
          pid: session.pid,
          status: out?.session.status ?? session.status,
          command,
          cwd: resolvedCwd,
          stdout: truncate(out?.newStdout ?? ""),
          stderr: truncate(out?.newStderr ?? ""),
          note:
            (out?.session.status ?? session.status) === "running"
              ? "Process is still running. Use proc_read_output with this pid to get more output, or proc_terminate to stop it."
              : `Process finished with exit code ${out?.session.exitCode ?? "unknown"}.`,
        };
        return { content: [{ type: "text", text: JSON.stringify(output, null, 2) }], structuredContent: output };
      } catch (err) {
        const msg = err instanceof CommandBlockedError || (err as Error)?.name === "PathAccessError" ? (err as Error).message : `Error: ${(err as Error).message}`;
        return { content: [{ type: "text", text: msg }], isError: true };
      }
    }
  );

  server.registerTool(
    "proc_read_output",
    {
      title: "Read Process Output",
      description: `Poll a running or finished proc_start session for new output since the last read.

Args:
  - pid (number): Session pid returned by proc_start.

Returns: { pid, status, exitCode, stdout, stderr } — stdout/stderr contain only *new* output since the last read_process_output or start_process call on this pid.

Error Handling:
  - "Session not found" if the pid is unknown or has been garbage-collected (sessions expire 30 minutes after completion).`,
      inputSchema: { pid: z.number().int().describe("Process session pid from proc_start") },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ pid }) => {
      const result = readProcessOutput(pid);
      if (!result) {
        return { content: [{ type: "text", text: `Session not found for pid ${pid}. It may have expired (sessions are kept 30 minutes after completion) or never existed.` }], isError: true };
      }
      const output = {
        pid,
        status: result.session.status,
        exitCode: result.session.exitCode ?? null,
        stdout: truncate(result.newStdout),
        stderr: truncate(result.newStderr),
      };
      return { content: [{ type: "text", text: JSON.stringify(output, null, 2) }], structuredContent: output };
    }
  );

  server.registerTool(
    "proc_write_input",
    {
      title: "Write to Process stdin",
      description: `Send input to a running process's stdin — for interactive programs (REPLs, prompts like "y/n", installers waiting for input).

Args:
  - pid (number): Session pid from proc_start.
  - input (string): Text to send.
  - append_newline (boolean, optional): Whether to append \\n after input, i.e. press Enter (default true).

Returns: { sent: true } on success. Follow up with proc_read_output to see the process's response.

Error Handling:
  - Returns sent: false if the process isn't running (already exited, or unknown pid).`,
      inputSchema: {
        pid: z.number().int().describe("Process session pid"),
        input: z.string().describe("Text to write to stdin"),
        append_newline: z.boolean().default(true).describe("Append newline (press Enter) after input"),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ pid, input, append_newline }) => {
      const sent = writeProcessInput(pid, input, append_newline);
      return { content: [{ type: "text", text: JSON.stringify({ sent }) }], structuredContent: { sent } };
    }
  );

  server.registerTool(
    "proc_list_sessions",
    {
      title: "List Process Sessions",
      description: `List all proc_start sessions tracked by this server (running, completed, failed, or terminated — completed ones are kept for 30 minutes).

Returns: JSON array of session summaries: { pid, command, status, cwd, startedAt, endedAt?, exitCode? }.`,
      inputSchema: {},
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      const sessions = listSessions().map((s) => ({
        pid: s.pid,
        command: s.command,
        status: s.status,
        cwd: s.cwd,
        startedAt: s.startedAt,
        endedAt: s.endedAt,
        exitCode: s.exitCode,
      }));
      return { content: [{ type: "text", text: truncate(JSON.stringify(sessions, null, 2)) }], structuredContent: { sessions } };
    }
  );

  server.registerTool(
    "proc_terminate",
    {
      title: "Terminate Process Session",
      description: `Force-stop a proc_start session by pid.

Args:
  - pid (number): Session pid.
  - force (boolean, optional): Use SIGKILL instead of SIGTERM (default false — tries graceful shutdown first).

Returns: { terminated: true/false }.`,
      inputSchema: {
        pid: z.number().int().describe("Process session pid"),
        force: z.boolean().default(false).describe("SIGKILL instead of SIGTERM"),
      },
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ pid, force }) => {
      const terminated = terminateProcess(pid, force ? "SIGKILL" : "SIGTERM");
      return { content: [{ type: "text", text: JSON.stringify({ terminated }) }], structuredContent: { terminated } };
    }
  );

  server.registerTool(
    "proc_get_session",
    {
      title: "Get Process Session Detail",
      description: `Get full detail (including complete buffered stdout/stderr, not just new output) for one proc_start session.

Args:
  - pid (number): Session pid.

Returns: Full session object, or an error if not found.`,
      inputSchema: { pid: z.number().int() },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ pid }) => {
      const session = getSession(pid);
      if (!session) {
        return { content: [{ type: "text", text: `Session not found for pid ${pid}.` }], isError: true };
      }
      const output = { ...session, stdoutBuffer: truncate(session.stdoutBuffer), stderrBuffer: truncate(session.stderrBuffer) };
      return { content: [{ type: "text", text: JSON.stringify(output, null, 2) }], structuredContent: output as unknown as Record<string, unknown> };
    }
  );

  server.registerTool(
    "proc_list_system",
    {
      title: "List System Processes",
      description: `List OS-level processes on the host (via 'ps'), independent of what this MCP server itself has started. Useful for checking what's eating CPU/memory or finding a stray process to kill.

Returns: Raw 'ps aux' style text output, truncated if very large.`,
      inputSchema: {},
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const { stdout } = await execAsync("ps aux", { timeout: 5000, maxBuffer: 5_000_000 });
        return { content: [{ type: "text", text: truncate(stdout) }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error running ps: ${(err as Error).message}` }], isError: true };
      }
    }
  );

  server.registerTool(
    "proc_kill_system",
    {
      title: "Kill System Process",
      description: `Send a signal to an OS-level process by PID (not limited to sessions started by proc_start). Use with care — this can kill anything the container/host user has permission to kill.

Args:
  - pid (number): OS process ID.
  - signal (string, optional): Signal name, e.g. "SIGTERM" or "SIGKILL" (default "SIGTERM").

Returns: { killed: true } on success, or an error if the process doesn't exist or permission is denied.`,
      inputSchema: {
        pid: z.number().int().describe("OS process ID to signal"),
        signal: z.string().default("SIGTERM").describe("Signal to send"),
      },
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ pid, signal }) => {
      try {
        process.kill(pid, signal as NodeJS.Signals);
        return { content: [{ type: "text", text: JSON.stringify({ killed: true, pid, signal }) }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${(err as Error).message}` }], isError: true };
      }
    }
  );
}
