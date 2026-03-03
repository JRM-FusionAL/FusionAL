"""
Distributed tracing for MCP servers using OpenTelemetry.

Configuration via environment variables:
  OTLP_ENDPOINT   - OTLP HTTP endpoint (e.g. http://localhost:4318)
                    Leave unset to use console exporter (dev mode).
  SERVICE_NAME    - Service name reported to the tracing backend.
  TRACING_ENABLED - Set to "false" to disable entirely (default: true).

Usage:
    from tracing import configure_tracing, get_trace_context
    configure_tracing(app)          # call once at startup
    ctx = get_trace_context()       # {"trace_id": "...", "span_id": "..."}
"""

import os
import logging

_TRACING_AVAILABLE = False
_tracer_provider = None

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME as RESOURCE_SERVICE_NAME
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        _OTLP_AVAILABLE = True
    except ImportError:
        _OTLP_AVAILABLE = False

    _TRACING_AVAILABLE = True
except ImportError:
    _TRACING_AVAILABLE = False
    _OTLP_AVAILABLE = False

logger = logging.getLogger("mcp.tracing")


def _is_tracing_enabled() -> bool:
    return os.getenv("TRACING_ENABLED", "true").strip().lower() != "false"


def configure_tracing(app, service_name: str | None = None) -> None:
    """
    Initialize OpenTelemetry tracing and instrument the FastAPI app.

    If opentelemetry packages are not installed, this is a no-op with a warning.
    """
    global _tracer_provider

    if not _TRACING_AVAILABLE:
        logger.warning(
            "tracing.unavailable reason='opentelemetry packages not installed' "
            "hint='pip install opentelemetry-sdk opentelemetry-instrumentation-fastapi'"
        )
        return

    if not _is_tracing_enabled():
        logger.info("tracing.disabled reason='TRACING_ENABLED=false'")
        return

    resolved_name = service_name or os.getenv("SERVICE_NAME", getattr(app, "title", "mcp-server"))
    resource = Resource.create({RESOURCE_SERVICE_NAME: resolved_name})
    provider = TracerProvider(resource=resource)

    otlp_endpoint = os.getenv("OTLP_ENDPOINT", "").strip()
    if otlp_endpoint and _OTLP_AVAILABLE:
        exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("tracing.configured exporter=otlp endpoint=%s service=%s", otlp_endpoint, resolved_name)
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info(
            "tracing.configured exporter=console service=%s "
            "hint='Set OTLP_ENDPOINT to ship traces to Jaeger/Tempo/Zipkin'",
            resolved_name,
        )

    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    logger.info("tracing.fastapi_instrumented service=%s", resolved_name)


def get_trace_context() -> dict:
    """
    Return current trace_id and span_id as hex strings.

    Returns empty strings when tracing is not active (safe to include in logs).
    """
    if not _TRACING_AVAILABLE:
        return {"trace_id": "", "span_id": ""}

    span = trace.get_current_span()
    ctx = span.get_span_context()

    if not ctx or not ctx.is_valid:
        return {"trace_id": "", "span_id": ""}

    return {
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
    }


def get_tracer(name: str = "mcp"):
    """
    Return an OpenTelemetry Tracer for manual instrumentation.

    Returns a no-op tracer when tracing is unavailable.
    """
    if not _TRACING_AVAILABLE or not _is_tracing_enabled():
        return _NoopTracer()

    return trace.get_tracer(name)


class _NoopTracer:
    """Minimal no-op tracer used when opentelemetry is not installed."""

    def start_as_current_span(self, name, **kwargs):
        from contextlib import contextmanager

        @contextmanager
        def _noop():
            yield _NoopSpan()

        return _noop()


class _NoopSpan:
    def set_attribute(self, key, value):
        pass

    def record_exception(self, exc, **kwargs):
        pass

    def set_status(self, *args, **kwargs):
        pass
