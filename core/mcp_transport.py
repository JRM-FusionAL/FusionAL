"""
Streamable HTTP MCP transport layer for FusionAL.

Exposes an aggregating proxy that surfaces every registered downstream MCP
server as namespaced tools on this server.

Built-in tools (disabled for Phase 0 — available via REST only):
  execute_code          - run Python in a subprocess (REST /execute only)
  generate_and_execute  - prompt → Claude writes Python → runs it (REST only)
  generate_mcp_project  - scaffold a new MCP server project (REST only)

Proxied tools (registered at startup from REGISTRY):
  <namespace>_<tool>    e.g. bi_nl_query, github_create_issue
"""

import asyncio
import logging
import time
from typing import Any

from pydantic import ConfigDict, create_model

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.server.transport_security import TransportSecuritySettings
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

from .ai_agent import (
    generate_and_execute as _generate_and_execute,
    generate_mcp_project as _gen_mcp_project,
)

logger = logging.getLogger("fusional.proxy")

mcp = FastMCP(
    "fusional",
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)

# Injected by main.py after audit module is resolved; no-op if unavailable.
_record_tool_call = None


def set_audit_hook(fn) -> None:
    """Wire in the audit.record_tool_call function once the module is loaded."""
    global _record_tool_call
    _record_tool_call = fn


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------

# NOT registered as MCP tool — Phase 0 security gate.
# Available to REST /execute endpoint only.
def execute_code(code: str, timeout: int = 5) -> dict:
    import shutil
    import subprocess
    import sys
    import tempfile

    timeout = min(max(timeout, 1), 30)
    tmpdir = tempfile.mkdtemp(prefix="fusional-")
    script_path = f"{tmpdir}/script.py"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        proc = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "Execution timed out", "returncode": -1}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# NOT registered as MCP tool — Phase 0 security gate.
def generate_and_execute(prompt: str, timeout: int = 10) -> dict:
    return _generate_and_execute(prompt, provider="claude", timeout=timeout, use_docker=False)


# NOT registered as MCP tool — Phase 0 security gate.
# Available to REST /generate endpoint only.
def generate_mcp_project(description: str) -> dict:
    result = _gen_mcp_project(description, provider="claude", build=False)
    return {"out_dir": result["out_dir"], "files": result["files"]}


# ---------------------------------------------------------------------------
# Aggregating proxy — schema-preserving tool registration
# ---------------------------------------------------------------------------

class _PassthroughArgModel(ArgModelBase):
    """Pydantic model that accepts any extra fields and passes them all through.

    Used for proxy tools so the actual argument validation is left to the
    downstream MCP server, not FastMCP.
    """
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        # Return all declared fields + any extra (unknown) fields
        result: dict[str, Any] = {}
        for field_name, field_info in self.__class__.model_fields.items():
            value = getattr(self, field_name)
            output_name = field_info.alias if field_info.alias else field_name
            result[output_name] = value
        if self.model_extra:
            result.update(self.model_extra)
        return result


def _make_passthrough_tool(
    name: str,
    description: str,
    input_schema: dict,
    fn,
) -> Tool:
    """Construct a FastMCP Tool with a custom JSON schema and a passthrough fn."""
    # Build a FuncMetadata whose arg_model accepts any dict
    meta = FuncMetadata(arg_model=_PassthroughArgModel)
    return Tool(
        fn=fn,
        name=name,
        title=None,
        description=description,
        parameters=input_schema,
        fn_metadata=meta,
        is_async=True,
        context_kwarg=None,
    )


def _server_namespace(server_name: str) -> str:
    """Derive a short namespace prefix from a server name.

    Examples:
      business-intelligence-mcp  → bi
      api-integration-hub        → api
      content-automation-mcp     → content
      github-mcp-safe            → github
      intelligence-mcp           → intel
      fusional-recall            → recall
    """
    _overrides = {
        "business-intelligence-mcp": "bi",
        "api-integration-hub": "api",
        "content-automation-mcp": "content",
        "github-mcp-safe": "github",
        "intelligence-mcp": "intel",
        "fusional-recall": "recall",
        "kb-server": "kb",
    }
    if server_name in _overrides:
        return _overrides[server_name]
    slug = server_name.removesuffix("-mcp").removesuffix("-safe").removesuffix("-hub")
    return slug.split("-")[0]


