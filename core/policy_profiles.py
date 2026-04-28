"""
FusionAL Policy Profiles

Configures security and execution behaviour for different deployment modes.
Select the active profile by setting the ``FUSIONAL_POLICY_PROFILE`` environment
variable before startup.  The selected profile is logged once at boot so it
always appears in the audit trail.

Profiles
--------
strict   — production hardening: Docker required, lowest limits, sandbox always on
balanced — default staging/production: Docker recommended, moderate limits
dev      — local development: relaxed limits, Docker optional, sandbox optional

Environment variables
---------------------
``FUSIONAL_POLICY_PROFILE``  : one of ``strict``, ``balanced``, ``dev``
                               (default: ``balanced``)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

LOGGER = logging.getLogger("fusional.policy")

# ---------------------------------------------------------------------------
# Profile dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolicyProfile:
    """Immutable execution and security limits for a deployment profile."""

    name: str
    description: str
    max_timeout_seconds: int
    max_memory_mb: int
    require_docker: bool
    force_sandbox: bool
    rate_limit_requests: int
    rate_limit_window_seconds: int

    def summary(self) -> str:
        return (
            f"profile={self.name} "
            f"max_timeout={self.max_timeout_seconds}s "
            f"max_memory={self.max_memory_mb}MB "
            f"require_docker={self.require_docker} "
            f"force_sandbox={self.force_sandbox} "
            f"rate_limit={self.rate_limit_requests}req/{self.rate_limit_window_seconds}s"
        )


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

PROFILES: dict[str, PolicyProfile] = {
    "strict": PolicyProfile(
        name="strict",
        description="Production hardening — Docker required, tightest limits, sandbox always enforced",
        max_timeout_seconds=10,
        max_memory_mb=64,
        require_docker=True,
        force_sandbox=True,
        rate_limit_requests=30,
        rate_limit_window_seconds=60,
    ),
    "balanced": PolicyProfile(
        name="balanced",
        description="Staging/production default — Docker recommended, moderate limits",
        max_timeout_seconds=15,
        max_memory_mb=128,
        require_docker=False,
        force_sandbox=True,
        rate_limit_requests=60,
        rate_limit_window_seconds=60,
    ),
    "dev": PolicyProfile(
        name="dev",
        description="Local development — relaxed limits, Docker optional, sandbox optional",
        max_timeout_seconds=30,
        max_memory_mb=256,
        require_docker=False,
        force_sandbox=False,
        rate_limit_requests=120,
        rate_limit_window_seconds=60,
    ),
}

_DEFAULT_PROFILE = "balanced"

# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def get_active_profile() -> PolicyProfile:
    """Return the active :class:`PolicyProfile` based on ``FUSIONAL_POLICY_PROFILE``.

    Falls back to ``balanced`` if the name is unrecognised and emits a warning.
    """
    name = os.getenv("FUSIONAL_POLICY_PROFILE", _DEFAULT_PROFILE).lower().strip()
    if name not in PROFILES:
        LOGGER.warning(
            "policy.unknown_profile profile=%s available=%s falling_back_to=%s",
            name,
            list(PROFILES),
            _DEFAULT_PROFILE,
        )
        name = _DEFAULT_PROFILE
    return PROFILES[name]


def log_active_profile() -> PolicyProfile:
    """Resolve and log the active profile.  Call once at application startup."""
    profile = get_active_profile()
    LOGGER.info("policy.active %s description=%r", profile.summary(), profile.description)
    return profile
