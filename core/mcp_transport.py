"""
Streamable HTTP MCP transport layer for FusionAL.

Exposes FusionAL's code execution and AI project generation as MCP tools.
Mounts at /mcp on the FastAPI app — any MCP client can connect here.
"""

import time
from pathlib import Path
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from .ai_agent import (
    generate_and_execute as _generate_and_execute,
    generate_mcp_project as _gen_mcp_project,
)

# Ensure core/common is on the path so the audit module can be imported.
_common_dir = str(Path(__file__).resolve().parent / "common")
if _common_dir not in sys.path:
    sys.path.insert(0, _common_dir)

try:
    from audit import record_tool_call as _record_tool_call
    _AUDIT_ENABLED = True
except ImportError:  # pragma: no cover
    _AUDIT_ENABLED = False

    def _record_tool_call(*args, **kwargs) -> None:  # type: ignore[misc]
        """No-op stub used when the audit module is unavailable."""
        pass


def _audit_call(tool: str, fn, *args, **kwargs):
    """Execute *fn* with *args*/*kwargs* and record an audit entry.

    Args:
        tool:   Name of the MCP tool being invoked (used in the audit record).
        fn:     Callable to execute.
        *args:  Positional arguments forwarded to *fn*.
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The return value of *fn*.

    Raises:
        Re-raises any exception from *fn* after recording it as an error audit.
    """
    start = time.perf_counter()
    error = ""
    status = "success"
    try:
        result = fn(*args, **kwargs)
        return result
    except Exception as exc:
        status = "error"
        error = str(exc)
        raise
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        _record_tool_call(tool, status, duration_ms, error=error)


mcp = FastMCP(
    "fusional",
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


@mcp.tool(
    name="execute_code",
    description=(
        "Execute Python code in a sandboxed subprocess. "
        "Returns stdout, stderr, and return code. Timeout is capped at 30 seconds."
    ),
)
def execute_code(code: str, timeout: int = 5) -> dict:
    import shutil
    import subprocess
    import sys as _sys
    import tempfile

    def _run():
        _timeout = min(max(timeout, 1), 30)
        tmpdir = tempfile.mkdtemp(prefix="fusional-")
        script_path = f"{tmpdir}/script.py"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            proc = subprocess.run(
                [_sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=_timeout,
            )
            return {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}
        except subprocess.TimeoutExpired:
            return {"error": "Execution timed out", "returncode": -1}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return _audit_call("execute_code", _run)


@mcp.tool(
    name="generate_and_execute",
    description=(
        "Generate Python code from a natural language prompt using Claude, then execute it. "
        "Returns the generated code and execution result. Requires ANTHROPIC_API_KEY."
    ),
)
def generate_and_execute(prompt: str, timeout: int = 10) -> dict:
    return _audit_call(
        "generate_and_execute",
        _generate_and_execute,
        prompt,
        provider="claude",
        timeout=timeout,
        use_docker=False,
    )


@mcp.tool(
    name="generate_mcp_project",
    description=(
        "Generate a complete MCP server project from a description using Claude. "
        "Returns the output directory path and list of generated files. Requires ANTHROPIC_API_KEY."
    ),
)
def generate_mcp_project(description: str) -> dict:
    def _run():
        result = _gen_mcp_project(description, provider="claude", build=False)
        return {"out_dir": result["out_dir"], "files": result["files"]}

    return _audit_call("generate_mcp_project", _run)
