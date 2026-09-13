import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import fs from "node:fs/promises";
import path from "node:path";
import { resolveSafePath, PathAccessError } from "../security.js";
import { CHARACTER_LIMIT } from "../constants.js";
import type { DirectoryEntry, FileInfo } from "../types.js";

function truncate(text: string, limit = CHARACTER_LIMIT): string {
  if (text.length <= limit) return text;
  return (
    text.slice(0, limit) +
    `\n\n[...truncated: ${text.length - limit} more characters. Narrow your request (offset/length, a more specific path, or a tighter search pattern) to see more.]`
  );
}

function errText(err: unknown): string {
  if (err instanceof PathAccessError) return err.message;
  if (err instanceof Error) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === "ENOENT") return `Error: path does not exist.`;
    if (code === "EACCES") return `Error: permission denied at the OS level.`;
    if (code === "ENOTDIR") return `Error: a component of the path is not a directory.`;
    return `Error: ${err.message}`;
  }
  return `Error: ${String(err)}`;
}

async function statToFileInfo(absPath: string): Promise<FileInfo> {
  const st = await fs.lstat(absPath);
  return {
    path: absPath,
    size: st.size,
    isDirectory: st.isDirectory(),
    isFile: st.isFile(),
    isSymlink: st.isSymbolicLink(),
    created: st.birthtime.toISOString(),
    modified: st.mtime.toISOString(),
    accessed: st.atime.toISOString(),
    permissions: (st.mode & 0o777).toString(8),
  };
}