def _proxy_tool_name(namespace: str, tool_name: str) -> str:
    """Build a valid MCP tool name: <namespace>_<tool> (a-z0-9_- only, max 64)."""
    safe_tool = tool_name.replace("-", "_")
    return f"{namespace}_{safe_tool}"[:64]


def _make_proxy_fn(mcp_url: str, tool_name: str, proxied_name: str):
    """Return an async function that proxies calls to a downstream MCP tool."""

    async def proxy(**kwargs: Any) -> dict:
        t0 = time.monotonic()
        status = "success"
        error_str = ""
        try:
            async with streamablehttp_client(mcp_url, timeout=30.0) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, kwargs)
                    # call_tool returns isError=True on tool-level failures; it does not raise.
                    if getattr(result, "isError", False):
                        status = "error"
                        error_str = " ".join(
                            getattr(c, "text", "") for c in result.content if hasattr(c, "text")
                        )[:500]
                    return {"content": [c.model_dump() for c in result.content]}
        except Exception as exc:
            status = "error"
            error_str = str(exc)
            raise
        finally:
            duration_ms = (time.monotonic() - t0) * 1000
            if _record_tool_call is not None:
                try:
                    _record_tool_call(proxied_name, status, duration_ms, error=error_str)
                except Exception:
                    pass

    proxy.__name__ = tool_name
    return proxy


async def register_downstream_tools(registry: dict) -> None:
    """Fetch tool manifests from all registered downstream MCP servers and
    add proxy tools to the FusionAL MCP server.

    Called once from the FastAPI lifespan after the registry is loaded.
    Failures are logged as warnings — a down downstream does NOT prevent
    FusionAL from starting.
    """
    existing_names = {t.name for t in (await mcp.list_tools())}

    for server_name, server_info in registry.items():
        # Prefer native_url (host networking) when running outside Docker,
        # then internal_url (Docker bridge), then url as fallback.
        import os as _os
        _in_docker = _os.path.exists("/.dockerenv")
        base_url = (
            (server_info.get("native_url") if not _in_docker else None)
            or server_info.get("internal_url")
            or server_info.get("url", "")
        ).rstrip("/")
        if not base_url:
            continue

        mcp_url = base_url + "/mcp"
        namespace = _server_namespace(server_name)

        try:
            # Retry once after a short delay to handle startup race conditions
            # (e.g. kb-server's MCP thread may not be bound when FusionAL starts).
            tools_result = None
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    async with streamablehttp_client(mcp_url, timeout=5.0) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt == 0:
                        await asyncio.sleep(3)

            if tools_result is None:
                raise last_exc  # type: ignore[misc]

            registered = 0
            for tool in tools_result.tools:
                proxied_name = _proxy_tool_name(namespace, tool.name)
                if proxied_name in existing_names:
                    continue

                proxy_fn = _make_proxy_fn(mcp_url, tool.name, proxied_name)
                tool_obj = _make_passthrough_tool(
                    name=proxied_name,
                    description=f"[{server_name}] {tool.description or tool.name}"[:512],
                    input_schema=tool.inputSchema or {"type": "object", "properties": {}},
                    fn=proxy_fn,
                )
                mcp._tool_manager._tools[proxied_name] = tool_obj
                existing_names.add(proxied_name)
                registered += 1

            logger.info(
                "proxy.registered server=%s namespace=%s tools=%d",
                server_name, namespace, registered,
            )

        except Exception as exc:
            logger.warning(
                "proxy.skip server=%s url=%s error=%s",
                server_name, mcp_url, exc,
            )
