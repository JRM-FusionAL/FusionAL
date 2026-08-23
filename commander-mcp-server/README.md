# commander-mcp-server

A self-hosted, Desktop-Commander-style MCP server: filesystem + persistent terminal
control, exposed over Streamable HTTP so it can live inside the FusionAL gateway
stack instead of only being reachable from Claude Desktop on one machine.

**Why this exists:** Desktop Commander only connects when Claude Desktop is running
locally with a direct filesystem/SSH connection. That means any session running in
claude.ai's web/mobile chat (or anywhere else that isn't your desktop) can't touch
your files or run commands — which is exactly the wall we hit trying to compile
context in this project. Running this behind `gateway.fusional.dev` fixes that:
any client that can call the FusionAL gateway gets Commander-equivalent power,
not just Claude Desktop.

Tested end-to-end (all 21 tools, path-escape rejection, command blocking,
timeout/kill semantics, interactive stdin/stdout) before delivery — see
"What was actually tested" below.

---

## Tools (21)

**Filesystem**
| Tool | Does |
|---|---|
| `fs_list_directory` | One-level directory listing |
| `fs_read_file` | Read a file, optionally by line range; binary files auto-detected and returned base64 |
| `fs_read_multiple_files` | Batch-read up to 20 files in one call |
| `fs_write_file` | Rewrite or append a file (creates parent dirs) |
| `fs_edit_block` | Surgical search/replace on a file — the preferred way to make small edits |
| `fs_create_directory` | `mkdir -p` equivalent |
| `fs_move_file` | Move/rename (refuses to silently overwrite) |
| `fs_get_file_info` | Size, type, timestamps, permissions |
| `fs_search_files` | Recursive filename search |
| `fs_search_code` | Recursive content search (grep-like, literal or regex) |

**Process / Terminal**
| Tool | Does |
|---|---|
| `proc_start` | Run a command as a persistent, pollable session (not fire-and-forget) |
| `proc_read_output` | Poll new stdout/stderr since the last read |
| `proc_write_input` | Send stdin to a running process (REPLs, prompts) |
| `proc_list_sessions` | List all tracked sessions |
| `proc_get_session` | Full detail incl. complete buffered output for one session |
| `proc_terminate` | Stop a session (SIGTERM or SIGKILL) |
| `proc_list_system` | Raw `ps aux` — OS-level view, not just this server's sessions |
| `proc_kill_system` | Signal any OS pid by number |

**Config**
| Tool | Does |
|---|---|
| `config_get` | View allowed root/directories, blocked command patterns, default shell |
| `config_set_allowed_directories` | Narrow the working set (can never widen past `ALLOWED_ROOT`) |
| `config_add_blocked_command_pattern` | Add a regex to the command blocklist |

---

## Security model

1. **`ALLOWED_ROOT`** — set once via env var at container start. This is the hard
   ceiling. No tool, including `config_set_allowed_directories`, can ever move
   filesystem or process `cwd` access outside it. Symlinks are resolved and
   checked too, so a symlink inside the allowed root can't point you outside it.
2. **Command blocklist** — `proc_start` checks every command against a regex
   list before running it (fork bombs, `rm -rf /`, disk-wiping `dd`, `shutdown`,
   piping `curl`/`wget` into `sh`, etc.). Additive only via
   `config_add_blocked_command_pattern` — nothing removes the defaults.
3. **Process lifetime cap** — every `proc_start` session is force-killed after
   10 minutes regardless of what it's doing, so nothing can wedge the server open.

None of this makes handing out shell + filesystem access *safe* in an absolute
sense — it makes the blast radius bounded and visible. Point `ALLOWED_ROOT` at
the narrowest directory that actually covers what you need this for, not `/`.

---

## Running it

**Local (stdio, for a Claude Desktop config):**
```bash
npm install
npm run build
ALLOWED_ROOT=/path/you/want/exposed npm start
```

**Remote (HTTP, for the gateway):**
```bash
docker compose -f docker-compose.snippet.yaml build commander
docker compose -f docker-compose.snippet.yaml up -d commander
curl http://localhost:8108/health
```
See `docker-compose.snippet.yaml` for the block to merge into your actual
`/data/projects/FusionAL/compose.yaml`, and `.env.example` for the variables.

Default port is **8108** — 8107 is already `recall` in your compose file.

---

## What was actually tested (this session)

- Full MCP handshake (`initialize`, `tools/list`) over Streamable HTTP
- `fs_write_file` → `fs_read_file` → `fs_edit_block` → `fs_list_directory` round trip
- Path-escape attempt (`/etc/passwd`) correctly rejected with `Access denied`
- `proc_start` with a dangerous command (`rm -rf /`) correctly blocked before spawning
- Timeout-triggered kill: found and fixed a bug where the exit handler was
  overwriting `"terminated"` status back to `"failed"` — verified fixed
- Found and fixed a bug where a short `timeout_ms` (meant only to control how
  fast `proc_start` returns) was also killing the underlying process early,
  which would have silently broken every interactive/long-running session
- Full interactive round trip: started `cat`, `proc_write_input`'d text into
  it, `proc_read_output` confirmed the echo, `proc_terminate`'d cleanly

## Known gaps vs. the real Desktop Commander

- No true PTY (`node-pty`) — `proc_start`/`proc_write_input` use plain pipes,
  which covers REPLs and most interactive prompts but not full terminal
  emulation (no ANSI cursor control, `less`/`vim`-style full-screen apps won't
  render correctly). Worth adding `node-pty` later if you hit a wall on this.
- No built-in SSH tool for reaching T3610 from elsewhere — either run this
  server *on* T3610 directly (simplest), or add an `ssh2`-based tool if you
  need to reach multiple hosts from one instance.
- Session store is a single in-memory `Map`, process-wide — fine for one
  gateway instance, won't survive a container restart or scale past one replica.

---

## Wiring into Claude

- **As a registered connector**, same slot `fusional-gateway` already occupies —
  usable from Artifacts via `mcp_servers: [{ type: "url", url: "https://gateway.fusional.dev/mcp", name: "..." }]`.
- **As a direct MCP connection** in Claude Desktop / a client that supports
  remote servers — point it at `https://gateway.fusional.dev/mcp` (or wherever
  you expose the `commander` service through the tunnel) once it's proxied
  through your existing ingress config, the same way the other FusionAL
  services are.
