"""
FusionAL Docker Sandbox Runner

Securely executes Python code in isolated Docker containers with hardened security constraints:
- Network isolation (--network none)
- Memory limits (configurable, default 128MB)
- Process limits (--pids-limit 64)
- No new privileges (--security-opt no-new-privileges)
- Capability drop (--cap-drop ALL)
- Read-only filesystem (--read-only with tmpfs for /tmp)
- Non-root user execution (--user 1000:1000)
"""

import tempfile
import os
import shutil
import subprocess  # nosec B404
import logging
from typing import Dict

LOGGER = logging.getLogger("fusional.runner_docker")


def _abs_path_for_docker(path: str) -> str:
    """Convert path to Docker-compatible format. Windows Docker Desktop handles absolute paths."""
    return os.path.abspath(path)


def run_in_docker(code: str, timeout: int = 5, memory_mb: int = 128) -> Dict:
    """
    Execute Python code inside a disposable, hardened Docker container.

    Args:
        code: Python source code to execute
        timeout: Maximum execution time in seconds
        memory_mb: Memory limit in megabytes (default 128MB)

    Returns:
        Dict with 'stdout', 'stderr', and 'returncode' from execution

    Security constraints applied:
        - No network access (--network none)
        - Limited memory (--memory {memory_mb}m)
        - Limited processes (--pids-limit 64)
        - No new privileges (--security-opt no-new-privileges)
        - Dropped all capabilities (--cap-drop ALL)
        - Read-only root filesystem (--read-only)
        - Non-root user (--user 1000:1000)
        - Temporary filesystem at /tmp (--tmpfs)

    Requirements:
        - Docker daemon available and accessible
        - User permitted to run docker commands
        - python:3.11-slim image available (auto-pulled if missing)
    """
    tmpdir = tempfile.mkdtemp(prefix="fusional-docker-")
    try:
        script_path = os.path.join(tmpdir, "script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        abs_tmp = _abs_path_for_docker(tmpdir)

        # Build hardened docker run command
        cmd = [
            "docker",
            "run",
            "--rm",                          # Remove container after execution
            "--network", "none",             # No network access
            f"--memory={int(memory_mb)}m",   # Memory limit
            "--pids-limit", "64",            # Process limit
            "--security-opt", "no-new-privileges",  # No privilege escalation
            "--cap-drop", "ALL",             # Drop all capabilities
            "--read-only",                   # Read-only root filesystem
            "--tmpfs", "/tmp:rw,exec,nosuid,size=64m",  # nosec B108
            "-v", f"{abs_tmp}:/workdir:ro",  # Mount code as read-only
            "-w", "/workdir",                # Set working directory
            "--user", "1000:1000",           # Non-root user
            "python:3.11-slim",              # Base image
            "python",
            "script.py",
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # nosec B603
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode
        }
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception as exc:
            LOGGER.debug("Failed cleaning temp directory %s: %s", tmpdir, exc)
