"""
Streamable HTTP MCP transport layer for FusionAL.

Exposes FusionAL's code execution and AI project generation as MCP tools.
Mounts at /mcp on the FastAPI app — any MCP client can connect here.
"""

import time
from pathlib import Path
from typing import Annotated, Any, Optional, TypedDict
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
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


# --- Output schemas ---

class ExecuteCodeResult(TypedDict, total=False):
    stdout: str
    stderr: str
    returncode: int
    error: str


class GenerateAndExecuteResult(TypedDict):
    generated_code: str
    execution_result: dict[str, Any]


class GenerateMcpProjectResult(TypedDict):
    out_dir: str
    files: list[str]
    build_result: Optional[dict[str, Any]]


@mcp.tool(
    name="execute_code",
    description=(
        "Execute Python code in a sandboxed subprocess. "
        "Returns stdout, stderr, and return code. Timeout is capped at 30 seconds."
    ),
    annotations=ToolAnnotations(
        title="Execute Code",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
def execute_code(
    code: Annotated[str, Field(description="Python source code to execute in the sandboxed subprocess")],
    timeout: Annotated[int, Field(description="Maximum execution time in seconds; clamped to 1–30", ge=1, le=30)] = 5,
) -> ExecuteCodeResult:
    import shutil
    import subprocess
    import sys as _sys
    import tempfile

    def _run() -> ExecuteCodeResult:
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
    annotations=ToolAnnotations(
        title="Generate and Execute",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
def generate_and_execute(
    prompt: Annotated[str, Field(description="Natural language description of the Python task to generate and run via Claude")],
    timeout: Annotated[int, Field(description="Maximum execution time in seconds for the generated code", ge=1, le=60)] = 10,
) -> GenerateAndExecuteResult:
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
    annotations=ToolAnnotations(
        title="Generate MCP Project",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
def generate_mcp_project(
    description: Annotated[str, Field(description="Natural language description of the MCP server project to scaffold, including desired tools and functionality")],
) -> GenerateMcpProjectResult:
    def _run() -> GenerateMcpProjectResult:
        result = _gen_mcp_project(description, provider="claude", build=False)
        return {"out_dir": result["out_dir"], "files": result["files"], "build_result": result.get("build_result")}

    return _audit_call("generate_mcp_project", _run)
