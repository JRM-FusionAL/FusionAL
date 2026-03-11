"""
Streamable HTTP MCP transport layer for FusionAL.

Exposes FusionAL's code execution and AI project generation as MCP tools.
Mounts at /mcp on the FastAPI app — any MCP client can connect here.
"""

from mcp.server.fastmcp import FastMCP
from .ai_agent import (
    generate_and_execute as _generate_and_execute,
    generate_mcp_project as _gen_mcp_project,
)

mcp = FastMCP(
    "fusional",
    streamable_http_path="/",
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


@mcp.tool(
    name="generate_and_execute",
    description=(
        "Generate Python code from a natural language prompt using Claude, then execute it. "
        "Returns the generated code and execution result. Requires ANTHROPIC_API_KEY."
    ),
)
def generate_and_execute(prompt: str, timeout: int = 10) -> dict:
    return _generate_and_execute(prompt, provider="claude", timeout=timeout, use_docker=False)


@mcp.tool(
    name="generate_mcp_project",
    description=(
        "Generate a complete MCP server project from a description using Claude. "
        "Returns the output directory path and list of generated files. Requires ANTHROPIC_API_KEY."
    ),
)
def generate_mcp_project(description: str) -> dict:
    result = _gen_mcp_project(description, provider="claude", build=False)
    return {"out_dir": result["out_dir"], "files": result["files"]}
