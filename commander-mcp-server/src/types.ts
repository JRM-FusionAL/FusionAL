export interface FileInfo {
  path: string;
  size: number;
  isDirectory: boolean;
  isFile: boolean;
  isSymlink: boolean;
  created: string;
  modified: string;
  accessed: string;
  permissions: string;
}

export interface DirectoryEntry {
  name: string;
  type: "file" | "directory" | "symlink" | "other";
  size?: number;
}

export type SessionStatus = "running" | "completed" | "failed" | "terminated";

export interface ProcessSession {
  pid: number;
  command: string;
  shell: string;
  cwd: string;
  status: SessionStatus;
  startedAt: string;
  endedAt?: string;
  exitCode?: number | null;
  stdoutBuffer: string;
  stderrBuffer: string;
  stdoutOffset: number; // how much of stdoutBuffer has already been delivered
  stderrOffset: number;
  lastActivity: number; // epoch ms, used for TTL cleanup
}

export interface SecurityConfig {
  allowedDirectories: string[];
  blockedCommandPatterns: string[];
  defaultShell: string;
}
