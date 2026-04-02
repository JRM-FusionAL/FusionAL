"""
FusionAL Think Tank v0.1
Triggered by watchdog.py when auto-restart fails or budget gate trips.
3 Claude agents collaborate → Logic Observer reviews → action plan returned.
All-Claude MVP (single provider) — cross-provider upgrade later.
"""

import asyncio
import json
import os
import time
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field

import anthropic

log = logging.getLogger("think_tank")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LOG_DIR = Path(__file__).parent.parent / "logs"
TT_LOG = LOG_DIR / "think_tank_log.json"

# ─────────────────────────────────────────────
# AGENT CONFIGS
# ─────────────────────────────────────────────

@dataclass
class TTAgent:
    name: str
    role: str
    system_prompt: str
    model: str = "claude-sonnet-4-20250514"

AGENTS = [
    TTAgent(
        name="InfraAgent",
        role="Infrastructure Expert",
        system_prompt=(
            "You are an MCP infrastructure expert. You analyze Docker container failures, "
            "port issues, memory constraints, and health check failures. "
            "You know FusionAL's server stack: ports 8009, 8089, 8101-8104. "
            "Be concise. Respond ONLY in valid JSON."
        ),
    ),
    TTAgent(
        name="LogicAgent",
        role="Dependency Analyzer",
        system_prompt=(
            "You are a systems dependency analyzer. You trace failure cascades, "
            "identify circular dependencies, and find root causes in distributed systems. "
            "Be concise. Respond ONLY in valid JSON."
        ),
    ),
    TTAgent(
        name="RecoveryAgent",
        role="Recovery Specialist",
        system_prompt=(
            "You are a recovery specialist with a library of known MCP fix patterns. "
            "You propose safe, executable remediation steps ranked by risk. "
            "Be concise. Respond ONLY in valid JSON."
        ),
    ),
]

OBSERVER = TTAgent(
    name="LogicObserver",
    role="Structural Observer",
    model="claude-opus-4-5",
    system_prompt=(
        "You are a pure-logic structural observer. You do NOT execute tasks. "
        "You review agent plans for logical flaws, missing steps, circular reasoning, "
        "and unsafe actions. Be brutal. Be brief. Respond ONLY in valid JSON."
    ),
)

# ─────────────────────────────────────────────
# PROMPTS
# ─────────────────────────────────────────────

DIAGNOSIS_PROMPT = """
A FusionAL MCP server has failed. Auto-restart did not recover it.

Fault context:
{fault_json}

Your role: {role}

Diagnose from your perspective. Return JSON:
{{
  "diagnosis": "...(1-2 sentences)",
  "root_cause_hypothesis": "...",
  "confidence": 0-10,
  "token_estimate": <int>,
  "needs_from_others": ["what you need from other agents"]
}}
"""

PLAN_PROMPT = """
You are {role}. Other agents have diagnosed this fault:

{all_diagnoses}

Now propose your recovery steps. Return JSON:
{{
  "steps": [
    {{"action": "...", "command": "...(shell cmd or null)", "risk": "low|medium|high", "reversible": true|false}}
  ],
  "token_estimate": <int>,
  "escalate_to_human": true|false,
  "escalation_reason": "...(or null)"
}}
"""

OBSERVER_PROMPT = """
Three agents have proposed a recovery plan for a failed FusionAL MCP server.

Fault: {fault_json}

Agent plans:
{all_plans}

Review for: logical consistency, unsafe commands, missing steps, circular fixes, 
and whether human escalation is actually needed.

Return JSON:
{{
  "verdict": "APPROVED" | "REVISE" | "ESCALATE",
  "issues": ["..."],
  "safe_to_execute": true|false,
  "final_steps": [
    {{"action": "...", "command": "...(or null)", "risk": "low|medium|high"}}
  ],
  "escalate_reason": "...(or null)"
}}
"""
