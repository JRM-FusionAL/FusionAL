"""
FusionAL Think Tank Trigger v0.1
Called by watchdog.py when auto-restart fails or budget gate is hit.
3 Claude agents collaborate on diagnosis → Logic Observer reviews → action plan.
MVP: all-Anthropic for validation. Cross-provider added in next phase.
"""

import asyncio
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

from dotenv import load_dotenv
from pathlib import Path as _Path
load_dotenv(_Path(__file__).parent.parent / "core" / ".env")

import anthropic
import action_executor as executor
import notion_reporter as reporter

log = logging.getLogger("think_tank")

LOG_DIR = Path(__file__).parent.parent / "logs"
TT_LOG = LOG_DIR / "think_tank_log.json"
FAULT_LOG = LOG_DIR / "fault_log.json"

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

class ReasoningPreset(Enum):
    LOW  = "low"
    MID  = "mid"
    HIGH = "high"

PRESET_THINKING_BUDGET = {
    ReasoningPreset.LOW:  1024,
    ReasoningPreset.MID:  4096,
    ReasoningPreset.HIGH: 10000,
}

DEFAULT_PRESET = ReasoningPreset.MID
OBSERVER_PRESET = ReasoningPreset.HIGH  # Observer always HIGH

WORKER_MODEL   = "claude-sonnet-4-20250514"
OBSERVER_MODEL = "claude-opus-4-5"


# ─────────────────────────────────────────────
# AGENT PROMPTS
# ─────────────────────────────────────────────

ROLE_NEGOTIATION_PROMPT = """
You are Agent-{idx} in a 3-agent FusionAL Think Tank.
A server failure has been detected. Review it and propose your role.
Be efficient — no fluff, no preamble.

Failure context:
{fault_json}

Choose ONE role from: [infrastructure, logic_analyzer, recovery_specialist]
Respond ONLY in JSON:
{{
  "proposed_role": "...",
  "rationale": "one sentence max",
  "token_estimate": <int>
}}
"""

DIAGNOSIS_PROMPT = """
You are the {role} agent in the FusionAL Think Tank.
Server failure context:
{fault_json}

Known server inventory:
{servers_json}

Recent fault history (last 5):
{fault_history}

Your role responsibilities:
- infrastructure: Analyze Docker state, port conflicts, memory pressure
- logic_analyzer: Trace dependency chain, identify circular failures, flag cascading risks
- recovery_specialist: Propose concrete fix steps based on known FusionAL failure patterns

Respond ONLY in JSON:
{{
  "root_cause_hypothesis": "...",
  "supporting_evidence": ["...", "..."],
  "recommended_actions": ["step1", "step2", "step3"],
  "confidence": 0-10,
  "token_estimate": <int>
}}
"""

OBSERVER_PROMPT = """
You are the Logic Observer for the FusionAL Think Tank.
Extended thinking is ON. Be thorough.

Three agents have diagnosed this server failure:
{fault_json}

Agent diagnoses:
{diagnoses_json}

Your job: structural critique only.
- Find logical inconsistencies between diagnoses
- Identify missing steps or false assumptions
- Confirm or reject the consensus action plan
- Flag any action that could cause cascading damage

Respond ONLY in JSON:
{{
  "verdict": "APPROVED" | "REVISE" | "REJECT",
  "consensus_action_plan": ["step1", "step2", "step3"],
  "issues": ["..."],
  "optimizations": ["..."],
  "escalate_to_human": true | false,
  "escalation_reason": "..." 
}}
"""


# ─────────────────────────────────────────────
# CORE ENGINE
# ─────────────────────────────────────────────

@dataclass
class FaultEvent:
    server_name: str
    fault_type: str
    detail: str
    trigger: str  # "restart_failed" | "budget_gate" | "critical_down"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

@dataclass
class ThinkTankResult:
    verdict: str
    action_plan: list[str]
    issues: list[str]
    escalate: bool
    escalation_reason: str
    raw_diagnoses: list[dict]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


def _get_recent_faults(server_name: str, limit: int = 5) -> list:
    """Pull last N faults for context."""
    if not FAULT_LOG.exists():
        return []
    try:
        all_faults = json.loads(FAULT_LOG.read_text())
        relevant = [f for f in all_faults if f.get("server") == server_name]
        return relevant[-limit:]
    except Exception:
        return []


