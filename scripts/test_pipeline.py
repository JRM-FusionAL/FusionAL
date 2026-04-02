"""
FusionAL Pipeline Test v0.1
Simulates a container failure to validate the full pipeline:
watchdog → think_tank → action_executor (dry_run) → notion_reporter

Run from FusionAL/scripts/:
  python test_pipeline.py

Flags:
  --live     Run executor for real (not dry run) — use with caution
  --skip-notion  Skip Notion posting (saves tokens if testing locally)
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

# ── setup logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("test_pipeline")

# ── args ──
parser = argparse.ArgumentParser()
parser.add_argument("--live",         action="store_true", help="Run executor live (not dry run)")
parser.add_argument("--skip-notion",  action="store_true", help="Skip Notion reporter")
parser.add_argument("--preset",       default="mid", choices=["low","mid","high"])
parser.add_argument("--server",       default="content-automation-mcp", help="Server name to simulate failing")
args = parser.parse_args()

# ── import pipeline modules ──
sys.path.insert(0, str(Path(__file__).parent))

import think_tank_trigger as tt
import action_executor as executor

if not args.skip_notion:
    import notion_reporter as reporter

# ── fake SERVERS list matching watchdog.py ──
SERVERS = [
    {"name": "fusional-mcp",             "port": 8009, "container": "fusional-mcp",             "health_path": "/health", "critical": True},
    {"name": "business-intelligence-mcp","port": 8101, "container": "business-intelligence-mcp","health_path": "/health", "critical": False},
    {"name": "api-integration-hub",      "port": 8102, "container": "api-integration-hub",      "health_path": "/health", "critical": False},
    {"name": "content-automation-mcp",   "port": 8103, "container": "content-automation-mcp",   "health_path": "/health", "critical": False},
    {"name": "intelligence-mcp",         "port": 8104, "container": "intelligence-mcp",          "health_path": "/health", "critical": False},
]

def separator(label: str):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}\n")


def run_test():
    separator("PHASE 1 — Simulated Fault Event")
    print(f"  Target server : {args.server}")
    print(f"  Preset        : {args.preset}")
    print(f"  Executor mode : {'LIVE' if args.live else 'DRY RUN'}")
    print(f"  Notion        : {'SKIP' if args.skip_notion else 'ENABLED'}")

    fault = tt.FaultEvent(
        server_name=args.server,
        fault_type="crash",
        detail="Simulated: health check failed + docker restart failed",
        trigger="restart_failed",
        timestamp=datetime.utcnow().isoformat(),
    )

    separator("PHASE 2 — Think Tank")
    print("  Firing 3 agents + Logic Observer...")
    print("  (This will take 30–90s depending on preset)\n")

    import asyncio
    preset_map = {
        "low":  tt.ReasoningPreset.LOW,
        "mid":  tt.ReasoningPreset.MID,
        "high": tt.ReasoningPreset.HIGH,
    }

    result = asyncio.run(tt.run_think_tank(
        fault=fault,
        servers=SERVERS,
        preset=preset_map[args.preset],
    ))

    separator("PHASE 3 — Think Tank Result")
    print(f"  Verdict       : {result.verdict}")
    print(f"  Escalate      : {result.escalate}")
    if result.escalation_reason:
        print(f"  Escalation    : {result.escalation_reason}")
    print(f"  Issues        : {result.issues}")
    print(f"\n  Action Plan:")
    for i, step in enumerate(result.action_plan):
        print(f"    {i+1}. {step}")

    separator("PHASE 4 — Action Executor")
    exec_results_raw = None

    if result.verdict == "APPROVED" and result.action_plan and not result.escalate:
        print(f"  Running {'LIVE' if args.live else 'DRY RUN'}...\n")
        exec_results = executor.execute_plan(
            action_plan=result.action_plan,
            dry_run=not args.live,
            stop_on_failure=False,
        )
        summary = executor.execution_summary(exec_results)
        print(summary)
        exec_results_raw = [r.__dict__ for r in exec_results]
    else:
        print(f"  Skipped — verdict={result.verdict}, escalate={result.escalate}")

    separator("PHASE 5 — Notion Reporter")
    if args.skip_notion:
        print("  Skipped (--skip-notion flag)")
    else:
        print("  Posting to Incident Log...")
        url = reporter.report_think_tank_result(
            fault_server=fault.server_name,
            fault_type=fault.fault_type,
            trigger_reason=fault.trigger,
            verdict=result.verdict,
            action_plan=result.action_plan,
            exec_results=exec_results_raw,
            issues=result.issues,
            escalate=result.escalate,
            escalation_reason=result.escalation_reason,
        )
        if url:
            print(f"  ✅ Incident logged: {url}")
        else:
            print("  ❌ Notion post failed — check NOTION_TOKEN")

    separator("TEST COMPLETE")
    print(f"  Logs written to: FusionAL/logs/")
    print(f"    think_tank_log.json")
    print(f"    execution_log.json")
    print(f"    watchdog.log\n")


if __name__ == "__main__":
    run_test()
