import path from "node:path";
import { realpathSync, existsSync } from "node:fs";
import { DEFAULT_SHELL } from "./constants.js";
import type { SecurityConfig } from "./types.js";

/**
 * ALLOWED_ROOT is the hard ceiling. It is set once at process start from
 * an environment variable and can never be widened at runtime, even via
 * the config_set_allowed_directories tool. This is what stands between
 * "filesystem MCP server" and "give the model rm -rf / on my box."
 */
const ALLOWED_ROOT = path.resolve(process.env.ALLOWED_ROOT || "/data");

const DEFAULT_BLOCKED_COMMAND_PATTERNS: string[] = [
  "rm\\s+-rf\\s+/(\\s|$)",
  "rm\\s+-rf\\s+/\\*",
  ":\\(\\)\\s*\\{.*\\|.*&.*\\};?:", // fork bomb
  "mkfs(\\.|\\s)",
  "dd\\s+if=.*of=/dev/(sd|nvme|hd)",
  "\\bshutdown\\b",
  "\\breboot\\b",
  "\\bpoweroff\\b",
  "chmod\\s+-R\\s+000\\s+/",
  "chown\\s+-R\\s+.*\\s+/(\\s|$)",
  ">\\s*/dev/sd[a-z]",
  "curl.*\\|\\s*sh",
  "wget.*\\|\\s*sh",
];

// In-memory, mutable-within-root config. Lets config_set_allowed_directories
// narrow scope further, but never escape ALLOWED_ROOT.
const config: SecurityConfig = {
  allowedDirectories: [ALLOWED_ROOT],
  blockedCommandPatterns: [...DEFAULT_BLOCKED_COMMAND_PATTERNS],
  defaultShell: DEFAULT_SHELL,
};

export function getConfig(): SecurityConfig {
  return {
    allowedDirectories: [...config.allowedDirectories],
    blockedCommandPatterns: [...config.blockedCommandPatterns],
    defaultShell: config.defaultShell,
  };
}

export function getAllowedRoot(): string {
  return ALLOWED_ROOT;
}

/**
 * Narrow (or reset) the working set of allowed directories. Every entry
 * must already resolve inside ALLOWED_ROOT or it's rejected outright.
 */
export function setAllowedDirectories(dirs: string[]): { accepted: string[]; rejected: string[] } {
  const accepted: string[] = [];
  const rejected: string[] = [];
  for (const dir of dirs) {
    const resolved = path.resolve(dir);
    if (isWithinRoot(resolved)) {
      accepted.push(resolved);
    } else {
      rejected.push(dir);
    }
  }
  if (accepted.length > 0) {
    config.allowedDirectories = accepted;
  }
  return { accepted, rejected };
}

function isWithinRoot(resolved: string): boolean {
  const rel = path.relative(ALLOWED_ROOT, resolved);
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

export class PathAccessError extends Error {}

/**
 * Resolves a user-supplied path (relative or absolute) against the
 * allowed directories, following symlinks, and throws PathAccessError
 * if the final real path lands outside every allowed directory.
 * Returns the resolved absolute path — use this, never the raw input,
 * for every fs operation.
 */
export function resolveSafePath(inputPath: string): string {
  const resolved = path.isAbsolute(inputPath)
    ? path.resolve(inputPath)
    : path.resolve(ALLOWED_ROOT, inputPath);

  const withinAllowed = (candidate: string) =>
    config.allowedDirectories.some((dir) => {
      const rel = path.relative(dir, candidate);
      return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
    });

  if (!withinAllowed(resolved)) {
    throw new PathAccessError(
      `Access denied: '${inputPath}' resolves to '${resolved}', which is outside the allowed directories (${config.allowedDirectories.join(", ")}). ` +
        `Use fs_list_directory or config_get to see what's accessible.`
    );
  }

  // Also check the *real* (symlink-resolved) path so a symlink inside an
  // allowed dir can't point outside it. This has to hold even when
  // `resolved` itself doesn't exist yet (e.g. fs_write_file to a new
  // file) — otherwise a symlinked ancestor directory (allowedRoot/foo ->
  // /etc) lets a caller create allowedRoot/foo/new.txt on paper while the
  // OS actually writes to /etc/new.txt, since existsSync(resolved) would
  // be false and this check would silently skip. Walk up to the nearest
  // existing ancestor, resolve *that*, and re-append whatever path
  // components don't exist yet.
  const { real, suffix } = realAncestorPath(resolved);
  const effectiveReal = suffix ? path.join(real, suffix) : real;
  if (!withinAllowed(effectiveReal)) {
    throw new PathAccessError(
      `Access denied: '${inputPath}' resolves through a symlink to '${effectiveReal}', which is outside the allowed directories.`
    );
  }

  return resolved;
}

/**
 * Finds the nearest existing ancestor of `p` (including `p` itself),
 * resolves symlinks on that ancestor only, and returns it along with the
 * trailing path components that don't exist yet (so they can't have been
 * symlinked). Terminates at the filesystem root if nothing on the path
 * exists yet.
 */
function realAncestorPath(p: string): { real: string; suffix: string } {
  let current = p;
  let suffix = "";
  while (!existsSync(current)) {
    const parent = path.dirname(current);
    if (parent === current) {
      // Hit the filesystem root without finding anything real — nothing
      // to resolve, return as-is.
      return { real: current, suffix };
    }
    suffix = suffix ? path.join(path.basename(current), suffix) : path.basename(current);
    current = parent;
  }
  return { real: realpathSync(current), suffix };
}

export class CommandBlockedError extends Error {}

/**
 * Checks a shell command string against the blocked-pattern list.
 * Throws CommandBlockedError with the matched pattern if blocked.
 */
export function assertCommandAllowed(command: string): void {
  for (const pattern of config.blockedCommandPatterns) {
    const re = new RegExp(pattern, "i");
    if (re.test(command)) {
      throw new CommandBlockedError(
        `Command blocked by security policy (matched pattern: ${pattern}). ` +
          `If this is a false positive, adjust blockedCommandPatterns via config, but understand what you're removing first.`
      );
    }
  }
}

export function addBlockedPattern(pattern: string): void {
  // Validate it compiles before storing it.
  new RegExp(pattern);
  if (!config.blockedCommandPatterns.includes(pattern)) {
    config.blockedCommandPatterns.push(pattern);
  }
}
