"""
FusionAL Action Executor v0.1
Takes Observer-approved action plan from Think Tank.
Maps natural language steps to real Docker/system commands.
Executes with safety gates. Logs everything.
"""

import subprocess
import json
import logging
import time
import re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field

log = logging.getLogger("action_executor")

LOG_DIR = Path(__file__).parent.parent / "logs"
EXEC_LOG = LOG_DIR / "execution_log.json"

# ─────────────────────────────────────────────
# SAFETY GATE — ALLOWED COMMAND PATTERNS ONLY
# These are the ONLY commands the executor will run.
# Nothing outside this list executes. Ever.
# ─────────────────────────────────────────────

SAFE_COMMAND_PATTERNS = [
    r"^docker restart \w[\w\-]+$",
    r"^docker stop \w[\w\-]+$",
    r"^docker start \w[\w\-]+$",
    r"^docker logs \w[\w\-]+( --tail \d+)?$",
    r"^docker inspect \w[\w\-]+$",
    r"^docker ps( -a)?$",
    r"^docker stats --no-stream$",
    r"^docker compose up -d( \w[\w\-]+)?$",
    r"^docker compose down$",
    r"^docker compose restart( \w[\w\-]+)?$",
    r"^docker network ls$",
    r"^docker volume ls$",
]


# ─────────────────────────────────────────────
# STEP → COMMAND MAPPER
# Natural language step → safe shell command
# Add patterns as you discover new fix types.
# ─────────────────────────────────────────────

STEP_COMMAND_MAP = [
    # Restart patterns
    (r"restart\s+(?:container\s+)?(?:the\s+)?['\"]?([\w\-]+)['\"]?",
     lambda m: f"docker restart {m.group(1)}"),

    # Stop patterns
    (r"stop\s+(?:container\s+)?(?:the\s+)?['\"]?([\w\-]+)['\"]?",
     lambda m: f"docker stop {m.group(1)}"),

    # Start patterns
    (r"start\s+(?:container\s+)?(?:the\s+)?['\"]?([\w\-]+)['\"]?",
     lambda m: f"docker start {m.group(1)}"),

    # Get logs
    (r"(?:check|fetch|get|view)\s+logs?\s+(?:for\s+)?(?:the\s+)?['\"]?([\w\-]+)['\"]?",
     lambda m: f"docker logs {m.group(1)} --tail 50"),

    # Inspect container
    (r"inspect\s+(?:container\s+)?(?:the\s+)?['\"]?([\w\-]+)['\"]?",
     lambda m: f"docker inspect {m.group(1)}"),

    # Check all containers
    (r"(?:list|show|check)\s+(?:all\s+)?containers?",
     lambda m: "docker ps -a"),

    # Compose restart
    (r"compose\s+restart\s+(?:the\s+)?['\"]?([\w\-]+)['\"]?",
     lambda m: f"docker compose restart {m.group(1)}"),

    # Compose up
    (r"compose\s+up\s+(?:the\s+)?['\"]?([\w\-]+)['\"]?",
     lambda m: f"docker compose up -d {m.group(1)}"),

    # Stats
    (r"(?:check|get|show)\s+(?:resource\s+)?(?:stats|usage|memory|cpu)",
     lambda m: "docker stats --no-stream"),

    # Network check
    (r"(?:check|list|show)\s+networks?",
     lambda m: "docker network ls"),
]


@dataclass
class StepResult:
    step: str
    command: str | None
    stdout: str
    stderr: str
    returncode: int
    success: bool
    skipped: bool = False
    skip_reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ─────────────────────────────────────────────
# CORE FUNCTIONS
# ─────────────────────────────────────────────

def map_step_to_command(step: str) -> str | None:
    """
    Try to match a natural language step to a safe command.
    Returns None if no match found — step gets skipped.
    """
    step_lower = step.lower().strip()
    for pattern, builder in STEP_COMMAND_MAP:
        m = re.search(pattern, step_lower, re.IGNORECASE)
        if m:
            try:
                return builder(m)
            except Exception:
                continue
    return None


