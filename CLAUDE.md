# CLAUDE.md — FusionAL

This file is the authoritative AI assistant guide for the `fusional` repository.
Read this before making any changes.

## What This Repo Is

FusionAL is a **self-hosted MCP governance gateway** that sits between AI clients
(Claude Desktop, Christopher, any MCP client) and MCP tool servers. It provides:

- Central auth and rate limiting across all connected servers
- Tool-level policy enforcement (strict / balanced / dev profiles)
- Full audit trail of every tool call
- Docker-sandboxed Python code execution
- AI-powered MCP server generation (describe it → Claude builds and registers it)
- Server registry / catalog

Primary deployment target: `t3610` — a remote Linux server, port `8009`.
This repo pairs with `mcp-consulting-kit` (the server collection) and
`christopher-ai` (local voice assistant).

---

## Architecture

```
Claude Desktop / Christopher / Any MCP Client
        │
        ▼  (Streamable HTTP at /mcp  OR  SSE at /sse)
  FusionAL Gateway  (:8009)
        │
   ┌────┴────────────┐
   ▼                 ▼
FastAPI           MCP Transport
REST API          ├── execute_code
                  ├── generate_and_execute
                  └── generate_mcp_project
        │
        ▼
  Docker Sandbox Executor  (network-isolated, memory-capped)
        │
        ▼
  MCP Server Registry (JSON file: core/mcp_registry.json)
  ├── business-intelligence-mcp  (:8101)  — from mcp-consulting-kit
  ├── api-integration-hub        (:8102)  — from mcp-consulting-kit
  ├── content-automation-mcp     (:8103)  — from mcp-consulting-kit
  └── <generated servers>        (:8200+) — dynamically created
```

---

## Directory Structure

```
fusional/
├── core/                      # Main FastAPI application
│   ├── main.py                # Gateway entry point — REST API + MCP mount
│   ├── ai_agent.py            # Claude/OpenAI code generation
│   ├── mcp_transport.py       # MCP tool definitions (execute_code etc.)
│   ├── policy_profiles.py     # strict / balanced / dev policy enforcement
│   ├── runner_docker.py       # Docker sandbox executor
│   ├── common/                # Symlinked or copied from mcp-consulting-kit
│   ├── middleware/            # FastAPI middleware
│   ├── models/                # Pydantic request/response models
│   ├── services/
│   │   └── key_manager.py     # API key rotation service
│   ├── requirements.txt       # Pinned Python deps
│   ├── Dockerfile             # Production image
│   ├── quick_test.py          # Quick smoke test
│   └── test_fusional.py       # Integration tests
├── examples/
│   ├── dice-roller/           # D&D dice (8 tools) — reference implementation
│   ├── weather-api/           # External API integration
│   └── file-utils/            # Safe filesystem access
├── migrations/                # DB schema migrations (if applicable)
├── mcp-builder-prompt/        # Prompt templates for MCP generation
├── well-known/                # Static files served at /.well-known/
├── notion_poller.py           # Polls Notion and forwards tasks to FusionAL
├── init.py                    # One-time initialization script
├── compose.yaml               # Simple Docker Compose (gateway only)
├── compose.debug.yaml         # Debug compose override
├── Dockerfile                 # Root-level Dockerfile (production)
└── .env.example               # All env vars with descriptions
```

---

## How to Run

### Local development

```bash
# Install deps
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows
pip install -r core/requirements.txt

# Copy and configure env
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, API_KEY, etc.

# Start the gateway
cd core
python -m uvicorn main:app --reload --port 8009
```

Verify: `curl http://localhost:8009/health`

### Docker

```bash
# Build and run
docker build -t fusional .
docker run -d -p 8009:8009 --name fusional fusional

# Or with Compose
docker compose up -d
```

### Connect to Claude Desktop

```json
{
  "mcpServers": {
    "fusional-gateway": {
      "url": "http://localhost:8009/mcp"
    }
  }
}
```

---

