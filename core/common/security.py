import os
import time
import json
import uuid
import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

try:
    import redis  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - exercised in environments without redis installed
    redis = None

LOGGER_NAME = "mcp.observability"
REQUEST_ID_HEADER = "X-Request-ID"
SENSITIVE_FIELD_MARKER = "***REDACTED***"
DEFAULT_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
}


def get_allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return _validate_cors_origins(origins)


def _validate_cors_origins(origins: list[str]) -> list[str]:
    """Validate CORS origins: reject wildcards and invalid formats (SEC-04)."""
    validated = []
    for origin in origins:
        if "*" in origin:
            _get_or_create_logger().warning("cors.invalid_origin_wildcard rejected=%s", origin)
            continue
        if not origin.startswith(("http://", "https://")):
            _get_or_create_logger().warning("cors.invalid_origin_scheme rejected=%s", origin)
            continue
        validated.append(origin)
    return validated


def get_rate_limit() -> tuple[int, int]:
    requests = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
    window_seconds = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    return requests, window_seconds


def get_log_level() -> str:
    return os.getenv("LOG_LEVEL", "INFO").upper()


def get_redis_url() -> str | None:
    value = os.getenv("REDIS_URL", "").strip()
    return value or None


def should_log_health_requests() -> bool:
    return os.getenv("LOG_HEALTH_REQUESTS", "false").strip().lower() == "true"


def _sanitize_request_id(request_id: str | None) -> str:
    """Sanitize and validate inbound request ID (SEC-06)."""
    if not request_id:
        return str(uuid.uuid4())

    sanitized = str(request_id)[:64]
    if not sanitized or not all(c.isalnum() or c in "-_" for c in sanitized):
        _get_or_create_logger().warning("request_id.invalid_format rejected=%s", request_id)
        return str(uuid.uuid4())

    return sanitized


def _get_security_headers() -> dict[str, str]:
    """Return baseline security headers (SEC-07)."""
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'",
    }


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("_", "-")
    return normalized in DEFAULT_SENSITIVE_KEYS or any(
        token in normalized for token in ("token", "secret", "password", "api-key")
    )


def _mask_secret(value: Any) -> str:
    text = str(value)
    if not text:
        # Preserve empty/None semantics without introducing a marker
        return text
    # For any non-empty sensitive value, return a constant marker so that
    # no part of the original secret (prefix, suffix, or exact length)
    # is exposed in logs.
    return SENSITIVE_FIELD_MARKER


def redact_sensitive_data(value: Any, key_name: str | None = None) -> Any:
    if key_name and _is_sensitive_key(key_name):
        return _mask_secret(value)

    if isinstance(value, dict):
        return {key: redact_sensitive_data(item, key_name=key) for key, item in value.items()}

    if isinstance(value, list):
        return [redact_sensitive_data(item, key_name=key_name) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item, key_name=key_name) for item in value)

    return value


def _resolve_service_name(app: FastAPI) -> str:
    return os.getenv("SERVICE_NAME", app.title)


def _get_or_create_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(get_log_level())
    logger.propagate = True
    return logger


def _build_log_payload(
    request: Request,
    request_id: str,
    status_code: int,
    duration_ms: float,
    service_name: str,
) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")
    redacted_headers = redact_sensitive_data(dict(request.headers))
    return {
        "event": "http_request",
        "service": service_name,
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 2),
        "client_ip": client_ip,
        "user_agent": user_agent,
        "headers": redacted_headers,
    }


def configure_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )


def configure_observability(app: FastAPI) -> None:
    logger = _get_or_create_logger()
    service_name = _resolve_service_name(app)
    security_headers = _get_security_headers()

    @app.middleware("http")
    async def observability_middleware(request: Request, call_next):
        request_id = _sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id

        start = time.perf_counter()
        status_code = 500
        response: Response | None = None

        try:
            response = await call_next(request)
            if response is None:
                raise RuntimeError("call_next returned no response")
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            for header_name, header_value in security_headers.items():
                response.headers[header_name] = header_value
            return response
        finally:
            if request.url.path != "/health" or should_log_health_requests():
                duration_ms = (time.perf_counter() - start) * 1000
                payload = _build_log_payload(
                    request=request,
                    request_id=request_id,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    service_name=service_name,
                )
                logger.info(json.dumps(payload, separators=(",", ":")))


def initialize_rate_limit_store(app: FastAPI) -> None:
    app.state.rate_limit_store = {}
    app.state.redis_client = _create_redis_client()
    app.state.redis_degraded = False
    app.state.revoked_api_keys = set()


def _create_redis_client():
    redis_url = get_redis_url()
    if not redis_url or redis is None:
        return None

    client = redis.from_url(redis_url, decode_responses=True)
    client.ping()
    return client


def _load_active_api_keys() -> list[str]:
    raw_keys = os.getenv("API_KEYS", "")
    keys = [item.strip() for item in raw_keys.split(",") if item.strip()]

    if keys:
        return keys

    fallback = os.getenv("API_KEY", "").strip()
    return [fallback] if fallback else []


def _load_revoked_api_keys() -> set[str]:
    raw_revoked = os.getenv("REVOKED_API_KEYS", "")
    return {item.strip() for item in raw_revoked.split(",") if item.strip()}


def revoke_api_key(app: FastAPI, api_key: str) -> None:
    if not api_key:
        return
    app.state.revoked_api_keys.add(api_key)


def verify_api_key(request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    active_api_keys = _load_active_api_keys()
    if not active_api_keys:
        raise HTTPException(status_code=500, detail="API_KEY is not configured")

    revoked_api_keys = set(_load_revoked_api_keys())
    runtime_revoked = getattr(request.app.state, "revoked_api_keys", set())
    revoked_api_keys.update(runtime_revoked)

    if not x_api_key or x_api_key in revoked_api_keys or x_api_key not in active_api_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _enforce_rate_limit_with_redis(request: Request, limit: int, window: int) -> bool:
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is None:
        return False

    client_ip = request.client.host if request.client else "unknown"
    key = f"rate_limit:{client_ip}:{request.url.path}"

    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, window)
        request.app.state.redis_degraded = False
    except Exception:
        request.app.state.redis_degraded = True
        _get_or_create_logger().warning(
            "rate_limit.redis_unavailable fallback=in_memory path=%s",
            request.url.path,
        )
        return False

    if count > limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return True


def enforce_rate_limit(request: Request) -> None:
    limit, window = get_rate_limit()
    now = time.time()

    if _enforce_rate_limit_with_redis(request, limit=limit, window=window):
        return

    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{request.url.path}"

    bucket = request.app.state.rate_limit_store.get(key)
    if not bucket or now >= bucket["reset_at"]:
        request.app.state.rate_limit_store[key] = {"count": 1, "reset_at": now + window}
        return

    if bucket["count"] >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    bucket["count"] += 1
