"""
Tests for core/common/rate_limit_presets.py

Covers:
- Preset lookup and fallback
- get_rate_limit() preset integration in security.py
- ErrorBudgetConfig.from_env()
- ErrorBudgetTracker: record, prune, threshold signals, stats, reset
- configure_error_budget_tracking() FastAPI middleware integration
"""

import logging
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import rate_limit_presets as rlp
import security


# ---------------------------------------------------------------------------
# Preset lookup
# ---------------------------------------------------------------------------


def test_presets_contain_expected_profiles():
    assert set(rlp.PRESETS) == {"permissive", "pilot", "production"}


def test_preset_values():
    assert rlp.PRESETS["permissive"].requests_per_window == 120
    assert rlp.PRESETS["pilot"].requests_per_window == 60
    assert rlp.PRESETS["production"].requests_per_window == 30
    for preset in rlp.PRESETS.values():
        assert preset.window_seconds == 60


def test_get_active_preset_defaults_to_pilot(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_PROFILE", raising=False)
    preset = rlp.get_active_preset()
    assert preset.profile == "pilot"


def test_get_active_preset_respects_env(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PROFILE", "production")
    preset = rlp.get_active_preset()
    assert preset.profile == "production"
    assert preset.requests_per_window == 30


def test_get_active_preset_permissive(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PROFILE", "permissive")
    preset = rlp.get_active_preset()
    assert preset.requests_per_window == 120


def test_get_active_preset_unknown_falls_back_to_pilot(monkeypatch, caplog):
    monkeypatch.setenv("RATE_LIMIT_PROFILE", "nonexistent")
    with caplog.at_level(logging.WARNING, logger=rlp.LOGGER_NAME):
        preset = rlp.get_active_preset()
    assert preset.profile == "pilot"
    assert any("unknown_profile" in r.message for r in caplog.records)


def test_preset_description_contains_profile_name():
    for name, preset in rlp.PRESETS.items():
        assert name in preset.description


# ---------------------------------------------------------------------------
# security.get_rate_limit() integration with presets
# ---------------------------------------------------------------------------


def test_get_rate_limit_uses_explicit_env_vars_over_preset(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "10")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "30")
    monkeypatch.setenv("RATE_LIMIT_PROFILE", "permissive")  # should be ignored
    limit, window = security.get_rate_limit()
    assert limit == 10
    assert window == 30


def test_get_rate_limit_falls_back_to_pilot_preset(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_REQUESTS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_WINDOW_SECONDS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PROFILE", raising=False)
    limit, window = security.get_rate_limit()
    assert limit == rlp.PRESETS["pilot"].requests_per_window
    assert window == rlp.PRESETS["pilot"].window_seconds


def test_get_rate_limit_falls_back_to_production_preset(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_REQUESTS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_WINDOW_SECONDS", raising=False)
    monkeypatch.setenv("RATE_LIMIT_PROFILE", "production")
    limit, window = security.get_rate_limit()
    assert limit == rlp.PRESETS["production"].requests_per_window


# ---------------------------------------------------------------------------
# ErrorBudgetConfig
# ---------------------------------------------------------------------------


def test_error_budget_config_defaults():
    cfg = rlp.ErrorBudgetConfig()
    assert cfg.warn_threshold == 0.05
    assert cfg.error_threshold == 0.10
    assert cfg.window_seconds == 300


def test_error_budget_config_from_env(monkeypatch):
    monkeypatch.setenv("ERROR_BUDGET_WARN_THRESHOLD", "0.02")
    monkeypatch.setenv("ERROR_BUDGET_ERROR_THRESHOLD", "0.08")
    monkeypatch.setenv("ERROR_BUDGET_WINDOW_SECONDS", "120")
    cfg = rlp.ErrorBudgetConfig.from_env()
    assert cfg.warn_threshold == pytest.approx(0.02)
    assert cfg.error_threshold == pytest.approx(0.08)
    assert cfg.window_seconds == 120


# ---------------------------------------------------------------------------
# ErrorBudgetTracker: basic behaviour
# ---------------------------------------------------------------------------


def test_tracker_starts_empty():
    tracker = rlp.ErrorBudgetTracker()
    assert tracker.current_error_rate() == 0.0
    stats = tracker.stats()
    assert stats["total_requests"] == 0
    assert stats["error_count"] == 0
    assert stats["error_rate"] == 0.0


def test_tracker_records_successes():
    tracker = rlp.ErrorBudgetTracker()
    for _ in range(5):
        tracker.record(is_error=False)
    assert tracker.current_error_rate() == 0.0
    assert tracker.stats()["total_requests"] == 5


def test_tracker_records_errors():
    tracker = rlp.ErrorBudgetTracker()
    tracker.record(is_error=True)
    tracker.record(is_error=False)
    assert tracker.current_error_rate() == pytest.approx(0.5)


def test_tracker_reset():
    tracker = rlp.ErrorBudgetTracker()
    for _ in range(10):
        tracker.record(is_error=True)
    tracker.reset()
    assert tracker.stats()["total_requests"] == 0
    assert tracker.current_error_rate() == 0.0


# ---------------------------------------------------------------------------
# ErrorBudgetTracker: threshold signals
# ---------------------------------------------------------------------------


def test_tracker_emits_warning_at_warn_threshold(caplog):
    cfg = rlp.ErrorBudgetConfig(warn_threshold=0.05, error_threshold=0.20, window_seconds=300)
    tracker = rlp.ErrorBudgetTracker(config=cfg)

    # 1 error out of 10 = 10 % — above warn (5 %), below error (20 %)
    for _ in range(9):
        tracker.record(is_error=False)

    with caplog.at_level(logging.WARNING, logger=rlp.LOGGER_NAME):
        tracker.record(is_error=True)

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("error_budget.warn" in m for m in warning_messages)
    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert not any("error_budget.exceeded" in m for m in error_messages)


def test_tracker_emits_error_at_error_threshold(caplog):
    cfg = rlp.ErrorBudgetConfig(warn_threshold=0.05, error_threshold=0.10, window_seconds=300)
    tracker = rlp.ErrorBudgetTracker(config=cfg)

    # 1 error out of 10 = 10 % — at error threshold (10 %)
    for _ in range(9):
        tracker.record(is_error=False)

    with caplog.at_level(logging.ERROR, logger=rlp.LOGGER_NAME):
        tracker.record(is_error=True)

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("error_budget.exceeded" in m for m in error_messages)


def test_tracker_no_signal_below_warn_threshold(caplog):
    cfg = rlp.ErrorBudgetConfig(warn_threshold=0.10, error_threshold=0.20, window_seconds=300)
    tracker = rlp.ErrorBudgetTracker(config=cfg)

    # 1 error out of 100 = 1 % — below warn (10 %)
    for _ in range(99):
        tracker.record(is_error=False)

    with caplog.at_level(logging.WARNING, logger=rlp.LOGGER_NAME):
        tracker.record(is_error=True)

    assert not any("error_budget" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# ErrorBudgetTracker: rolling window pruning
# ---------------------------------------------------------------------------


def test_tracker_prunes_old_events(monkeypatch):
    """Events outside the window should be discarded."""
    cfg = rlp.ErrorBudgetConfig(warn_threshold=0.05, error_threshold=0.10, window_seconds=1)
    tracker = rlp.ErrorBudgetTracker(config=cfg)

    # Record an error, then advance time past the window
    tracker.record(is_error=True)
    assert tracker.stats()["total_requests"] == 1

    # Shift existing event timestamps to be older than the window
    tracker._events = [(ts - 2, err) for ts, err in tracker._events]

    # Record a fresh success — prune should remove the stale error
    tracker.record(is_error=False)
    assert tracker.stats()["total_requests"] == 1
    assert tracker.stats()["error_count"] == 0


def test_tracker_stats_keys():
    tracker = rlp.ErrorBudgetTracker()
    stats = tracker.stats()
    expected_keys = {
        "total_requests",
        "error_count",
        "error_rate",
        "warn_threshold",
        "error_threshold",
        "window_seconds",
    }
    assert set(stats.keys()) == expected_keys


# ---------------------------------------------------------------------------
# configure_error_budget_tracking() FastAPI middleware integration
# ---------------------------------------------------------------------------


def test_configure_error_budget_tracking_attaches_tracker():
    app = FastAPI()
    cfg = rlp.ErrorBudgetConfig(warn_threshold=0.05, error_threshold=0.10, window_seconds=300)
    tracker = rlp.configure_error_budget_tracking(app, config=cfg)

    assert app.state.error_budget_tracker is tracker


def test_error_budget_middleware_counts_errors():
    app = FastAPI()
    cfg = rlp.ErrorBudgetConfig(warn_threshold=0.05, error_threshold=0.10, window_seconds=300)
    tracker = rlp.configure_error_budget_tracking(app, config=cfg)

    @app.get("/ok")
    def ok():
        return {"status": "ok"}

    @app.get("/fail")
    def fail():
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="boom")

    client = TestClient(app, raise_server_exceptions=False)
    client.get("/ok")
    client.get("/ok")
    client.get("/fail")

    stats = tracker.stats()
    assert stats["total_requests"] == 3
    assert stats["error_count"] == 1
    assert stats["error_rate"] == pytest.approx(1 / 3)


def test_error_budget_middleware_emits_signal_on_high_error_rate(caplog):
    app = FastAPI()
    cfg = rlp.ErrorBudgetConfig(warn_threshold=0.05, error_threshold=0.30, window_seconds=300)
    rlp.configure_error_budget_tracking(app, config=cfg)

    @app.get("/fail")
    def fail():
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="boom")

    @app.get("/ok")
    def ok():
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)

    # 2 errors out of 5 = 40 % — above error threshold (30 %)
    with caplog.at_level(logging.WARNING, logger=rlp.LOGGER_NAME):
        for _ in range(3):
            client.get("/ok")
        for _ in range(2):
            client.get("/fail")

    assert any("error_budget" in r.message for r in caplog.records)