## REST API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | none | Health check — returns policy profile name |
| `/execute` | POST | API key | Run Python code (optional Docker sandbox) |
| `/register` | POST | API key | Register an MCP server in the catalog |
| `/catalog` | GET | none | List all registered servers |
| `/generate` | POST | API key | Generate + launch a new MCP server from a prompt |
| `/audit/export/json` | GET | API key | Export audit records as JSON |
| `/audit/export/csv` | GET | API key | Export audit records as CSV |
| `/mcp` | — | — | Streamable HTTP MCP transport |

Audit export supports `?start=<ISO8601>&end=<ISO8601>` query params.

---

## MCP Tools (via `/mcp`)

| Tool | Description |
|------|-------------|
| `execute_code` | Run Python in an isolated subprocess (or Docker sandbox) |
| `generate_and_execute` | Plain English → Claude writes Python → runs it |
| `generate_mcp_project` | Describe a server → Claude builds the full project, registers it |

---

## Environment Variables

All vars documented in `.env.example`. Key ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Enables Claude-powered code generation |
| `OPENAI_API_KEY` | — | Fallback if Anthropic unavailable |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-20241022` | Model for code generation |
| `OPENAI_MODEL` | `gpt-4-turbo` | OpenAI model fallback |
| `API_KEY` | — | Required for protected endpoints |
| `API_KEYS` | — | Comma-sep list for zero-downtime key rotation |
| `REVOKED_API_KEYS` | — | Denylist |
| `FUSIONAL_POLICY_PROFILE` | `balanced` | `strict` / `balanced` / `dev` |
| `ALLOWED_ORIGINS` | `http://localhost,...` | CORS allowlist |
| `RATE_LIMIT_REQUESTS` | `60` | Requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window length |
| `REDIS_URL` | — | Optional Redis for shared rate limiting |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `PORT` | `8009` | Gateway port |
| `NOTION_TOKEN` | — | For `notion_poller.py` |
| `FUSIONAL_URL` | `http://localhost:8009` | For `notion_poller.py` |
| `POLL_INTERVAL` | `30` | Notion polling interval (seconds) |

---

## Policy Profiles

Set via `FUSIONAL_POLICY_PROFILE` env var. Enforced at `/execute` and `/generate`.

| Profile | Docker | Timeout | Memory | Sandbox |
|---------|--------|---------|--------|---------|
| `strict` | Required | 10s | 64MB | Always |
| `balanced` (default) | Recommended | 15s | 128MB | On |
| `dev` | Optional | 30s | 256MB | Optional |

Policy logic lives in `core/policy_profiles.py`. The active profile is logged at startup
and returned in `/health` responses.

---

## Security Model

### API Key Authentication

Protected endpoints check the `X-API-Key` header against `API_KEY` / `API_KEYS`.
Implemented in `showcase-servers/common/security.py` from `mcp-consulting-kit`.

The gateway resolves this module at startup by searching these candidate paths:
1. `core/common/` (if present as symlink or copy)
2. `~/Projects/mcp-consulting-kit/showcase-servers/common/`
3. `~/projects/mcp-consulting-kit/showcase-servers/common/`
4. `~/mcp-consulting-kit/showcase-servers/common/`
5. Two levels up from `core/` → `mcp-consulting-kit/showcase-servers/common/`

If the module is not found, security is disabled and a warning is logged.

### Docker Sandbox (for `/execute`)

When `use_docker=true`:
- `--network none` — no network access
- `--memory` — capped (default 128MB per policy)
- `--pids-limit 64` — process limits
- Read-only filesystem except `/tmp`
- No privilege escalation
- Non-root user

### Audit Logging

Every tool call is recorded via `audit.py`. Export at `/audit/export/json` or
`/audit/export/csv` with optional time-range filtering.

---

## AI Code Generation

The `/generate` endpoint and `generate_mcp_project` MCP tool use this provider chain:
1. Try `ANTHROPIC_API_KEY` → `generate_python_from_claude()` in `core/ai_agent.py`
2. Fall back to `OPENAI_API_KEY` → `generate_python_from_openai()`
3. Fall back to local template (`_generate_local_server_code()`)

