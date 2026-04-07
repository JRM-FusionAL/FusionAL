"""
FusionAL Rate-Limit Presets and Error-Budget Guardrails

Provides opinionated rate-limit profiles for different deployment modes
and a rolling-window error-budget tracker that emits structured log signals
when error rates breach configured thresholds.

Profiles
--------
- ``permissive`` — local development; high throughput, minimal friction
- ``pilot``      — staging / controlled rollout; moderate limits (default)
- ``production`` — full production; conservative, safest defaults

Error-budget
------------
The ``ErrorBudgetTracker`` maintains a rolling time-window of request outcomes.
When the observed error rate crosses ``warn_threshold`` or ``error_threshold``
it emits a structured WARNING or ERROR log respectively, giving operators an
early signal before SLO burn-rate becomes critical.

Environment variables
---------------------
``RATE_LIMIT_PROFILE``            : preset profile name (default: ``pilot``)
``ERROR_BUDGET_WARN_THRESHOLD``   : fractional warn level, e.g. ``0.05`` (default)
``ERROR_BUDGET_ERROR_THRESHOLD``  : fractional alert level, e.g. ``0.10`` (default)
``ERROR_BUDGET_WINDOW_SECONDS``   : rolling window size in seconds (default: ``300``)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI, Request, Response

LOGGER_NAME = "fusional.reliability"

# ---------------------------------------------------------------------------
# Rate-limit presets
# ---------------------------------------------------------------------------

_PRESETS_DOC = {
    "permissive": "local dev — high throughput, minimal friction",
    "pilot": "staging / controlled rollout — moderate protection",
    "production": "full production — conservative defaults",
}


@dataclass(frozen=True)
class RateLimitPreset:
    """Immutable rate-limit configuration for a deployment profile."""

    requests_per_window: int
    window_seconds: int
    profile: str = "pilot"

    @property
    def description(self) -> str:
        label = _PRESETS_DOC.get(self.profile, self.profile)
        return f"{self.profile}: {self.requests_per_window} req/{self.window_seconds}s ({label})"


PRESETS: dict[str, RateLimitPreset] = {
    "permissive": RateLimitPreset(
        requests_per_window=120, window_seconds=60, profile="permissive"
    ),
    "pilot": RateLimitPreset(
        requests_per_window=60, window_seconds=60, profile="pilot"
    ),
    "production": RateLimitPreset(
        requests_per_window=30, window_seconds=60, profile="production"
    ),
}

_DEFAULT_PROFILE = "pilot"


def get_active_preset() -> RateLimitPreset:
    """Return the active ``RateLimitPreset`` based on ``RATE_LIMIT_PROFILE`` env var.

    Falls back to ``pilot`` if the profile name is unrecognised and logs a
    warning so operators can spot misconfiguration early.
    """
    profile = os.getenv("RATE_LIMIT_PROFILE", _DEFAULT_PROFILE).lower().strip()
    if profile not in PRESETS:
        _logger().warning(
            "rate_limit.unknown_profile profile=%s available=%s falling_back_to=%s",
            profile,
            list(PRESETS),
            _DEFAULT_PROFILE,
        )
        profile = _DEFAULT_PROFILE
    preset = PRESETS[profile]
    _logger().debug("rate_limit.preset_active profile=%s %s", profile, preset.description)
    return preset


# ---------------------------------------------------------------------------
# Error-budget configuration and tracker
# ---------------------------------------------------------------------------


@dataclass
class ErrorBudgetConfig:
    """Thresholds for the error-budget guardrail."""

    warn_threshold: float = 0.05
    """Fraction of requests that may fail before a WARNING is emitted (default 5 %)."""

    error_threshold: float = 0.10
    """Fraction of requests that may fail before an ERROR is emitted (default 10 %)."""

    window_seconds: int = 300
    """Rolling observation window in seconds (default 5 min)."""

    @classmethod
    def from_env(cls) -> ErrorBudgetConfig:
        """Build config from environment variables."""
        return cls(
            warn_threshold=float(
                os.getenv("ERROR_BUDGET_WARN_THRESHOLD", "0.05")
            ),
            error_threshold=float(
                os.getenv("ERROR_BUDGET_ERROR_THRESHOLD", "0.10")
            ),
            window_seconds=int(
                os.getenv("ERROR_BUDGET_WINDOW_SECONDS", "300")
            ),
        )


class ErrorBudgetTracker:
    """Rolling-window error-budget tracker.

    Records request outcomes and emits structured log signals when the
    observed error rate within the rolling window breaches configured
    thresholds.

    Usage
    -----
    Instantiate once at application startup (or per-test) and call
    :meth:`record` for every request, passing ``is_error=True`` for any
    response with a 5xx status code (or any outcome your SLO considers an
    error).

    Example::

        tracker = ErrorBudgetTracker()
        tracker.record(is_error=response.status_code >= 500)
        stats = tracker.stats()
    """

    def __init__(self, config: ErrorBudgetConfig | None = None) -> None:
        self._config = config or ErrorBudgetConfig.from_env()
        # List of (timestamp_float, is_error_bool) tuples
        self._events: list[tuple[float, bool]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, *, is_error: bool) -> None:
        """Record a single request outcome and check budget thresholds."""
        now = time.monotonic()
        self._events.append((now, is_error))
        self._prune(now)
        self._check_budget()

    def current_error_rate(self) -> float:
        """Return error rate in ``[0.0, 1.0]`` for the current window."""
        self._prune(time.monotonic())
        if not self._events:
            return 0.0
        error_count = sum(1 for _, err in self._events if err)
        return error_count / len(self._events)

    def stats(self) -> dict:
        """Return a snapshot of current budget statistics.

        Returns
        -------
        dict with keys:
            total_requests, error_count, error_rate,
            warn_threshold, error_threshold, window_seconds
        """
        self._prune(time.monotonic())
        total = len(self._events)
        error_count = sum(1 for _, err in self._events if err)
        return {
            "total_requests": total,
            "error_count": error_count,
            "error_rate": error_count / total if total else 0.0,
            "warn_threshold": self._config.warn_threshold,
            "error_threshold": self._config.error_threshold,
            "window_seconds": self._config.window_seconds,
        }

    def reset(self) -> None:
        """Clear all recorded events (useful in tests)."""
        self._events = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prune(self, now: float) -> None:
        cutoff = now - self._config.window_seconds
        self._events = [(ts, err) for ts, err in self._events if ts >= cutoff]

    def _check_budget(self) -> None:
        total = len(self._events)
        if total == 0:
            return
        error_count = sum(1 for _, err in self._events if err)
        rate = error_count / total

        if rate >= self._config.error_threshold:
            _logger().error(
                "error_budget.exceeded "
                "rate=%.4f threshold=%.4f errors=%d total=%d window_seconds=%d",
                rate,
                self._config.error_threshold,
                error_count,
                total,
                self._config.window_seconds,
            )
        elif rate >= self._config.warn_threshold:
            _logger().warning(
                "error_budget.warn "
                "rate=%.4f threshold=%.4f errors=%d total=%d window_seconds=%d",
                rate,
                self._config.warn_threshold,
                error_count,
                total,
                self._config.window_seconds,
            )


# ---------------------------------------------------------------------------
# FastAPI integration helpers
# ---------------------------------------------------------------------------


def configure_error_budget_tracking(
    app: "FastAPI",
    config: ErrorBudgetConfig | None = None,
) -> ErrorBudgetTracker:
    """Attach an ``ErrorBudgetTracker`` to *app* and register middleware.

    The tracker is stored as ``app.state.error_budget_tracker`` so it can be
    inspected or reset in tests.

    Returns the attached :class:`ErrorBudgetTracker` for convenience.
    """
    tracker = ErrorBudgetTracker(config=config)
    app.state.error_budget_tracker = tracker

    @app.middleware("http")
    async def _error_budget_middleware(request: "Request", call_next: object):
        from fastapi import Response  # local import to avoid circular deps

        response: Response = await call_next(request)  # type: ignore[misc]
        is_error = response.status_code >= 500
        tracker.record(is_error=is_error)
        return response

    return tracker


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
