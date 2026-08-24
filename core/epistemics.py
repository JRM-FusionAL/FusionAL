"""Epistemic status engine for FusionAL.

Every proxied tool result gets an epistemic envelope before it reaches the
calling agent.  The gateway records what a tool SAID without promoting it to
authorized system state — the same invariant as the SMCP claim gate:

    Source -> Claim -> Provenance -> Review -> Graph
    Tool   -> Result -> Envelope   -> (future) Review -> Downstream use

Tagging only in Phase 1.  Enforcement (blocking downstream chaining on
PENDING_REVIEW / QUARANTINED results) is a follow-up.

Classification is deterministic and name-based (no LLM in the gate):
    DESTRUCTIVE   - irreversible verbs: drop, purge, delete-all, revoke...
    WRITE         - mutating verbs: create, update, send, approve, deploy...
    READONLY      - everything else (default)

Override per tool via the FUSIONAL_TOOL_TIERS env var (JSON object mapping
proxied tool name -> tier), e.g.:
    FUSIONAL_TOOL_TIERS='{"github_delete_issue": "DESTRUCTIVE"}'
"""

import hashlib
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("fusional.epistemics")

# Tier -> epistemic status + downstream permission.
#   OBSERVATION    - safe to feed anywhere
#   PENDING_REVIEW - agent must not chain decisions on it without human sign-off
#   QUARANTINED    - blocked from downstream use entirely
STATUS_MAP = {
    "READONLY": {"epistemic_status": "OBSERVATION", "downstream_use": True},
    "WRITE": {"epistemic_status": "PENDING_REVIEW", "downstream_use": False},
    "DESTRUCTIVE": {"epistemic_status": "QUARANTINED", "downstream_use": False},
}

_DESTRUCTIVE_RE = re.compile(
    r"(?:^|_)(drop|purge|wipe|revoke|destroy|delete_all|force_delete|terminate)(?:$|_)",
    re.IGNORECASE,
)
_WRITE_RE = re.compile(
    r"(?:^|_)(create|update|write|send|post|approve|deploy|delete|remove|"
    r"merge|close|assign|submit|publish|modify|set_|add_|run|execute|"
    r"generate|register|install|restart|stop|start)(?:$|_)",
    re.IGNORECASE,
)

# Loaded once at import; per-tool overrides win over name heuristics.
_tool_tier_overrides: dict[str, str] = {}
_raw = os.getenv("FUSIONAL_TOOL_TIERS", "").strip()
if _raw:
    try:
        _tool_tier_overrides = {k: v.upper() for k, v in json.loads(_raw).items()}
    except json.JSONDecodeError:
        logger.warning("epistemics.bad_env FUSIONAL_TOOL_TIERS ignored (invalid JSON)")


def classify_tool(tool_name: str) -> str:
    """Return the tier (READONLY | WRITE | DESTRUCTIVE) for a proxied tool."""
    override = _tool_tier_overrides.get(tool_name)
    if override in STATUS_MAP:
        return override
    if _DESTRUCTIVE_RE.search(tool_name):
        return "DESTRUCTIVE"
    if _WRITE_RE.search(tool_name):
        return "WRITE"
    return "READONLY"


def result_sha256(result: Any) -> str:
    """Stable SHA-256 digest of a tool result (canonical JSON, sorted keys)."""
    if not isinstance(result, str):
        result = json.dumps(result, sort_keys=True, default=str)
    return hashlib.sha256(result.strip().encode("utf-8")).hexdigest()


def wrap_result(tool_name: str, content: Any) -> dict:
    """Attach the epistemic envelope to a proxied tool result.

    *content* is the original MCP content list; it is returned unchanged under
    "content" so existing clients see no schema break.  The envelope rides
    alongside it under "epistemic".
    """
    tier = classify_tool(tool_name)
    meta = STATUS_MAP[tier]
    envelope = {
        "content": content,
        "epistemic": {
            "tool": tool_name,
            "tier": tier,
            "sha256": result_sha256(content),
            "epistemic_status": meta["epistemic_status"],
            "downstream_use": meta["downstream_use"],
            "graph_mutation_authorized": False,
            "human_review_required": tier != "READONLY",
        },
    }
    logger.debug(
        "epistemics.tag tool=%s tier=%s sha256=%s",
        tool_name, tier, envelope["epistemic"]["sha256"][:16],
    )
    return envelope
