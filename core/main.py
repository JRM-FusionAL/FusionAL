"""
FusionAL - FastAPI MCP Execution Server

Core execution engine for MCP servers with Docker sandboxing support.
Provides REST APIs for code execution, MCP server registration, and catalog management.

Security: API key auth + rate limiting via shared common/security.py
         (sourced from mcp-consulting-kit/showcase-servers/common/)
"""

import os
import sys
import json
import logging
import re
import socket
import shutil
import subprocess  # nosec B404
import tempfile
import time
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

PORT = int(os.getenv("PORT", "8009"))
LOGGER = logging.getLogger("fusional.main")

# --- Security module: cross-platform path resolution ---
_this_file = Path(__file__).resolve()
_SECURITY_CANDIDATES = [
    _this_file.parent / "common",
    Path.home() / "Projects" / "mcp-consulting-kit" / "showcase-servers" / "common",
    Path.home() / "projects" / "mcp-consulting-kit" / "showcase-servers" / "common",
    Path.home() / "mcp-consulting-kit" / "showcase-servers" / "common",
]

if len(_this_file.parents) > 2:
    _SECURITY_CANDIDATES.append(
        _this_file.parents[2] / "mcp-consulting-kit" / "showcase-servers" / "common"
    )

if len(_this_file.parents) > 3:
    _SECURITY_CANDIDATES.append(
        _this_file.parents[3] / "mcp-consulting-kit" / "showcase-servers" / "common"
    )

for _candidate in _SECURITY_CANDIDATES:
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
        break

try:
    from security import (
        configure_cors,
        configure_observability,
        enforce_rate_limit,
        initialize_rate_limit_store,
        verify_api_key,
    )
    _SECURITY_ENABLED = True
except ImportError:
    _SECURITY_ENABLED = False

try:
    from tracing import configure_tracing
    _TRACING_IMPORTABLE = True
except ImportError:
    _TRACING_IMPORTABLE = False

try:
    from audit import get_audit_store, record_tool_call, records_to_json, records_to_csv
    _AUDIT_ENABLED = True
except ImportError:
    _AUDIT_ENABLED = False

# --- Docker runner ---
try:
    from runner_docker import run_in_docker
except Exception:
    run_in_docker = None

# --- MCP transport + aggregating proxy ---
from .mcp_transport import mcp, register_downstream_tools, set_audit_hook
from .ai_agent import generate_python_from_claude, generate_python_from_openai

# Wire the audit hook so proxied tool calls are recorded
if _AUDIT_ENABLED:
    set_audit_hook(record_tool_call)


@asynccontextmanager
async def _lifespan(app):
    # Start MCP session manager
    app.state._mcp_session_context = mcp.session_manager.run()
    await app.state._mcp_session_context.__aenter__()

    # Register downstream tools (failures are logged but non-fatal)
    try:
        await register_downstream_tools(REGISTRY)
    except Exception as exc:
        LOGGER.warning("proxy.register_failed error=%s", exc)

    yield

    ctx = getattr(app.state, "_mcp_session_context", None)
    if ctx is not None:
        await ctx.__aexit__(None, None, None)


# --- App ---
app = FastAPI(
    title="FusionAL - MCP Execution Server",
    description="AI-powered MCP server builder and executor with Docker sandboxing",
    version="1.0.0",
    lifespan=_lifespan,
)

if _SECURITY_ENABLED:
    configure_cors(app)
    configure_observability(app)
    initialize_rate_limit_store(app)

if _TRACING_IMPORTABLE:
    configure_tracing(app)

mcp.settings.streamable_http_path = "/"
mcp_app = mcp.streamable_http_app()
app.mount("/mcp", mcp_app)
from fastapi.staticfiles import StaticFiles
app.mount("/.well-known", StaticFiles(directory="/app/well-known"), name="well-known")


def _auth():
    pass


def _rate():
    pass


if _SECURITY_ENABLED:
    _auth = verify_api_key
    _rate = enforce_rate_limit


# ── Models ──────────────────────────────────────────────────────────────────

class ExecRequest(BaseModel):
    language: str = "python"
    code: str
    timeout: int = 5
    use_docker: Optional[bool] = False
    memory_mb: Optional[int] = 128


