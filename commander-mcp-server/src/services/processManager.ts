import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { MAX_PROCESS_TIMEOUT_MS, SESSION_TTL_MS } from "../constants.js";
import type { ProcessSession } from "../types.js";

interface ManagedSession extends ProcessSession {
  child: ChildProcessWithoutNullStreams;
}

const sessions = new Map<number, ManagedSession>();

// Periodic sweep of finished sessions past their TTL so memory doesn't grow
// unbounded across a long-lived gateway process.
setInterval(() => {
  const now = Date.now();
  for (const [pid, session] of sessions) {
    if (session.status !== "running" && now - session.lastActivity > SESSION_TTL_MS) {
      sessions.delete(pid);
    }
  }
}, 60_000).unref();

export interface StartProcessArgs {
  command: string;
  cwd: string;
  shell: string;
  timeoutMs: number;
  env?: Record<string, string>;
}

/**
 * Starts a command as a persistent, trackable session (like opening a
 * terminal tab and typing a command into it) rather than a fire-and-forget
 * exec. Returns immediately with whatever output has arrived within a
 * short initial window — callers should poll read_process_output for
 * long-running commands, and can write_process_input for interactive ones.
 */
export function startProcess(args: StartProcessArgs): ProcessSession {
  const { command, cwd, shell, env } = args;
  const timeoutMs = Math.min(args.timeoutMs, MAX_PROCESS_TIMEOUT_MS);

  const child = spawn(shell, ["-c", command], {
    cwd,
    env: { ...process.env, ...env },
    stdio: ["pipe", "pipe", "pipe"],
  });

  const session: ManagedSession = {
    pid: child.pid ?? -1,
    command,
    shell,
    cwd,
    status: "running",
    startedAt: new Date().toISOString(),
    stdoutBuffer: "",
    stderrBuffer: "",
    stdoutOffset: 0,
    stderrOffset: 0,
    lastActivity: Date.now(),
    child,
  };

  child.stdout.on("data", (chunk: Buffer) => {
    session.stdoutBuffer += chunk.toString("utf8");
    session.lastActivity = Date.now();
  });
  child.stderr.on("data", (chunk: Buffer) => {
    session.stderrBuffer += chunk.toString("utf8");
    session.lastActivity = Date.now();
  });
  child.on("exit", (code) => {
    // A timeout or explicit terminateProcess() call may have already set
    // status to "terminated" before this event fires — don't clobber that
    // with "failed" just because the exit code looks non-zero.
    if (session.status !== "terminated") {
      session.status = code === 0 ? "completed" : "failed";
    }
    session.exitCode = code;
    session.endedAt = new Date().toISOString();
    session.lastActivity = Date.now();
  });
  child.on("error", (err) => {
    session.status = "failed";
    session.stderrBuffer += `\n[spawn error] ${err.message}`;
    session.endedAt = new Date().toISOString();
    session.lastActivity = Date.now();
  });

  if (session.pid !== -1) {
    sessions.set(session.pid, session);
  }

  // Hard timeout: force-terminate regardless of what the process is doing.
  const killTimer = setTimeout(() => {
    if (session.status === "running") {
      child.kill("SIGKILL");
      session.status = "terminated";
      session.stderrBuffer += `\n[terminated: exceeded ${timeoutMs}ms timeout]`;
      session.endedAt = new Date().toISOString();
    }
  }, timeoutMs);
  child.on("exit", () => clearTimeout(killTimer));

  return toPublicSession(session);
}

/** Returns new output since the last read, without consuming the buffer entirely. */
export function readProcessOutput(pid: number): {
  session: ProcessSession;
  newStdout: string;
  newStderr: string;
} | null {
  const session = sessions.get(pid);
  if (!session) return null;

  const newStdout = session.stdoutBuffer.slice(session.stdoutOffset);
  const newStderr = session.stderrBuffer.slice(session.stderrOffset);
  session.stdoutOffset = session.stdoutBuffer.length;
  session.stderrOffset = session.stderrBuffer.length;

  return { session: toPublicSession(session), newStdout, newStderr };
}

export function writeProcessInput(pid: number, input: string, appendNewline = true): boolean {
  const session = sessions.get(pid);
  if (!session || session.status !== "running") return false;
  session.child.stdin.write(input + (appendNewline ? "\n" : ""));
  session.lastActivity = Date.now();
  return true;
}

export function terminateProcess(pid: number, signal: NodeJS.Signals = "SIGTERM"): boolean {
  const session = sessions.get(pid);
  if (!session) return false;
  if (session.status === "running") {
    session.child.kill(signal);
    session.status = "terminated";
    session.endedAt = new Date().toISOString();
  }
  return true;
}

export function listSessions(): ProcessSession[] {
  return Array.from(sessions.values()).map(toPublicSession);
}

export function getSession(pid: number): ProcessSession | null {
  const session = sessions.get(pid);
  return session ? toPublicSession(session) : null;
}

function toPublicSession(session: ManagedSession): ProcessSession {
  // Strip the non-serializable `child` handle before handing this back to a tool.
  const { child: _child, ...publicFields } = session;
  return publicFields;
}
