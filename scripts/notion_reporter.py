"""
FusionAL Notion Reporter v0.1
Posts Think Tank results + execution summaries to Incident Log.
Runs after action_executor completes — full audit trail in Notion.
"""

from dotenv import load_dotenv
from pathlib import Path as _Path
load_dotenv(_Path(__file__).parent.parent / "core" / ".env")

import json
import logging
import os
import requests
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("notion_reporter")

INCIDENT_LOG_DB = "7b0194c1-c3d6-4aa0-b45f-6b7f0e3ba371"
NOTION_VERSION  = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"


def _headers() -> dict:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        raise EnvironmentError("NOTION_TOKEN not set in environment")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _rt(text: str) -> list:
    """Build a rich_text block — truncated to 2000 chars (Notion limit)."""
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def post_incident(
    server_name: str,
    fault_type: str,
    trigger_reason: str,
    verdict: str,
    action_plan: list[str],
    execution_summary: str,
    issues: list[str],
    escalate: bool,
    escalation_reason: str,
) -> str | None:
    """
    Create one Incident Log entry in Notion.
    Returns the new page URL or None on failure.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Build status: Resolved if APPROVED + executed, else Open
    status = "Resolved" if (verdict == "APPROVED" and not escalate) else "Open"

    # Build notes content
    notes_parts = [
        f"Trigger: {trigger_reason}",
        f"Think Tank Verdict: {verdict}",
        "",
        "Action Plan:",
        *[f"  {i+1}. {step}" for i, step in enumerate(action_plan)],
        "",
        "Execution Summary:",
        execution_summary or "(no execution — plan not approved)",
    ]
    if issues:
        notes_parts += ["", "Observer Issues:", *[f"  • {i}" for i in issues]]
    if escalate:
        notes_parts += ["", f"⚠️ ESCALATED TO HUMAN: {escalation_reason}"]

    notes_text = "\n".join(notes_parts)

    error_text = f"[{fault_type}] Watchdog trigger: {trigger_reason}"

    payload = {
        "parent": {"database_id": INCIDENT_LOG_DB},
        "icon": {"type": "emoji", "emoji": "🤖"},
        "properties": {
            "Server":  {"title": _rt(server_name)},
            "Status":  {"select": {"name": status}},
            "Error":   {"rich_text": _rt(error_text)},
            "Date":    {"date": {"start": now}},
            "Notes":   {"rich_text": _rt(notes_text)},
        },
    }

    try:
        resp = requests.post(
            f"{NOTION_API_BASE}/pages",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        url = resp.json().get("url", "")
        log.info(f"[NotionReporter] Incident logged: {url}")
        return url
    except requests.HTTPError as e:
        log.error(f"[NotionReporter] HTTP error: {e.response.status_code} {e.response.text[:300]}")
        return None
    except Exception as e:
        log.error(f"[NotionReporter] Failed to post incident: {e}")
        return None


def report_think_tank_result(
    fault_server: str,
    fault_type: str,
    trigger_reason: str,
    verdict: str,
    action_plan: list[str],
    exec_results: list | None,
    issues: list[str],
    escalate: bool,
    escalation_reason: str,
) -> str | None:
    """
    High-level wrapper called from think_tank_trigger.
    Builds execution summary from exec_results then posts to Notion.
    """
    # Build execution summary text
    if exec_results:
        lines = []
        for i, r in enumerate(exec_results):
            if r.get("skipped"):
                lines.append(f"[{i+1}] SKIPPED — {r.get('step','')[:60]} ({r.get('skip_reason','')})")
            elif r.get("success"):
                lines.append(f"[{i+1}] OK — {r.get('command','')}")
            else:
                lines.append(f"[{i+1}] FAIL — {r.get('command','')} | {r.get('stderr','')[:80]}")
        exec_summary = "\n".join(lines)
    else:
        exec_summary = "(not executed)"

    return post_incident(
        server_name=fault_server,
        fault_type=fault_type,
        trigger_reason=trigger_reason,
        verdict=verdict,
        action_plan=action_plan,
        execution_summary=exec_summary,
        issues=issues,
        escalate=escalate,
        escalation_reason=escalation_reason,
    )