Generated servers are:
- Saved to a temp directory
- Launched as a subprocess on a dynamically assigned port (8200–8299)
- Registered in `core/mcp_registry.json`

Slug rules: prompt text → lowercase, non-alphanumeric → `-`, max 80 chars, suffix `-mcp`.

---

## Server Registry

Persisted to `core/mcp_registry.json`. Three showcase servers from `mcp-consulting-kit`
are pre-loaded at startup (`_SHOWCASE_SERVERS` in `main.py`) and merged with the file.

Registry entry structure:
```json
{
  "server-name": {
    "description": "...",
    "url": "http://localhost:PORT",
    "metadata": {"tools": [...], "port": PORT, "source": "generated"},
    "registered_at": "2026-01-01T00:00:00"
  }
}
```

---

## Key Dependencies (core/requirements.txt)

| Package | Version | Purpose |
|---------|---------|--------|
| `fastapi` | 0.143.0 | Web framework |
| `uvicorn[standard]` | 0.45.0 | ASGI server |
| `pydantic` | 2.15.0 | Request/response models |
| `anthropic` | 0.96.0 | Claude API client |
| `openai` | 2.32.0 | OpenAI fallback |
| `mcp[cli]` | 1.27.1 | MCP server framework |
| `redis` | 7.4.0 | Rate limit store |
| `opentelemetry-*` | ≥1.40.0 | Distributed tracing |

Always pin `setuptools ≥82.0.1`, `jaraco.context ≥6.1.2`, `wheel ≥0.46.3` to avoid
known CVEs in transitive deps.

---

## MCP Server Authoring Conventions

New tools in `core/mcp_transport.py` must follow:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fusional")

@mcp.tool()
async def my_tool(param: str = "") -> str:
    """One-line description — multi-line breaks some MCP clients."""
    return f"Result: {param}"
```

- Single-line docstrings only.
- Default parameters to `""` not `None`.
- Return formatted strings.
- Mount at `/mcp`: `app.mount("/mcp", mcp.streamable_http_app())`
- Use `# nosec B404` on subprocess imports, `# nosec B603` on list-form subprocess.run.
  Never suppress `B602` (shell=True injection risk).

---

## Notion Poller

`notion_poller.py` is a separate long-running process that polls a Notion database and
forwards tasks to FusionAL's `/execute` endpoint.

```bash
python notion_poller.py
```

Configured via `.env`: `NOTION_TOKEN`, `FUSIONAL_URL`, `POLL_INTERVAL`,
`HEALTH_CHECK_FAILURES_THRESHOLD`.

---

## Testing

```bash
cd core
python quick_test.py          # Smoke test — requires running server
python test_fusional.py       # Integration tests
```

---

## Cross-Repo Relationships

| Dependency | Direction | Details |
|-----------|-----------|--------|
| `mcp-consulting-kit/showcase-servers/common/` | This repo imports from it | Security, audit, tracing modules |
| `mcp-consulting-kit` MCP servers (8101–8103) | Pre-registered in this gateway | `_SHOWCASE_SERVERS` in `main.py` |
| `christopher-ai` | Connects to this gateway | Via `FUSIONAL_*_URL` env vars |

Local development assumes all repos are siblings:
```
~/Projects/
├── mcp-consulting-kit/
├── FusionAL/
└── Christopher-AI/
```

---

## Common Development Mistakes to Avoid

- Do not use `shell=True` in any subprocess call.
- Do not use `None` as a default for MCP tool parameters.
- Do not write multi-line docstrings on `@mcp.tool()` functions.
- Do not modify `_SHOWCASE_SERVERS` without updating the counterpart in `mcp-consulting-kit`.
- Do not break the `common/` path search logic — `fusional` must be able to find it at runtime.
- Do not change the `/mcp` mount path without updating all client configurations.
- Do not commit `.env` files or API keys.
- Always update `core/mcp_registry.json.bak` if you change the registry format.