def is_safe(command: str) -> bool:
    """Hard safety gate. Command must match an allowed pattern."""
    for pattern in SAFE_COMMAND_PATTERNS:
        if re.match(pattern, command.strip(), re.IGNORECASE):
            return True
    return False


def run_command(command: str, timeout: int = 30) -> tuple[str, str, int]:
    """Execute a validated shell command. Returns (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            command.split(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout}s", 1
    except Exception as e:
        return "", str(e), 1


def execute_plan(
    action_plan: list[str],
    dry_run: bool = False,
    stop_on_failure: bool = False,
) -> list[StepResult]:
    """
    Execute an Observer-approved action plan step by step.
    dry_run=True logs what WOULD run without executing.
    stop_on_failure=True halts on first failed step.
    """
    results: list[StepResult] = []

    for i, step in enumerate(action_plan):
        log.info(f"[Executor] Step {i+1}/{len(action_plan)}: {step}")

        command = map_step_to_command(step)

        if command is None:
            result = StepResult(
                step=step, command=None,
                stdout="", stderr="",
                returncode=-1, success=False,
                skipped=True,
                skip_reason="No command mapping found for this step",
            )
            log.warning(f"[Executor] SKIPPED (no mapping): {step}")
            results.append(result)
            continue

        if not is_safe(command):
            result = StepResult(
                step=step, command=command,
                stdout="", stderr="",
                returncode=-1, success=False,
                skipped=True,
                skip_reason=f"Safety gate blocked: {command}",
            )
            log.error(f"[Executor] BLOCKED by safety gate: {command}")
            results.append(result)
            continue

        if dry_run:
            result = StepResult(
                step=step, command=command,
                stdout=f"[DRY RUN] Would execute: {command}",
                stderr="", returncode=0, success=True,
                skipped=False,
            )
            log.info(f"[Executor] DRY RUN: {command}")
            results.append(result)
            continue

        stdout, stderr, returncode = run_command(command)
        success = returncode == 0

        result = StepResult(
            step=step, command=command,
            stdout=stdout, stderr=stderr,
            returncode=returncode, success=success,
        )

        level = log.info if success else log.error
        level(f"[Executor] {'OK' if success else 'FAIL'} ({returncode}): {command}")
        if stderr:
            log.warning(f"[Executor] stderr: {stderr[:200]}")

        results.append(result)

        if not success and stop_on_failure:
            log.error("[Executor] Halting plan — stop_on_failure=True")
            break

        # Brief pause between steps to let Docker settle
        if success and i < len(action_plan) - 1:
            time.sleep(2)

    _log_execution(action_plan, results)
    return results


def _log_execution(action_plan: list[str], results: list[StepResult]):
    """Persist execution results to execution_log.json."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "plan": action_plan,
        "results": [
            {
                "step": r.step,
                "command": r.command,
                "success": r.success,
                "skipped": r.skipped,
                "skip_reason": r.skip_reason,
                "returncode": r.returncode,
                "stdout": r.stdout[:500],
                "stderr": r.stderr[:500],
            }
            for r in results
        ],
        "summary": {
            "total": len(results),
            "succeeded": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success and not r.skipped),
            "skipped": sum(1 for r in results if r.skipped),
        }
    }
    existing = []
    if EXEC_LOG.exists():
        try:
            existing = json.loads(EXEC_LOG.read_text())
        except Exception:
            existing = []
    existing.append(entry)
    EXEC_LOG.write_text(json.dumps(existing, indent=2))
    log.info(f"[Executor] Done. {entry['summary']}")


def execution_summary(results: list[StepResult]) -> str:
    """Human-readable summary for logging/Notion."""
    lines = []
    for i, r in enumerate(results):
        if r.skipped:
            lines.append(f"  [{i+1}] SKIPPED — {r.step[:60]} ({r.skip_reason})")
        elif r.success:
            lines.append(f"  [{i+1}] OK — {r.command}")
        else:
            lines.append(f"  [{i+1}] FAIL — {r.command} | {r.stderr[:80]}")
    return "\n".join(lines)