async def _call_claude(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    user_content: str,
    thinking_budget: int = 4096,
    use_thinking: bool = False,
) -> tuple[str, int]:
    """Unified Claude call. Returns (text, tokens_used)."""
    kwargs = dict(
        model=model,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    if use_thinking:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    resp = client.messages.create(**kwargs)
    tokens = resp.usage.input_tokens + resp.usage.output_tokens
    text = " ".join(
        b.text for b in resp.content
        if hasattr(b, "text") and b.type == "text"
    )
    return text, tokens


async def run_think_tank(
    fault: FaultEvent,
    servers: list[dict],
    preset: ReasoningPreset = DEFAULT_PRESET,
) -> ThinkTankResult:
    """
    Full Think Tank session for one fault event.
    Phase 1: 3 workers negotiate roles + diagnose (parallel)
    Phase 2: Logic Observer reviews consensus → final verdict
    """
    client = anthropic.Anthropic()
    fault_json = json.dumps(fault.__dict__, indent=2)
    servers_json = json.dumps([{k: v for k, v in s.items()} for s in servers], indent=2)
    fault_history = json.dumps(_get_recent_faults(fault.server_name), indent=2)
    thinking_budget = PRESET_THINKING_BUDGET[preset]

    log.info(f"[ThinkTank] Starting session | server={fault.server_name} | preset={preset.value}")

    # ── PHASE 1A: Role Negotiation (parallel) ──
    log.info("[ThinkTank] Phase 1A: Role negotiation")
    role_tasks = [
        _call_claude(
            client, WORKER_MODEL,
            system="You are an expert AI agent in a multi-agent diagnostic system. Always respond in valid JSON only.",
            user_content=ROLE_NEGOTIATION_PROMPT.format(idx=i+1, fault_json=fault_json),
            thinking_budget=thinking_budget,
            use_thinking=(preset == ReasoningPreset.HIGH),
        )
        for i in range(3)
    ]
    role_results = await asyncio.gather(*role_tasks)

    roles = []
    fallback_roles = ["infrastructure", "logic_analyzer", "recovery_specialist"]
    for i, (text, tokens) in enumerate(role_results):
        try:
            data = json.loads(text)
            roles.append(data.get("proposed_role", fallback_roles[i]))
        except Exception:
            roles.append(fallback_roles[i])
    log.info(f"[ThinkTank] Roles assigned: {roles}")

    # ── PHASE 1B: Diagnosis (parallel) ──
    log.info("[ThinkTank] Phase 1B: Parallel diagnosis")
    diag_tasks = [
        _call_claude(
            client, WORKER_MODEL,
            system="You are a specialist diagnostic agent. Always respond in valid JSON only.",
            user_content=DIAGNOSIS_PROMPT.format(
                role=roles[i],
                fault_json=fault_json,
                servers_json=servers_json,
                fault_history=fault_history,
            ),
            thinking_budget=thinking_budget,
            use_thinking=(preset == ReasoningPreset.HIGH),
        )
        for i in range(3)
    ]
    diag_results = await asyncio.gather(*diag_tasks)

    diagnoses = []
    for i, (text, tokens) in enumerate(diag_results):
        try:
            data = json.loads(text)
            data["agent_role"] = roles[i]
            diagnoses.append(data)
        except Exception:
            diagnoses.append({"agent_role": roles[i], "raw": text})
    log.info(f"[ThinkTank] Diagnoses complete")

    # ── PHASE 2: Logic Observer ──
    log.info("[ThinkTank] Phase 2: Logic Observer review")
    obs_text, obs_tokens = await _call_claude(
        client, OBSERVER_MODEL,
        system="You are a pure-logic structural observer. Never take sides. Always respond in valid JSON only.",
        user_content=OBSERVER_PROMPT.format(
            fault_json=fault_json,
            diagnoses_json=json.dumps(diagnoses, indent=2),
        ),
        thinking_budget=PRESET_THINKING_BUDGET[OBSERVER_PRESET],
        use_thinking=True,  # Observer always uses extended thinking
    )

    try:
        obs = json.loads(obs_text)
    except Exception:
        obs = {
            "verdict": "REVISE",
            "consensus_action_plan": [],
            "issues": ["Observer parse error"],
            "escalate_to_human": True,
            "escalation_reason": "Could not parse observer output",
        }

    result = ThinkTankResult(
        verdict=obs.get("verdict", "REVISE"),
        action_plan=obs.get("consensus_action_plan", []),
        issues=obs.get("issues", []),
        escalate=obs.get("escalate_to_human", False),
        escalation_reason=obs.get("escalation_reason", ""),
        raw_diagnoses=diagnoses,
    )

    _log_result(fault, result)
    log.info(f"[ThinkTank] Verdict: {result.verdict} | Escalate: {result.escalate}")

    # ── AUTO-EXECUTE if APPROVED and plan exists ──
    exec_results_raw = None
    if result.verdict == "APPROVED" and result.action_plan and not result.escalate:
        log.info("[ThinkTank] Observer APPROVED — dispatching to Action Executor")
        exec_results = executor.execute_plan(
            action_plan=result.action_plan,
            dry_run=False,
            stop_on_failure=False,
        )
        summary = executor.execution_summary(exec_results)
        log.info(f"[ThinkTank] Execution complete:\n{summary}")
        exec_results_raw = [r.__dict__ for r in exec_results]
    elif result.verdict == "APPROVED" and result.escalate:
        log.warning("[ThinkTank] APPROVED but escalation flagged — skipping auto-execute")
    else:
        log.warning(f"[ThinkTank] Verdict={result.verdict} — no auto-execution")

    # ── NOTION INCIDENT LOG ──
    try:
        notion_url = reporter.report_think_tank_result(
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
        if notion_url:
            log.info(f"[ThinkTank] Notion incident logged: {notion_url}")
    except Exception as e:
        log.error(f"[ThinkTank] Notion report failed (non-critical): {e}")

    return result


def _log_result(fault: FaultEvent, result: ThinkTankResult):
    """Persist Think Tank session to think_tank_log.json."""
    entry = {
        "fault": fault.__dict__,
        "verdict": result.verdict,
        "action_plan": result.action_plan,
        "issues": result.issues,
        "escalate": result.escalate,
        "escalation_reason": result.escalation_reason,
        "timestamp": result.timestamp,
    }
    existing = []
    if TT_LOG.exists():
        try:
            existing = json.loads(TT_LOG.read_text())
        except Exception:
            existing = []
    existing.append(entry)
    TT_LOG.write_text(json.dumps(existing, indent=2))


def trigger(
    server_name: str,
    fault_type: str,
    detail: str,
    trigger_reason: str,
    servers: list[dict],
    preset: ReasoningPreset = DEFAULT_PRESET,
) -> ThinkTankResult:
    """
    Synchronous entry point called from watchdog.py.
    Runs the async Think Tank in a clean event loop.
    """
    fault = FaultEvent(
        server_name=server_name,
        fault_type=fault_type,
        detail=detail,
        trigger=trigger_reason,
    )
    log.info(f"[ThinkTank] Triggered by watchdog | reason={trigger_reason}")
    return asyncio.run(run_think_tank(fault, servers, preset))