class RegisterRequest(BaseModel):
    name: str
    description: Optional[str] = None
    url: Optional[str] = None
    metadata: Optional[dict] = None


class GenerateRequest(BaseModel):
    prompt: str
    sandbox: bool = True


# ── Registry ────────────────────────────────────────────────────────────────

REGISTRY: dict = {}
REGISTRY_FILE = os.path.join(os.getcwd(), "mcp_registry.json")

# Showcase servers: `url` is the external/catalog URL; `internal_url` is used
# by the aggregating proxy when connecting from inside the Docker network.
_SHOWCASE_SERVERS = {
    "business-intelligence-mcp": {
        "description": "Natural language → SQL queries against PostgreSQL/MySQL/SQLite",
        "url": "http://localhost:8101",
        "internal_url": "http://business-intelligence-mcp:8101",
        "metadata": {"version": "0.3.0", "tools": ["nl_query"], "port": 8101, "source": "mcp-consulting-kit"},
        "registered_at": "2026-02-23T00:00:00"
    },
    "api-integration-hub": {
        "description": "Slack, GitHub, and Stripe integrations via natural language",
        "url": "http://localhost:8102",
        "internal_url": "http://api-integration-hub:8102",
        "metadata": {"version": "0.3.0", "tools": ["slack/send", "github/create-issue", "stripe/customer"], "port": 8102, "source": "mcp-consulting-kit"},
        "registered_at": "2026-02-23T00:00:00"
    },
    "content-automation-mcp": {
        "description": "Web scraping, link extraction, table parsing, and RSS feeds",
        "url": "http://localhost:8103",
        "internal_url": "http://content-automation-mcp:8103",
        "metadata": {"version": "0.3.0", "tools": ["scrape/article", "scrape/links", "scrape/tables", "rss/parse"], "port": 8103, "source": "mcp-consulting-kit"},
        "registered_at": "2026-02-23T00:00:00"
    },
    "github-mcp-safe": {
        "description": "Safe GitHub API operations (list issues, create issue, search code)",
        "url": "http://localhost:8105",
        "internal_url": "http://github-mcp-safe:8105",
        "metadata": {"version": "0.3.0", "tools": ["github_list_issues", "github_create_issue"], "port": 8105, "source": "mcp-consulting-kit"},
        "registered_at": "2026-02-23T00:00:00"
    },
    "intelligence-mcp": {
        "description": "Intelligence and research tools",
        "url": "http://localhost:8104",
        "internal_url": "http://intelligence-mcp:8104",
        "metadata": {"version": "0.3.0", "tools": [], "port": 8104, "source": "mcp-consulting-kit"},
        "registered_at": "2026-02-23T00:00:00"
    },
    # Host-network services (systemd, not Docker) — reachable via host.docker.internal
    "fusional-recall": {
        "description": "Semantic recall and solved-issues memory search",
        "url": "http://localhost:8107",
        "internal_url": "http://host.docker.internal:8107",
        "metadata": {"version": "0.1.0", "tools": ["recall"], "port": 8107, "source": "fusional"},
        "registered_at": "2026-05-31T00:00:00"
    },
    "kb-server": {
        "description": "FusionAL knowledge base search",
        "url": "http://localhost:8106",
        "internal_url": "http://host.docker.internal:8108",
        "metadata": {"version": "0.1.0", "tools": ["search"], "port": 8106, "source": "fusional"},
        "registered_at": "2026-05-31T00:00:00"
    },
}


def _load_registry():
    global REGISTRY
    REGISTRY.update(_SHOWCASE_SERVERS)
    try:
        if os.path.exists(REGISTRY_FILE):
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                REGISTRY.update(json.load(f))
    except Exception as exc:
        LOGGER.warning("Failed loading registry file %s: %s", REGISTRY_FILE, exc)


def _save_registry():
    try:
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(REGISTRY, f, indent=2)
    except Exception as exc:
        LOGGER.warning("Failed saving registry file %s: %s", REGISTRY_FILE, exc)


_load_registry()


