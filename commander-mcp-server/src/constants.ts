// Character budget for any single tool response before we truncate.
// Keeps large directory listings / file reads / process output from
// blowing up the calling agent's context window.
export const CHARACTER_LIMIT = 30_000;

// Default shell used for start_process when the caller doesn't specify one.
export const DEFAULT_SHELL = process.env.DEFAULT_SHELL || "/bin/bash";

// Hard ceiling on how long a spawned process is allowed to run before
// it's force-terminated, regardless of what the caller asks for.
export const MAX_PROCESS_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes

// How long a completed/idle process session is kept around (for late
// read_process_output calls) before it's garbage-collected.
export const SESSION_TTL_MS = 30 * 60 * 1000; // 30 minutes
