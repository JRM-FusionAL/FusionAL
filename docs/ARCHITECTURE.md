# FusionAL Architecture Guide

> **FusionAL** is a self-hosted MCP (Model Context Protocol) governance gateway that sits between AI clients and tool servers. It provides centralized auth, tool-level policy enforcement, token control, full audit trails, and AI-powered MCP server generation.

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Project Structure](#2-project-structure)
3. [Core Components](#3-core-components)
   - [3.1 FastAPI Application — `core/main.py`](#31-fastapi-application--coremainpy)
   - [3.2 MCP Aggregating Proxy — `core/mcp_transport.py`](#32-mcp-aggregating-proxy--corpmcp_transportpy)
   - [3.3 AI Agent — `core/ai_agent.py`](#33-ai-agent--coreai_agentpy)
   - [3.4 Docker Sandbox Runner — `core/runner_docker.py`](#34-docker-sandbox-runner--corerunner_dockerpy)
   - [3.5 Security Layer](#35-security-layer)
   - [3.6 Audit System — `core/common/audit.py`](#36-audit-system--corecommonauditpy)
   - [3.7 Distributed Tracing — `core/common/tracing.py`](#37-distributed-tracing--corecommontracingpy)
4. [MCP Server Registry](#4-mcp-server-registry)
5. [Server Generation Pipeline](#5-server-generation-pipeline)
6. [Deployment Architecture](#6-deployment-architecture)
7. [Data Flow](#7-data-flow)
8. [Environment Configuration](#8-environment-configuration)
9. [Scripts & Supporting Tools](#9-scripts--supporting-tools)

---

## 1. High-Level Overview

```
                  ┌──────────────────────────────────┐
                  │     MCP Client (Claude, etc.)    │
                  │       SSE / Streamable HTTP       │
                  └──────────────┬───────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────────┐
                  │       FusionAL Gateway (:8009)    │
                  │                                   │
                  │  ┌────────────┐  ┌─────────────┐  │
                  │  │ FastAPI    │  │ FastMCP      │  │
                  │  │ REST API   │  │ Aggregating  │  │
                  │  │            │  │ Proxy (/mcp) │  │
                  │  └─────┬──────┘  └──────┬───────┘  │
                  │        │                │          │
                  │        ▼                ▼          │
                  │  ┌─────────────────────────────┐   │
                  │  │    AI Agent / Docker Runner  │   │
                  │  └─────────────────────────────┘   │
                  └──────────────────┬─────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                 ▼
           ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
           │  Showcase   │  │  Showcase    │  │  Generated   │
           │  Server A   │  │  Server B    │  │  Server N    │
           │  (:8101)    │  │  (:8102)     │  │  (:8200-8299)│
           └─────────────┘  └──────────────┘  └──────────────┘
```

FusionAL operates as a **single-entry gateway** for MCP clients. Clients connect once via SSE or Streamable HTTP; FusionAL transparently proxies tool calls to registered downstream servers. All tool calls are logged, auditable, and subject to authentication and rate-limiting policies.

### Tier Architecture

FusionAL's governance model organizes MCP servers into tiers:

| Tier | Description | Examples |
|------|-------------|----------|
| **Tier 0** | Core gateway services | `fusional-recall`, `kb-server` |
| **Tier 1** | Showcase / curated servers | `business-intelligence-mcp`, `api-integration-hub` |
| **Tier 2** | AI-generated / dynamic servers | Servers created via `/generate` on ports 8200–8299 |

---

## 2. Project Structure

```
FusionAL/
├── Dockerfile                         # Production container image
├── compose.yaml                       # Docker Compose (native deployment)
├── compose.debug.yaml                 # Docker Compose (debugpy remote debug)
├── requirements.txt                   # Python dependencies
├── mcp_registry.json                  # Persistent MCP server registry
├── .env                               # Environment configuration
├── core/
│   ├── main.py                        # FastAPI application + REST endpoints
│   ├── mcp_transport.py               # FastMCP aggregating proxy
│   ├── ai_agent.py                    # AI code generation (Claude / OpenAI)
│   ├── runner_docker.py               # Docker sandbox execution
│   ├── security.py                    # Local auth + rate limiting module
│   ├── __init__.py
│   ├── common/
│   │   ├── security.py                # Advanced security: CORS, log middleware, Redis RL
│   │   ├── audit.py                   # Tool-call audit store (ring buffer)
│   │   ├── tracing.py                 # OpenTelemetry distributed tracing
│   │   ├── rate_limit_presets.py      # Pre-configured rate limit profiles
│   │   └── test_*.py                  # Unit tests
│   ├── Dockerfile                     # Core-only container build
│   ├── test_fusional.py               # Integration test suite
│   └── quick_test.py                  # Quick AI generation test
├── scripts/
│   ├── watchdog.py                    # Health monitoring + auto-restart
│   ├── think_tank.py                  # AI-driven fault diagnosis
│   ├── think_tank_trigger.py          # Think Tank dispatch
│   ├── notion_reporter.py             # Notion-based reporting
│   ├── action_executor.py             # Action execution
│   └── test_pipeline.py               # Pipeline test
├── examples/
│   ├── dice-roller/                   # D&D dice MCP server example
│   ├── weather-api/                   # OpenWeather MCP server example
│   └── file-utils/                    # File operation MCP server example
└── docs/
    ├── ARCHITECTURE.md                # THIS FILE
    ├── custom-servers.md              # Building custom MCP servers
    ├── docker-gateway.md              # Docker deployment notes
    └── troubleshooting.md             # Common issues & solutions
```

---

## 3. Core Components

### 3.1 FastAPI Application — `core/main.py`

The central application orchestrates all services. It is a **FastAPI** app running via **uvicorn** on port 8009 (configurable via `PORT`).

#### REST API Endpoints

| Endpoint | Method | Authentication | Description |
|----------|--------|---------------|-------------|
| `/health` | GET | None | Health check returning service status |
| `/execute` | POST | Optional API key | Execute Python code (subprocess or Docker sandbox) |
| `/register` | POST | Optional API key | Register a new MCP server in the registry |
| `/catalog` | GET | Optional API key | List all registered MCP servers |
| `/generate` | POST | Optional API key | AI-powered MCP server generation |
| `/audit/export/json` | GET | Optional API key | Export tool-call audit records as JSON |
| `/audit/export/csv` | GET | Optional API key | Export tool-call audit records as CSV |

#### MCP Mount

FastMCP's **Streamable HTTP** transport is mounted at `/mcp`:

```python
mcp.settings.streamable_http_path = "/"
mcp_app = mcp.streamable_http_app()
app.mount("/mcp", mcp_app)
```

Clients connect to `http://host:8009/sse` or `http://host:8009/mcp` for Streamable HTTP.

#### Module Loading Strategy

The application uses **graceful optional imports** with a multi-path security module resolver:

1. Looks for `core/common/security.py` first
2. Falls back to `mcp-consulting-kit/showcase-servers/common/` at multiple path depths
3. If missing — security features are **disabled** (open access / dev mode)
4. Same pattern for `tracing` and `audit` modules — missing modules degrade gracefully

#### Well-Known Directory

If a `well-known/` directory exists, it is mounted at `/.well-known` for domain verification and discovery.

### 3.2 MCP Aggregating Proxy — `core/mcp_transport.py`

This is the **heart of FusionAL's governance capability**. It exposes a single FastMCP server that aggregates tools from all registered downstream MCP servers.

#### How It Works

1. **Startup**: `register_downstream_tools(registry)` iterates over every server in the registry
2. **Connection**: For each server, it connects via `streamablehttp_client` to `<server_url>/mcp`
3. **Discovery**: Calls `session.list_tools()` to fetch the server's tool manifest
4. **Namespacing**: Each tool is renamed with a short namespace prefix (e.g., `bi_nl_query`, `github_create_issue`)
5. **Registration**: A `_make_passthrough_tool` creates a FastMCP Tool with a passthrough `_PassthroughArgModel` that accepts any JSON arguments
6. **Proxying**: When called, the proxy connects to the downstream server via `streamablehttp_client`, calls `session.call_tool()`, and returns the result

#### Namespace Mapping

| Server Name | Namespace Prefix | Example Proxied Tool |
|-------------|-----------------|---------------------|
| `business-intelligence-mcp` | `bi` | `bi_nl_query` |
| `api-integration-hub` | `api` | `api_slack_send` |
| `content-automation-mcp` | `content` | `content_scrape_article` |
| `github-mcp-safe` | `github` | `github_list_issues` |
| `intelligence-mcp` | `intel` | `intel_*` |
| `fusional-recall` | `recall` | `recall_search` |
| `kb-server` | `kb` | `kb_search` |

#### Built-in Tools (REST-only in Phase 0)

| Tool | Purpose | Status |
|------|---------|--------|
| `execute_code` | Run Python in isolated subprocess | REST `/execute` only |
| `generate_and_execute` | Prompt → Claude writes code → runs it | REST only |
| `generate_mcp_project` | Scaffold full MCP server project from prompt | REST `/generate` only |

#### URL Resolution for Downstream Servers

Each registered server can have up to three URLs:

- **`url`**: External/catalog URL (e.g., `http://localhost:8101`)
- **`internal_url`**: Docker bridge network URL (e.g., `http://business-intelligence-mcp:8101`)
- **`native_url`**: Host loopback URL (e.g., `http://127.0.0.1:8101`)

The proxy selects the appropriate URL based on runtime context (detecting Docker via `/.dockerenv`).

#### Retry Logic

The proxy retries downstream connections once after a 3-second delay to handle startup race conditions (e.g., `kb-server`'s MCP thread not yet bound when FusionAL starts). Failures are logged as warnings but do not prevent FusionAL from starting.

### 3.3 AI Agent — `core/ai_agent.py`

Generates MCP servers using AI (Claude or OpenAI). Supports three operations:

#### `generate_python_from_claude(prompt)`
- Calls Anthropic Messages API (`claude-3-5-sonnet-20241022` by default)
- Returns raw generated Python code

#### `generate_python_from_openai(prompt)`
- Calls OpenAI Chat Completions API (`gpt-4-turbo` by default)  
- Returns raw generated Python code

#### `generate_and_execute(prompt, provider, timeout, use_docker)`
- End-to-end pipeline: prompt → AI generation → execute on FusionAL
- Useful for one-shot code generation + execution

#### `generate_mcp_project(prompt, provider, out_dir, build, image_tag)`
- Generates a **complete MCP server project** including:
  - `Dockerfile`
  - `requirements.txt`
  - `main_server.py`
  - `README.md`
- Uses `=== FILE: path ===` markers for multi-file output
- Optionally builds a Docker image from the generated project
- Falls back to a builder prompt template from `mcp-builder-prompt/` if available

#### Provider Fallback Chain

The `/generate` endpoint uses a cascading fallback:
1. **Anthropic** (Claude) — if `ANTHROPIC_API_KEY` is set
2. **OpenAI** — if `OPENAI_API_KEY` is set and Claude failed
3. **Local template** — generates a simple ping/echo server with health endpoint

### 3.4 Docker Sandbox Runner — `core/runner_docker.py`

Executes untrusted Python code in a **hardened Docker container** with the following security constraints:

| Constraint | Implementation | Purpose |
|------------|---------------|---------|
| Network isolation | `--network none` | Prevents data exfiltration |
| Memory limit | `--memory=128m` (configurable) | Prevents resource exhaustion |
| Process limit | `--pids-limit 64` | Prevents fork bombs |
| No privilege escalation | `--security-opt no-new-privileges` | Prevents container escape |
| Drop all capabilities | `--cap-drop ALL` | Reduces kernel attack surface |
| Read-only filesystem | `--read-only` | Prevents persistent writes |
| Temp filesystem | `--tmpfs /tmp:rw,exec,noexec,size=64m` | Controlled write space |
| Non-root user | `--user 1000:1000` | Reduces privilege |
| Disposable | `--rm` | Auto-removed after execution |

The base image is `python:3.11-slim` (auto-pulled if missing). Code is mounted as a read-only volume.

### 3.5 Security Layer

FusionAL has a **layered security architecture** with two files providing complementary protections:

#### `core/security.py` — Local Module
- **API Key Authentication**: Reads `API_KEY` or `API_KEYS` environment variables
- **Key Revocation**: `REVOKED_API_KEYS` env var for immediate key blacklisting
- **Rate Limiting**: In-memory sliding window (configurable via `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS`)
- **CORS**: Configurable via `ALLOWED_ORIGINS`

#### `core/common/security.py` — Advanced Module (shared from mcp-consulting-kit)
- **Redis-backed rate limiting** with automatic in-memory fallback
- **Structured JSON logging middleware** with:
  - Request ID tracing (`X-Request-ID`)
  - Sensitive data redaction (API keys, tokens, passwords)
  - Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `CSP`, `Referrer-Policy`)
- **Observability middleware** logging request duration, method, path, status code

#### Security Headers Applied
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; ...
```

### 3.6 Audit System — `core/common/audit.py`

Provides a **thread-safe, bounded audit trail** for every MCP tool invocation.

#### Architecture
- **Ring buffer**: In-memory list with configurable max records (default 10,000)
- **Thread safety**: Uses `threading.Lock` for concurrent access
- **Optional persistence**: Appends each record as NDJSON to `AUDIT_STORE_PATH`

#### Audit Record Schema
```python
{
    "timestamp": "2026-01-15T12:00:00.000000+00:00",  # ISO 8601 UTC
    "tool": "bi_nl_query",                              # Proxied tool name
    "status": "success" | "error",                      # Call outcome
    "duration_ms": 234.56,                              # Wall-clock time
    "request_id": "uuid-here",                          # X-Request-ID or generated
    "trace_id": "hex-trace-id",                         # OpenTelemetry trace ID
    "span_id": "hex-span-id",                           # OpenTelemetry span ID
    "error": ""                                         # Error message (empty on success)
}
```

#### Integration
- The audit hook is wired in `main.py` via `set_audit_hook(record_tool_call)`
- The MCP proxy calls `_record_tool_call()` in its `finally` block for every proxied tool call
- Export available via `/audit/export/json` and `/audit/export/csv` with optional date range filtering

### 3.7 Distributed Tracing — `core/common/tracing.py`

Based on **OpenTelemetry** with automatic FastAPI instrumentation.

#### Configuration
| Env Variable | Default | Description |
|-------------|---------|-------------|
| `TRACING_ENABLED` | `true` | Set to `false` to disable |
| `OTLP_ENDPOINT` | (console exporter) | OTLP HTTP endpoint (e.g., `http://localhost:4318`) |
| `SERVICE_NAME` | App title | Service name for traces |

#### Behavior
- If OpenTelemetry packages are not installed: **no-op with a warning**
- If `OTLP_ENDPOINT` is set: exports traces via OTLP (Jaeger/Tempo/Zipkin)
- If `OTLP_ENDPOINT` is unset: traces go to console (dev mode)
- `get_trace_context()` returns `trace_id` and `span_id` for correlation
- Trace IDs are embedded in audit records and structured logs

---

## 4. MCP Server Registry

FusionAL maintains a **JSON-based registry** of all known MCP servers.

### Registry Sources

1. **Built-in showcase servers** (hardcoded in `main.py`):
   - `business-intelligence-mcp` (:8101)
   - `api-integration-hub` (:8102)
   - `content-automation-mcp` (:8103)
   - `github-mcp-safe` (:8105)
   - `intelligence-mcp` (:8104)
   - `fusional-recall` (:8107)
   - `kb-server` (:8106)

2. **Persistent file** (`mcp_registry.json`): Merged at startup

3. **Dynamic registration**: Via `POST /register` API

4. **Generated servers**: Auto-registered after AI generation via `POST /generate`

### Registry Persistence

```python
REGISTRY_FILE = os.path.join(os.getcwd(), "mcp_registry.json")
```

Loaded at startup via `_load_registry()` and saved after every registration via `_save_registry()`.

---

## 5. Server Generation Pipeline

When a client calls `POST /generate`:

```
  User Prompt
       │
       ▼
  ┌────────────────┐
  │  Slugify Name  │  →  "build a weather API server"  →  "build-a-weather-api-server-mcp"
  └───────┬────────┘
          │
          ▼
  ┌─────────────────────────────┐
  │  AI Provider (Cascade)      │
  │                              │
  │  1. Anthropic (Claude)       │
  │  2. OpenAI (GPT-4)          │
  │  3. Local Template Fallback │
  └───────────┬─────────────────┘
              │
              ▼
  ┌──────────────────────┐
  │  Code Extraction      │  →  Strip markdown fences
  │  Tool Extraction      │  →  Regex @mcp.tool() / def names
  └───────────┬──────────┘
              │
              ▼
  ┌──────────────────────┐
  │  Port Discovery       │  →  Find available port in range 8200-8299
  └───────────┬──────────┘
              │
              ▼
  ┌──────────────────────┐
  │  Launch Subprocess    │  →  Spawn server, wait 2s for startup
  └───────────┬──────────┘
              │
              ▼
  ┌──────────────────────┐
  │  Register in Catalog  │  →  Add to REGISTRY, persist to disk
  └───────────┬──────────┘
              │
              ▼
         Return success
         (server_name, port, tools, provider, logs)
```

Generated servers run as **subprocesses** (not Docker containers) on dynamically allocated ports. Each gets a `FUSIONAL_GENERATED_SERVER` environment variable for identification.

---

## 6. Deployment Architecture

### Native (Direct)

```bash
python -m uvicorn core.main:app --reload --port 8009
```

Ports: 8009 (gateway), 8101-8107 (showcase servers), 8200-8299 (generated servers)

### Docker (Production)

**`Dockerfile`**:
- Base: `python:3.12-slim`
- Non-root user `appuser` (uid 5678)
- Runs `uvicorn core.main:app` on port 8009
- Supports `--forwarded-allow-ips *` for reverse proxy deployments

**`compose.yaml`**:
- Builds from `./Dockerfile`
- Maps host `127.0.0.1:8089` to container `8009`
- Connects to external `mcp-consulting-kit_default` network (`mcp-kit`) for showcase server discovery via Docker DNS
- Adds `host.docker.internal:host-gateway` for reaching host-network services (e.g., `fusional-recall`, `kb-server`)

```
Host :8089  →  Container :8009  →  Proxy to mcp-kit servers (via Docker DNS)
                                  →  Proxy to host services (via host.docker.internal)
```

### Debug Mode

**`compose.debug.yaml`**: Adds debugpy on port 5678 for remote Python debugging with `--wait-for-client`.

---

## 7. Data Flow

### Tool Call (Client → FusionAL → Downstream)

```
  Client (Claude Desktop)
       │
       │  POST /mcp  (Streamable HTTP)
       │  { tool: "bi_nl_query", args: { query: "..." } }
       ▼
  ┌──────────────────────────────────┐
  │  FusionAL Gateway                 │
  │                                  │
  │  1. Security: verify_api_key()    │
  │  2. Rate Limit: enforce_rate()   │
  │  3. Proxy: look up bi_ →         │
  │     business-intelligence-mcp     │
  │  4. Connect to internal_url/mcp   │
  │  5. Call tool "nl_query"           │
  │  6. Record audit trail            │
  │  7. Return result to client       │
  └──────────────────────────────────┘
       │
       ▼
  business-intelligence-mcp (:8101)
       │
       ▼
  PostgreSQL / MySQL / SQLite
```

### Code Execution (Client → FusionAL → Sandbox)

```
  Client
       │
       │  POST /execute { code, use_docker: true }
       ▼
  ┌──────────────────────────────────┐
  │  FusionAL                         │
  │                                  │
  │  ┌─ Without Docker:              │
  │  │   subprocess.run(python)      │
  │  │                              │
  │  └─ With Docker:                 │
  │      docker run --rm             │
  │        --network none            │
  │        --memory=128m             │
  │        --pids-limit 64           │
  │        --cap-drop ALL            │
  │        --read-only               │
  │        python:3.11-slim          │
  │        python script.py          │
  └──────────────────────────────────┘
```

---

## 8. Environment Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8009` | FastAPI server port |
| `ANTHROPIC_API_KEY` | — | Claude API key for AI generation |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-20241022` | Claude model name |
| `OPENAI_API_KEY` | — | OpenAI API key for AI generation |
| `OPENAI_MODEL` | `gpt-4-turbo` | OpenAI model name |
| `API_KEY` / `API_KEYS` | — | API key(s) for gateway auth (comma-separated) |
| `REVOKED_API_KEYS` | — | Keys to immediately revoke |
| `RATE_LIMIT_REQUESTS` | `60` | Max requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window |
| `ALLOWED_ORIGINS` | `http://localhost,http://127.0.0.1` | CORS allowed origins |
| `REDIS_URL` | — | Redis for rate limiting (optional) |
| `OTLP_ENDPOINT` | — | OpenTelemetry OTLP endpoint |
| `TRACING_ENABLED` | `true` | Enable/disable distributed tracing |
| `SERVICE_NAME` | App title | Service name for traces & logs |
| `AUDIT_MAX_RECORDS` | `10000` | Max in-memory audit records |
| `AUDIT_STORE_PATH` | — | File path for NDJSON audit persistence |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_HEALTH_REQUESTS` | `false` | Log health check requests |
| `HTTP_REQUEST_TIMEOUT_SECONDS` | `30` | HTTP request timeout for AI API calls |

---

## 9. Scripts & Supporting Tools

### Watchdog (`scripts/watchdog.py`)
- Monitors MCP servers by polling `/health` every 30 seconds
- **Budget-gated auto-restart**: max 3 restarts per hour per server
- Escalates to **Think Tank** (AI-driven diagnosis) when restart budget is exhausted
- Logs all faults to `logs/fault_log.json` for post-mortem analysis
- Distinguishes **critical** servers (FusionAL itself) from non-critical

### Think Tank (`scripts/think_tank.py`, `scripts/think_tank_trigger.py`)
- AI-driven fault diagnosis and action planning
- Triggered by watchdog when automatic recovery fails
- Runs in a background thread — non-blocking
- Can escalate to human operators

### Notion Reporter (`scripts/notion_reporter.py`)
- Reports system status and audit data to Notion workspaces
- Integration point for operational dashboards

---

## Key Design Decisions

1. **Single entry point**: Clients connect to one endpoint; FusionAL handles routing — simplifies client configuration and centralizes policy.

2. **Graceful degradation**: Every optional module (security, tracing, audit, Docker runner) has a no-op fallback — the gateway starts even with partial configuration.

3. **Namespaced proxy tools**: Prevents name collisions between downstream servers — each tool is prefixed with its server's namespace (e.g., `bi_nl_query`).

4. **Ring-buffer audit**: Bounded memory usage regardless of deployment duration — configurable max records with optional file persistence.

5. **Cascading AI providers**: Falls back through Claude → OpenAI → local template, ensuring generation works even without API keys.

6. **Dual-URL registry**: Servers are reachable both from Docker bridge networks (`internal_url`) and host networking (`native_url`), adapting to the deployment context.

7. **Windows hardening**: Six documented Windows MCP failure modes addressed in the gateway's design, including BOM traps, path separator issues, and Docker named pipe compatibility.
