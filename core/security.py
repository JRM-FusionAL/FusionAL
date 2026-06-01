"""
Shared security module for MCP Consulting Kit servers.
Provides API key authentication, rate limiting, CORS, and observability.
"""

import os
import time
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

# ── API Key Auth ─────────────────────────────────────────────────────────────

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def _get_valid_keys() -> set:
    keys = set()
    single = os.getenv("API_KEY", "").strip()
    if single:
        keys.add(single)
    multi = os.getenv("API_KEYS", "").strip()
    if multi:
        keys.update(k.strip() for k in multi.split(",") if k.strip())
    return keys

def _get_revoked_keys() -> set:
    revoked = os.getenv("REVOKED_API_KEYS", "").strip()
    if not revoked:
        return set()
    return {k.strip() for k in revoked.split(",") if k.strip()}

async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)):
    valid_keys = _get_valid_keys()
    if not valid_keys:
        return  # No keys configured — open access (dev mode)
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    revoked = _get_revoked_keys()
    if api_key in revoked:
        raise HTTPException(status_code=401, detail="API key has been revoked")
    if api_key not in valid_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ── Rate Limiting ─────────────────────────────────────────────────────────────

_rate_limit_store: dict = {}

def initialize_rate_limit_store(app: FastAPI):
    app.state.rate_limit_store = {}

async def enforce_rate_limit(request: Request):
    store = getattr(request.app.state, "rate_limit_store", _rate_limit_store)
    limit = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
    window = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    record = store.get(client_ip, {"count": 0, "window_start": now})
    if now - record["window_start"] > window:
        record = {"count": 0, "window_start": now}
    record["count"] += 1
    store[client_ip] = record
    if record["count"] > limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

# ── CORS ──────────────────────────────────────────────────────────────────────

def configure_cors(app: FastAPI):
    origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1")
    origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ── Observability ─────────────────────────────────────────────────────────────

class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response: Response = await call_next(request)
        duration_ms = (time.time() - start) * 1000
        log_health = os.getenv("LOG_HEALTH_REQUESTS", "false").lower() == "true"
        if request.url.path == "/health" and not log_health:
            return response
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

def configure_observability(app: FastAPI):
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app.add_middleware(ObservabilityMiddleware)