async function walk(
  root: string,
  opts: { maxDepth: number; maxEntries: number },
  visit: (absPath: string, depth: number) => Promise<boolean /* continue */>,
  depth = 0,
  counter = { n: 0 }
): Promise<void> {
  if (depth > opts.maxDepth || counter.n >= opts.maxEntries) return;
  let entries: import("node:fs").Dirent[];
  try {
    entries = await fs.readdir(root, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (counter.n >= opts.maxEntries) return;
    const abs = path.join(root, entry.name);
    counter.n++;
    const keepGoing = await visit(abs, depth);
    if (!keepGoing) return;
    if (entry.isDirectory() && !entry.isSymbolicLink()) {
      await walk(abs, opts, visit, depth + 1, counter);
    }
  }
}

export function registerFilesystemTools(server: McpServer): void {
  server.registerTool(
    "fs_list_directory",
    {
      title: "List Directory",
      description: `List the contents of a directory (one level deep, non-recursive).

Args:
  - path (string): Directory to list. Relative paths resolve against the allowed root.

Returns: JSON array of { name, type, size? } for each entry, sorted directories-first then alphabetically.

Error Handling:
  - "Access denied" if the path is outside the allowed directories (see config_get).
  - "Error: path does not exist" if not found.
  - Use fs_get_file_info first if unsure whether a path is a file or directory.`,
      inputSchema: { path: z.string().describe("Directory path to list") },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ path: dirPath }) => {
      try {
        const abs = resolveSafePath(dirPath);
        const entries = await fs.readdir(abs, { withFileTypes: true });
        const results: DirectoryEntry[] = await Promise.all(
          entries.map(async (e): Promise<DirectoryEntry> => {
            const type = e.isSymbolicLink() ? "symlink" : e.isDirectory() ? "directory" : e.isFile() ? "file" : "other";
            let size: number | undefined;
            if (type === "file") {
              try {
                size = (await fs.stat(path.join(abs, e.name))).size;
              } catch {
                /* ignore */
              }
            }
            return { name: e.name, type, size };
          })
        );
        results.sort((a, b) => {
          if (a.type === "directory" && b.type !== "directory") return -1;
          if (a.type !== "directory" && b.type === "directory") return 1;
          return a.name.localeCompare(b.name);
        });
        const output = { path: abs, count: results.length, entries: results };
        return { content: [{ type: "text", text: truncate(JSON.stringify(output, null, 2)) }], structuredContent: output };
      } catch (err) {
        return { content: [{ type: "text", text: errText(err) }], isError: true };
      }
    }
  );

  server.registerTool(
    "fs_read_file",
    {
      title: "Read File",
      description: `Read a text file's contents, optionally by line range for large files.

Args:
  - path (string): File to read.
  - offset (number, optional): 0-indexed line number to start from (default 0).
  - length (number, optional): Max number of lines to return (default: all remaining, capped by response size).

Returns: File contents as text, prefixed with total line count when offset/length is used.

Error Handling:
  - "Access denied" if outside allowed directories.
  - "Error: path does not exist" if not found.
  - Binary files are read and returned base64-encoded with a note, rather than corrupted as text.`,
      inputSchema: {
        path: z.string().describe("File path to read"),
        offset: z.number().int().min(0).default(0).describe("0-indexed starting line"),
        length: z.number().int().min(1).max(10000).optional().describe("Max lines to return"),
      },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ path: filePath, offset, length }) => {
      try {
        const abs = resolveSafePath(filePath);
        const buf = await fs.readFile(abs);
        // Cheap binary sniff: presence of a NUL byte in the first 8KB.
        const sample = buf.subarray(0, 8192);
        if (sample.includes(0)) {
          const b64 = buf.toString("base64");
          return {
            content: [
              {
                type: "text",
                text: `[binary file, ${buf.length} bytes, base64-encoded below]\n\n${truncate(b64)}`,
              },
            ],
          };
        }
        const text = buf.toString("utf8");
        const lines = text.split("\n");
        if (offset === 0 && length === undefined) {
          return { content: [{ type: "text", text: truncate(text) }] };
        }
        const end = length !== undefined ? offset + length : lines.length;
        const slice = lines.slice(offset, end).join("\n");
        const header = `[lines ${offset}-${Math.min(end, lines.length) - 1} of ${lines.length} total]\n`;
        return { content: [{ type: "text", text: truncate(header + slice) }] };
      } catch (err) {
        return { content: [{ type: "text", text: errText(err) }], isError: true };
      }
    }
  );

  server.registerTool(
    "fs_read_multiple_files",
    {
      title: "Read Multiple Files",
      description: `Read several small-to-medium text files in one call, to avoid round-trips.

Args:
  - paths (string[]): Files to read (max 20 per call).

Returns: JSON array of { path, content } or { path, error } per file. Each file's content is individually truncated if huge.`,
      inputSchema: { paths: z.array(z.string()).min(1).max(20).describe("List of file paths") },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ paths }) => {
      const results = await Promise.all(
        paths.map(async (p) => {
          try {
            const abs = resolveSafePath(p);
            const content = await fs.readFile(abs, "utf8");
            return { path: p, content: truncate(content, 5000) };
          } catch (err) {
            return { path: p, error: errText(err) };
          }
        })
      );
      return { content: [{ type: "text", text: truncate(JSON.stringify(results, null, 2)) }], structuredContent: { results } };
    }
  );

  server.registerTool(
    "fs_write_file",
    {
      title: "Write File",
      description: `Write or append text content to a file. Creates parent directories if needed.

Args:
  - path (string): File to write.
  - content (string): Text content to write.
  - mode ('rewrite' | 'append'): 'rewrite' replaces the entire file (default), 'append' adds to the end.

Returns: Confirmation with bytes written.

Error Handling:
  - "Access denied" if outside allowed directories.
  - For large content, prefer several 'append' calls over one giant 'rewrite' call to stay within response limits.`,
      inputSchema: {
        path: z.string().describe("File path to write"),
        content: z.string().describe("Content to write"),
        mode: z.enum(["rewrite", "append"]).default("rewrite").describe("Write mode"),
      },
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ path: filePath, content, mode }) => {
      try {
        const abs = resolveSafePath(filePath);
        await fs.mkdir(path.dirname(abs), { recursive: true });
        if (mode === "append") {
          await fs.appendFile(abs, content, "utf8");
        } else {
          await fs.writeFile(abs, content, "utf8");
        }
        const output = { path: abs, mode, bytesWritten: Buffer.byteLength(content, "utf8") };
        return { content: [{ type: "text", text: JSON.stringify(output) }], structuredContent: output };
      } catch (err) {
        return { content: [{ type: "text", text: errText(err) }], isError: true };
      }
    }
  );

  server.registerTool(
    "fs_edit_block",
    {
      title: "Edit File (Search & Replace)",
      description: `Make a surgical edit to a file by replacing an exact block of text with new text, without rewriting the whole file. This is the preferred way to make small changes to large files.

Args:
  - path (string): File to edit.
  - old_str (string): Exact text to find. Must match exactly once in the file, including whitespace/indentation.
  - new_str (string): Text to replace it with.
  - replace_all (boolean, optional): If true, replaces every occurrence instead of requiring exactly one match (default false).

Returns: Confirmation with number of replacements made.

Error Handling:
  - "No match found" if old_str isn't present verbatim — re-read the file with fs_read_file to get exact current content/whitespace.
  - "Ambiguous match: N occurrences found" if old_str isn't unique and replace_all wasn't set — include more surrounding context in old_str.`,
      inputSchema: {
        path: z.string().describe("File path to edit"),
        old_str: z.string().min(1).describe("Exact text to find and replace"),
        new_str: z.string().describe("Replacement text"),
        replace_all: z.boolean().default(false).describe("Replace all occurrences instead of requiring exactly one"),
      },
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ path: filePath, old_str, new_str, replace_all }) => {
      try {
        const abs = resolveSafePath(filePath);
        const original = await fs.readFile(abs, "utf8");
        const occurrences = original.split(old_str).length - 1;

        if (occurrences === 0) {
          return {
            content: [{ type: "text", text: `No match found for old_str in ${filePath}. Re-read the file to confirm exact current content, including whitespace.` }],
            isError: true,
          };
        }
        if (occurrences > 1 && !replace_all) {
          return {
            content: [
              {
                type: "text",
                text: `Ambiguous match: ${occurrences} occurrences of old_str found in ${filePath}. Either include more context in old_str to make it unique, or pass replace_all: true.`,
              },
            ],
            isError: true,
          };
        }

        const updated = replace_all ? original.split(old_str).join(new_str) : original.replace(old_str, new_str);
        await fs.writeFile(abs, updated, "utf8");
        const output = { path: abs, replacements: replace_all ? occurrences : 1 };
        return { content: [{ type: "text", text: JSON.stringify(output) }], structuredContent: output };
      } catch (err) {
        return { content: [{ type: "text", text: errText(err) }], isError: true };
      }
    }
  );

  server.registerTool(
    "fs_create_directory",
    {
      title: "Create Directory",
      description: `Create a directory, including any missing parent directories (like mkdir -p).

Args:
  - path (string): Directory path to create.

Returns: Confirmation of the created path.`,
      inputSchema: { path: z.string().describe("Directory path to create") },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ path: dirPath }) => {
      try {
        const abs = resolveSafePath(dirPath);
        await fs.mkdir(abs, { recursive: true });
        return { content: [{ type: "text", text: JSON.stringify({ created: abs }) }] };
      } catch (err) {
        return { content: [{ type: "text", text: errText(err) }], isError: true };
      }
    }
  );

  server.registerTool(
    "fs_move_file",
    {
      title: "Move or Rename File",
      description: `Move or rename a file or directory.

Args:
  - source (string): Current path.
  - destination (string): New path. Parent directories are created if needed.

Returns: Confirmation of the move.

Error Handling:
  - Both source and destination must resolve inside the allowed directories.
  - Fails if destination already exists (no silent overwrite) — use fs_write_file or delete first if overwrite is intended.`,
      inputSchema: {
        source: z.string().describe("Current file/directory path"),
        destination: z.string().describe("New file/directory path"),
      },
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ source, destination }) => {
      try {
        const absSrc = resolveSafePath(source);
        const absDst = resolveSafePath(destination);
        try {
          await fs.access(absDst);
          return { content: [{ type: "text", text: `Error: destination '${destination}' already exists. Refusing to overwrite silently.` }], isError: true };
        } catch {
          /* good, doesn't exist */
        }
        await fs.mkdir(path.dirname(absDst), { recursive: true });
        await fs.rename(absSrc, absDst);
        return { content: [{ type: "text", text: JSON.stringify({ moved: { from: absSrc, to: absDst } }) }] };
      } catch (err) {
        return { content: [{ type: "text", text: errText(err) }], isError: true };
      }
    }
  );

  server.registerTool(
    "fs_get_file_info",
    {
      title: "Get File Info",
      description: `Get metadata about a file or directory: size, type, timestamps, permissions.

Args:
  - path (string): Path to inspect.

Returns: JSON with size, isDirectory, isFile, isSymlink, created, modified, accessed, permissions (octal string).`,
      inputSchema: { path: z.string().describe("Path to inspect") },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ path: targetPath }) => {
      try {
        const abs = resolveSafePath(targetPath);
        const info = await statToFileInfo(abs);
        return { content: [{ type: "text", text: JSON.stringify(info, null, 2) }], structuredContent: info as unknown as Record<string, unknown> };
      } catch (err) {
        return { content: [{ type: "text", text: errText(err) }], isError: true };
      }
    }
  );

  server.registerTool(
    "fs_search_files",
    {
      title: "Search Files by Name",
      description: `Recursively search a directory tree for files/directories whose name matches a substring or pattern (case-insensitive substring match).

Args:
  - path (string): Directory to search from.
  - pattern (string): Substring to match against file/directory names.
  - max_depth (number, optional): Max recursion depth (default 8).
  - max_results (number, optional): Max matches to return (default 200).

Returns: JSON array of matching absolute paths.

Use fs_search_code instead if you need to search file *contents*, not names.`,
      inputSchema: {
        path: z.string().describe("Directory to search from"),
        pattern: z.string().min(1).describe("Substring to match in file/directory names"),
        max_depth: z.number().int().min(1).max(20).default(8),
        max_results: z.number().int().min(1).max(1000).default(200),
      },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ path: startPath, pattern, max_depth, max_results }) => {
      try {
        const abs = resolveSafePath(startPath);
        const needle = pattern.toLowerCase();
        const matches: string[] = [];
        await walk(abs, { maxDepth: max_depth, maxEntries: 50000 }, async (candidate) => {
          if (matches.length >= max_results) return false;
          if (path.basename(candidate).toLowerCase().includes(needle)) {
            matches.push(candidate);
          }
          return true;
        });
        const output = { searchedFrom: abs, pattern, count: matches.length, matches };
        return { content: [{ type: "text", text: truncate(JSON.stringify(output, null, 2)) }], structuredContent: output };
      } catch (err) {
        return { content: [{ type: "text", text: errText(err) }], isError: true };
      }
    }
  );

  server.registerTool(
    "fs_search_code",
    {
      title: "Search File Contents",
      description: `Recursively search text files under a directory for lines matching a substring or regex, similar to grep -rn.

Args:
  - path (string): Directory to search from.
  - pattern (string): Text to search for in file contents.
  - is_regex (boolean, optional): Treat pattern as a regular expression (default false = literal substring).
  - file_extension (string, optional): Only search files with this extension, e.g. "ts" or "md" (no leading dot).
  - max_depth (number, optional): Max recursion depth (default 8).
  - max_results (number, optional): Max matching lines to return (default 200).

Returns: JSON array of { file, line, text } for each match. Binary files are skipped automatically.`,
      inputSchema: {
        path: z.string().describe("Directory to search from"),
        pattern: z.string().min(1).describe("Text or regex to search for"),
        is_regex: z.boolean().default(false),
        file_extension: z.string().optional().describe("Restrict to files with this extension (no dot)"),
        max_depth: z.number().int().min(1).max(20).default(8),
        max_results: z.number().int().min(1).max(1000).default(200),
      },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ path: startPath, pattern, is_regex, file_extension, max_depth, max_results }) => {
      try {
        const abs = resolveSafePath(startPath);
        const re = is_regex ? new RegExp(pattern) : null;
        const needle = pattern.toLowerCase();
        const matches: { file: string; line: number; text: string }[] = [];
        const SKIP_DIRS = new Set(["node_modules", ".git", "dist", "build", "__pycache__", ".venv"]);

        await walk(abs, { maxDepth: max_depth, maxEntries: 20000 }, async (candidate) => {
          if (matches.length >= max_results) return false;
          const base = path.basename(candidate);
          if (SKIP_DIRS.has(base)) return true; // skip descending, but keep sibling iteration going
          let st;
          try {
            st = await fs.lstat(candidate);
          } catch {
            return true;
          }
          if (!st.isFile()) return true;
          if (file_extension && path.extname(candidate).replace(/^\./, "") !== file_extension) return true;
          if (st.size > 2_000_000) return true; // skip huge files

          let content: string;
          try {
            const buf = await fs.readFile(candidate);
            if (buf.subarray(0, 8192).includes(0)) return true; // binary
            content = buf.toString("utf8");
          } catch {
            return true;
          }
          const lines = content.split("\n");
          for (let i = 0; i < lines.length; i++) {
            if (matches.length >= max_results) break;
            const line = lines[i];
            const hit = re ? re.test(line) : line.toLowerCase().includes(needle);
            if (hit) matches.push({ file: candidate, line: i + 1, text: line.trim().slice(0, 300) });
          }
          return true;
        });

        const output = { searchedFrom: abs, pattern, count: matches.length, matches };
        return { content: [{ type: "text", text: truncate(JSON.stringify(output, null, 2)) }], structuredContent: output };
      } catch (err) {
        return { content: [{ type: "text", text: errText(err) }], isError: true };
      }
    }
  );
}
