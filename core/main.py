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
import shutil
import subprocess  # nosec B404
import tempfile
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
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

# --- Docker runner ---
try:
    from runner_docker import run_in_docker
except Exception:
    run_in_docker = None

# --- MCP transport ---
from .mcp_transport import mcp


@asynccontextmanager
async def _lifespan(app):
    app.state._mcp_session_context = mcp.session_manager.run()
    await app.state._mcp_session_context.__aenter__()
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


def _auth():
    pass

def _rate():
    pass

if _SECURITY_ENABLED:
    _auth = verify_api_key
    _rate = enforce_rate_limit


# ── Models ────────────────────────────────────────────────────────────────────

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


# ── Registry ──────────────────────────────────────────────────────────────────

REGISTRY: dict = {}
REGISTRY_FILE = os.path.join(os.getcwd(), "mcp_registry.json")

_SHOWCASE_SERVERS = {
    "business-intelligence-mcp": {
        "description": "Natural language → SQL queries against PostgreSQL/MySQL/SQLite",
        "url": "http://localhost:8101",
        "metadata": {"version": "0.3.0", "tools": ["nl-query"], "port": 8101, "source": "mcp-consulting-kit"},
        "registered_at": "2026-02-23T00:00:00"
    },
    "api-integration-hub": {
        "description": "Slack, GitHub, and Stripe integrations via natural language",
        "url": "http://localhost:8102",
        "metadata": {"version": "0.3.0", "tools": ["slack/send", "github/create-issue", "stripe/customer"], "port": 8102, "source": "mcp-consulting-kit"},
        "registered_at": "2026-02-23T00:00:00"
    },
    "content-automation-mcp": {
        "description": "Web scraping, link extraction, table parsing, and RSS feeds",
        "url": "http://localhost:8103",
        "metadata": {"version": "0.3.0", "tools": ["scrape/article", "scrape/links", "scrape/tables", "rss/parse"], "port": 8103, "source": "mcp-consulting-kit"},
        "registered_at": "2026-02-23T00:00:00"
    }
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

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
