"""
Policy profile resolution and enforcement for FusionAL's code-execution paths.

Set via FUSIONAL_POLICY_PROFILE: strict / balanced / dev. See table below and
CLAUDE.md. Resolved once at import time and logged loudly if unset or unknown,
since a silent default reads as "nobody decided" to an auditor.
"""

import logging
import os

LOGGER = logging.getLogger("fusional.policy_profiles")

PROFILES = {
    "strict": {"require_docker": True, "timeout": 10, "memory_mb": 64},
    "balanced": {"require_docker": False, "timeout": 15, "memory_mb": 128},
    "dev": {"require_docker": False, "timeout": 30, "memory_mb": 256},
}

DEFAULT_PROFILE = "balanced"


def _resolve_active_profile() -> tuple[str, dict]:
    raw = os.getenv("FUSIONAL_POLICY_PROFILE", "").strip().lower()
    if not raw:
        LOGGER.warning(
            "FUSIONAL_POLICY_PROFILE is not set — defaulting to %r. "
            "Set it explicitly in production so this is a decision, not a fallback.",
            DEFAULT_PROFILE,
        )
        raw = DEFAULT_PROFILE
    elif raw not in PROFILES:
        LOGGER.warning("Unknown FUSIONAL_POLICY_PROFILE=%r — defaulting to %r", raw, DEFAULT_PROFILE)
        raw = DEFAULT_PROFILE
    return raw, PROFILES[raw]


ACTIVE_PROFILE_NAME, ACTIVE_PROFILE = _resolve_active_profile()
LOGGER.info("Active FusionAL policy profile: %s %s", ACTIVE_PROFILE_NAME, ACTIVE_PROFILE)


def enforce_execute_limits(use_docker: bool, timeout: int, memory_mb: int) -> tuple[bool, int, int]:
    """Clamp a requested /execute configuration down to the active profile's ceiling."""
    profile = ACTIVE_PROFILE
    if profile["require_docker"]:
        use_docker = True
    timeout = min(timeout, profile["timeout"])
    memory_mb = min(memory_mb, profile["memory_mb"])
    return use_docker, timeout, memory_mb
