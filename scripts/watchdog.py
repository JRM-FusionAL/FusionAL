"""
FusionAL Server Watchdog v0.1
Monitors MCP servers, detects crashes, auto-restarts containers.
Zero AI cost. Pure Python + Docker.
Built from real crash signatures in fusional-knowledge-base logs.
"""

import subprocess
import requests
import json
import time
import logging
from datetime import datetime
from pathlib import Path
import threading
import think_tank_trigger as tt

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

FAULT_LOG = LOG_DIR / "fault_log.json"
WATCHDOG_LOG = LOG_DIR / "watchdog.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(WATCHDOG_LOG),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("watchdog")

SERVERS = [
    {
        "name": "fusional-mcp",
        "port": 8009,
        "container": "fusional-mcp",
        "health_path": "/health",
        "critical": True,
    },
    {
        "name": "business-intelligence-mcp",
        "port": 8101,
        "container": "business-intelligence-mcp",
        "health_path": "/health",
        "critical": False,
    },
    {
        "name": "api-integration-hub",
        "port": 8102,
        "container": "api-integration-hub",
        "health_path": "/health",
        "critical": False,
    },
    {
        "name": "content-automation-mcp",
        "port": 8103,
        "container": "content-automation-mcp",
        "health_path": "/health",
        "critical": False,
    },
    {
        "name": "intelligence-mcp",
        "port": 8104,
        "container": "intelligence-mcp",
        "health_path": "/health",
        "critical": False,
    },
]

POLL_INTERVAL = 30
RESTART_COOLDOWN = 60
MAX_RESTARTS_PER_HOUR = 3
HEALTH_TIMEOUT = 5

restart_tracker: dict = {s["name"]: [] for s in SERVERS}


def log_fault(server_name: str, fault_type: str, detail: str, action: str):
    """Append fault to fault_log.json for the diagnosis agent."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "server": server_name,
        "fault_type": fault_type,
        "detail": detail,
        "action_taken": action,
    }
    existing = []
    if FAULT_LOG.exists():
        try:
            existing = json.loads(FAULT_LOG.read_text())
        except Exception:
            existing = []
    existing.append(entry)
    FAULT_LOG.write_text(json.dumps(existing, indent=2))
    log.warning(f"FAULT LOGGED: {server_name} | {fault_type} | {action}")


def check_health(server: dict) -> bool:
    """Ping server health endpoint. Returns True if healthy."""
    url = f"http://localhost:{server['port']}{server['health_path']}"
    try:
        r = requests.get(url, timeout=HEALTH_TIMEOUT)
        return r.status_code == 200
    except requests.exceptions.ConnectionError:
        return False
    except requests.exceptions.Timeout:
        return False
    except Exception as e:
        log.error(f"Unexpected health check error for {server['name']}: {e}")
        return False


def can_restart(server_name: str) -> bool:
    """Budget gate: block restart if too many attempts in last hour."""
    now = time.time()
    hour_ago = now - 3600
    recent = [t for t in restart_tracker[server_name] if t > hour_ago]
    restart_tracker[server_name] = recent
    return len(recent) < MAX_RESTARTS_PER_HOUR


def restart_container(server: dict) -> bool:
    """Execute docker restart and verify recovery."""
    container = server["container"]
    log.info(f"Attempting restart: {container}")
    try:
        result = subprocess.run(
            ["docker", "restart", container],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            time.sleep(5)
            if check_health(server):
                log.info(f"RECOVERED: {container} healthy after restart")
                restart_tracker[server["name"]].append(time.time())
                return True
            else:
                log.error(f"RESTART FAILED: {container} still unhealthy")
                return False
        else:
            log.error(f"Docker restart error: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        log.error(f"Docker restart timed out for {container}")
        return False


def handle_fault(server: dict):
    """Diagnose fault and apply budget-gated repair."""
    name = server["name"]

    if not can_restart(name):
        msg = f"Budget gate: max restarts reached for {name}, escalating to Think Tank"
        log.error(msg)
        log_fault(name, "crash", "health check failed", "budget_gate_think_tank_triggered")
        _fire_think_tank(server, "crash", "health check failed", "budget_gate")
        return

    recovered = restart_container(server)
    if recovered:
        log_fault(name, "crash", "health check failed", "restarted_successfully")
    else:
        action = "restart_failed_think_tank_triggered"
        if server["critical"]:
            log.critical(f"CRITICAL SERVER DOWN: {name} — escalating to Think Tank")
        log_fault(name, "crash", "health check failed + restart failed", action)
        _fire_think_tank(server, "crash", "health check failed + restart failed", "restart_failed")


def _fire_think_tank(server: dict, fault_type: str, detail: str, trigger_reason: str):
    """Non-blocking Think Tank dispatch — runs in background thread."""
    def _run():
        try:
            result = tt.trigger(
                server_name=server["name"],
                fault_type=fault_type,
                detail=detail,
                trigger_reason=trigger_reason,
                servers=SERVERS,
            )
            log.info(f"[ThinkTank] Verdict={result.verdict} | Plan={result.action_plan}")
            if result.escalate:
                log.critical(f"[ThinkTank] ESCALATE TO HUMAN: {result.escalation_reason}")
        except Exception as e:
            log.error(f"[ThinkTank] Failed to run: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    log.info(f"[ThinkTank] Dispatched in background for {server['name']}")


def run():
    """Main watchdog loop."""
    log.info("FusionAL Watchdog started")
    log.info(f"Monitoring {len(SERVERS)} servers every {POLL_INTERVAL}s")

    while True:
        for server in SERVERS:
            healthy = check_health(server)
            if healthy:
                log.debug(f"OK: {server['name']}:{server['port']}")
            else:
                log.warning(f"FAULT DETECTED: {server['name']}:{server['port']}")
                handle_fault(server)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