def _slugify_server_name(prompt: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")
    if not slug:
        slug = "generated-server"
    if not slug.endswith("-mcp"):
        slug = f"{slug}-mcp"
    return slug[:80]


def _find_available_port(start: int = 8200, end: int = 8299) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            in_use = sock.connect_ex(("127.0.0.1", port)) == 0
            if not in_use:
                return port
    raise RuntimeError(f"No available ports in range {start}-{end}")


def _extract_tools_from_code(code: str) -> List[str]:
    tools: List[str] = []
    for match in re.finditer(r"@mcp\\.tool\\((.*?)\\)", code, flags=re.DOTALL):
        args_text = match.group(1)
        name_match = re.search(r"name\\s*=\\s*[\"']([^\"']+)[\"']", args_text)
        if name_match:
            tools.append(name_match.group(1))

    if tools:
        return sorted(set(tools))

    for match in re.finditer(r"def\\s+([a-zA-Z_][a-zA-Z0-9_]*)\\s*\\(", code):
        fn_name = match.group(1)
        if not fn_name.startswith("_"):
            tools.append(fn_name)

    return sorted(set(tools))[:20]


def _generate_local_server_code(server_name: str, user_request: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", server_name)[:48] or "generated_mcp"
    escaped_request = user_request.replace('"', '\\"')
    return f'''"""Auto-generated local MCP server fallback for {server_name}."""

import os
from datetime import datetime

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
import uvicorn

mcp = FastMCP("{safe_name}", streamable_http_path="/")


@mcp.tool(name="ping", description="Health-check tool that returns pong with context")
def ping() -> dict:
    return {{"message": "pong", "server": "{server_name}", "request": "{escaped_request}"}}


@mcp.tool(name="echo", description="Echoes back provided text")
def echo(text: str) -> dict:
    return {{"echo": text, "server": "{server_name}"}}


app = FastAPI(title="{server_name}")


@app.get("/health")
async def health() -> dict:
    return {{"status": "ok", "server": "{server_name}", "timestamp": datetime.utcnow().isoformat()}}


app.mount("/mcp", mcp.streamable_http_app())


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8200"))
    uvicorn.run(app, host="0.0.0.0", port=port)
'''


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "FusionAL MCP Server", "security_enabled": _SECURITY_ENABLED, "timestamp": datetime.utcnow().isoformat()}


@app.post("/execute")
async def execute(req: ExecRequest, _auth_dep=Depends(_auth), _rate_dep=Depends(_rate)):
    if req.language != "python":
        raise HTTPException(status_code=400, detail="Only 'python' language supported")

    if req.use_docker:
        if run_in_docker is None:
            raise HTTPException(status_code=500, detail="Docker runner not available on server")
        try:
            return run_in_docker(req.code, timeout=req.timeout, memory_mb=req.memory_mb)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Execution timed out")
        except subprocess.CalledProcessError as e:
            return {"stdout": e.stdout, "stderr": e.stderr, "returncode": e.returncode}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    tmpdir = tempfile.mkdtemp(prefix="fusional-")
    script_path = os.path.join(tmpdir, "script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(req.code)
    try:
        proc = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=req.timeout)  # nosec B603
        return {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Execution timed out")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/register")
async def register(req: RegisterRequest, _auth_dep=Depends(_auth), _rate_dep=Depends(_rate)):
    if req.name in REGISTRY:
        raise HTTPException(status_code=400, detail=f"Server '{req.name}' already registered")
    REGISTRY[req.name] = {"description": req.description, "url": req.url, "metadata": req.metadata or {}, "registered_at": datetime.utcnow().isoformat()}
    _save_registry()
    return {"status": "registered", "name": req.name, "timestamp": datetime.utcnow().isoformat()}


@app.get("/catalog")
async def catalog():
    return {"total": len(REGISTRY), "servers": REGISTRY, "timestamp": datetime.utcnow().isoformat()}


@app.post("/generate")
async def generate(req: GenerateRequest, _auth_dep=Depends(_auth), _rate_dep=Depends(_rate)):
    try:
        server_name = _slugify_server_name(req.prompt)
        if server_name in REGISTRY:
            server_name = f"{server_name}-{int(time.time())}"

        generation_prompt = (
            "Generate complete Python MCP server code in one file. "
            "Requirements: use FastMCP streamable HTTP transport mounted at /mcp, expose GET /health, "
            "read port from PORT env var with default 8200, and include at least one useful tool. "
            "Return only valid Python code with no markdown fences.\n\n"
            f"Server name: {server_name}\n"
            f"User request: {req.prompt}"
        )

        generated_code = None
        provider_used = "local"
        provider_errors: List[str] = []

        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                generated_code = generate_python_from_claude(generation_prompt)
                provider_used = "anthropic"
            except Exception as exc:
                provider_errors.append(f"anthropic: {exc}")

        if generated_code is None and os.getenv("OPENAI_API_KEY"):
            try:
                generated_code = generate_python_from_openai(generation_prompt)
                provider_used = "openai"
            except Exception as exc:
                provider_errors.append(f"openai: {exc}")

        if generated_code is None:
            generated_code = _generate_local_server_code(server_name, req.prompt)
            if provider_errors:
                LOGGER.warning(
                    "AI provider generation failed, falling back to local template: %s",
                    " | ".join(provider_errors),
                )

        generated_code = generated_code.strip()
        if generated_code.startswith("```"):
            generated_code = re.sub(r"^```[a-zA-Z]*\\n", "", generated_code)
            generated_code = re.sub(r"\\n```$", "", generated_code)

        tools = _extract_tools_from_code(generated_code)
        port = _find_available_port(8200, 8299)

        tmpdir = tempfile.mkdtemp(prefix=f"{server_name}-")
        script_path = os.path.join(tmpdir, "generated_server.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(generated_code)

        env = os.environ.copy()
        env["PORT"] = str(port)
        env["FUSIONAL_GENERATED_SERVER"] = server_name

        proc = subprocess.Popen(  # nosec B603
            [sys.executable, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=tmpdir,
        )

        time.sleep(2)
        startup_logs = ""
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=2)
            startup_logs = (out or "") + ("\n" + err if err else "")
            raise RuntimeError(f"Generated server exited early with code {proc.returncode}. {startup_logs}")

        startup_logs = f"Generated server started with PID {proc.pid} on port {port}"

        REGISTRY[server_name] = {
            "description": req.prompt,
            "url": f"http://localhost:{port}",
            "metadata": {
                "tools": tools,
                "port": port,
                "pid": proc.pid,
                "sandbox": req.sandbox,
                "source": "generated",
                "script_path": script_path,
            },
            "registered_at": datetime.utcnow().isoformat(),
        }
        _save_registry()

        return {
            "status": "success",
            "server_name": server_name,
            "port": port,
            "tools": tools,
            "provider": provider_used,
            "logs": startup_logs,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ── Audit Export Endpoints ───────────────────────────────────────────────────

@app.get("/audit/export/json")
async def audit_export_json(
    start: Optional[str] = None,
    end: Optional[str] = None,
    _auth_dep=Depends(_auth),
):
    """Export tool-call audit records as JSON.

    Query parameters:
        start: ISO 8601 UTC datetime (inclusive lower bound, optional)
        end:   ISO 8601 UTC datetime (inclusive upper bound, optional)
    """
    if not _AUDIT_ENABLED:
        raise HTTPException(status_code=503, detail="Audit module not available")

    start_dt = _parse_export_datetime(start, "start")
    end_dt = _parse_export_datetime(end, "end")

    store = get_audit_store()
    records = store.query(start=start_dt, end=end_dt)
    body = records_to_json(records)
    return StreamingResponse(
        iter([body]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=audit_export.json"},
    )


@app.get("/audit/export/csv")
async def audit_export_csv(
    start: Optional[str] = None,
    end: Optional[str] = None,
    _auth_dep=Depends(_auth),
):
    """Export tool-call audit records as CSV.

    Query parameters:
        start: ISO 8601 UTC datetime (inclusive lower bound, optional)
        end:   ISO 8601 UTC datetime (inclusive upper bound, optional)
    """
    if not _AUDIT_ENABLED:
        raise HTTPException(status_code=503, detail="Audit module not available")

    start_dt = _parse_export_datetime(start, "start")
    end_dt = _parse_export_datetime(end, "end")

    store = get_audit_store()
    records = store.query(start=start_dt, end=end_dt)
    body = records_to_csv(records)
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_export.csv"},
    )


def _parse_export_datetime(value: Optional[str], param_name: str) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid '{param_name}' datetime format. Use ISO 8601, e.g. 2026-01-01T00:00:00Z",
        )
