"""
middleware/auth.py
Tenant authentication middleware for the FusionAL gateway.

Intercepts every request, extracts X-API-Key + X-Tenant-ID headers,
and validates against the key store before passing to route handlers.

Usage (in main.py / gateway entrypoint):
    from middleware.auth import TenantAuthMiddleware
    app.add_middleware(TenantAuthMiddleware)

Or as a FastAPI dependency (per-route):
    from middleware.auth import require_tenant
    @app.get("/tools", dependencies=[Depends(require_tenant)])
"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from services.key_manager import validate_key

logger = logging.getLogger("fusional.auth")


def _s(value: str) -> str:
    """Sanitize user-controlled strings before logging to prevent log injection."""
    return value.replace("\r", "\\r").replace("\n", "\\n")

# ---------------------------------------------------------------------------
# Paths that bypass auth (health checks, docs)
# ---------------------------------------------------------------------------
EXEMPT_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


# ---------------------------------------------------------------------------
# Middleware (applies to all routes)
# ---------------------------------------------------------------------------

class TenantAuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette/FastAPI middleware that enforces tenant-scoped API key auth.

    Attaches `request.state.tenant_id` for use in route handlers.
    Returns 401/403 JSON responses on failure — never leaks key details.
    """

    def __init__(self, app: ASGIApp, exempt_paths: Optional[set] = None):
        super().__init__(app)
        self.exempt_paths = exempt_paths or EXEMPT_PATHS

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.exempt_paths:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key", "").strip()
        tenant_id = request.headers.get("X-Tenant-ID", "").strip()

        if not api_key or not tenant_id:
            logger.warning(
                "auth: missing credentials path=%s ip=%s",
                _s(request.url.path),
                _s(request.client.host) if request.client else "unknown",
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "Missing X-API-Key or X-Tenant-ID header"},
            )

        if not validate_key(api_key, tenant_id):
            logger.warning(
                "auth: invalid/revoked key tenant=%s path=%s ip=%s",
                _s(tenant_id),
                _s(request.url.path),
                _s(request.client.host) if request.client else "unknown",
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": "Invalid or revoked API key"},
            )

        # Attach tenant to request state for downstream handlers
        request.state.tenant_id = tenant_id
        return await call_next(request)


# ---------------------------------------------------------------------------
# Dependency (per-route alternative)
# ---------------------------------------------------------------------------

async def require_tenant(request: Request) -> str:
    """
    FastAPI dependency that validates tenant auth and returns the tenant_id.

    Usage:
        @app.get("/tools")
        async def list_tools(tenant_id: str = Depends(require_tenant)):
            ...
    """
    api_key = request.headers.get("X-API-Key", "").strip()
    tenant_id = request.headers.get("X-Tenant-ID", "").strip()

    if not api_key or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key or X-Tenant-ID header",
        )

    if not validate_key(api_key, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked API key",
        )

    request.state.tenant_id = tenant_id
    return tenant_id
