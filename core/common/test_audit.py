"""Tests for core/common/audit.py."""

import csv
import io
import json
from datetime import datetime, timezone, timedelta

import pytest

from audit import (
    AuditRecord,
    AuditStore,
    get_audit_store,
    record_tool_call,
    records_to_json,
    records_to_csv,
    _parse_utc,
    _as_utc,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_record(**kwargs) -> AuditRecord:
    defaults = dict(
        timestamp=datetime.now(timezone.utc).isoformat(),
        tool="execute_code",
        status="success",
        duration_ms=42.0,
    )
    defaults.update(kwargs)
    return AuditRecord(**defaults)


# ---------------------------------------------------------------------------
# AuditRecord
# ---------------------------------------------------------------------------

class TestAuditRecord:
    def test_required_fields(self):
        rec = _make_record()
        assert rec.tool == "execute_code"
        assert rec.status == "success"
        assert rec.duration_ms == 42.0

    def test_optional_fields_default_to_empty_string(self):
        rec = _make_record()
        assert rec.request_id == ""
        assert rec.trace_id == ""
        assert rec.span_id == ""
        assert rec.error == ""

    def test_error_status(self):
        rec = _make_record(status="error", error="timeout")
        assert rec.status == "error"
        assert rec.error == "timeout"

    def test_model_dump_includes_all_columns(self):
        rec = _make_record(request_id="req-1", trace_id="abc", span_id="def")
        data = rec.model_dump()
        for key in ("timestamp", "tool", "status", "duration_ms", "request_id", "trace_id", "span_id", "error"):
            assert key in data


# ---------------------------------------------------------------------------
# AuditStore
# ---------------------------------------------------------------------------

class TestAuditStore:
    def test_append_and_len(self):
        store = AuditStore(max_records=100)
        store.append(_make_record())
        assert len(store) == 1

    def test_evicts_oldest_when_max_exceeded(self):
        store = AuditStore(max_records=3)
        for i in range(5):
            store.append(_make_record(tool=f"tool_{i}"))
        assert len(store) == 3
        # The three newest tools survive
        tools = [r.tool for r in store.query()]
        assert tools == ["tool_2", "tool_3", "tool_4"]

    def test_query_no_filter_returns_all(self):
        store = AuditStore()
        store.append(_make_record(tool="a"))
        store.append(_make_record(tool="b"))
        assert len(store.query()) == 2

    def test_query_with_start_filter(self):
        store = AuditStore()
        past = datetime(2025, 1, 1, tzinfo=timezone.utc)
        future = datetime(2027, 1, 1, tzinfo=timezone.utc)
        store.append(_make_record(timestamp=past.isoformat()))
        store.append(_make_record(timestamp=future.isoformat()))
        results = store.query(start=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert len(results) == 1
        assert _parse_utc(results[0].timestamp) == future

    def test_query_with_end_filter(self):
        store = AuditStore()
        past = datetime(2025, 1, 1, tzinfo=timezone.utc)
        future = datetime(2027, 1, 1, tzinfo=timezone.utc)
        store.append(_make_record(timestamp=past.isoformat()))
        store.append(_make_record(timestamp=future.isoformat()))
        results = store.query(end=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert len(results) == 1
        assert _parse_utc(results[0].timestamp) == past

    def test_query_with_start_and_end_filter(self):
        store = AuditStore()
        timestamps = [
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2027, 1, 1, tzinfo=timezone.utc),
        ]
        for ts in timestamps:
            store.append(_make_record(timestamp=ts.isoformat()))
        results = store.query(
            start=datetime(2025, 6, 1, tzinfo=timezone.utc),
            end=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert len(results) == 1
        assert _parse_utc(results[0].timestamp) == timestamps[1]

    def test_query_empty_store_returns_empty_list(self):
        store = AuditStore()
        assert store.query() == []

    def test_query_empty_store_with_range_returns_empty_list(self):
        store = AuditStore()
        results = store.query(
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        assert results == []

    def test_query_with_no_matching_range_returns_empty_list(self):
        store = AuditStore()
        store.append(_make_record(timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat()))
        results = store.query(
            start=datetime(2030, 1, 1, tzinfo=timezone.utc),
            end=datetime(2030, 12, 31, tzinfo=timezone.utc),
        )
        assert results == []

    def test_inclusive_bounds(self):
        store = AuditStore()
        ts = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        store.append(_make_record(timestamp=ts.isoformat()))
        # Exact match on start bound
        assert len(store.query(start=ts)) == 1
        # Exact match on end bound
        assert len(store.query(end=ts)) == 1
        # Both bounds equal timestamp
        assert len(store.query(start=ts, end=ts)) == 1

    def test_persist_writes_to_file(self, tmp_path):
        path = tmp_path / "audit.ndjson"
        store = AuditStore(max_records=100)
        store._store_path = str(path)
        store.append(_make_record(tool="persist_test"))
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["tool"] == "persist_test"

    def test_persist_is_skipped_when_no_path(self, tmp_path):
        store = AuditStore(max_records=100)
        store._store_path = None  # explicitly disabled
        store.append(_make_record(tool="no_persist"))
        # Nothing written — no exception raised

    def test_thread_safety_under_concurrent_writes(self):
        import threading

        store = AuditStore(max_records=5000)
        errors: list[Exception] = []

        def _writer():
            for _ in range(100):
                try:
                    store.append(_make_record())
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=_writer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(store) == 1000


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

class TestRecordToolCall:
    def test_records_success(self, monkeypatch):
        store = AuditStore()
        import audit as _audit_mod
        monkeypatch.setattr(_audit_mod, "_store", store)

        record_tool_call("my_tool", "success", 12.5, request_id="req-99")
        assert len(store) == 1
        rec = store.query()[0]
        assert rec.tool == "my_tool"
        assert rec.status == "success"
        assert rec.duration_ms == 12.5
        assert rec.request_id == "req-99"
        assert rec.error == ""

    def test_records_error(self, monkeypatch):
        store = AuditStore()
        import audit as _audit_mod
        monkeypatch.setattr(_audit_mod, "_store", store)

        record_tool_call("my_tool", "error", 5.0, error="something failed")
        rec = store.query()[0]
        assert rec.status == "error"
        assert rec.error == "something failed"

    def test_timestamp_is_utc_iso(self, monkeypatch):
        store = AuditStore()
        import audit as _audit_mod
        monkeypatch.setattr(_audit_mod, "_store", store)

        record_tool_call("t", "success", 1.0)
        ts = datetime.fromisoformat(store.query()[0].timestamp)
        assert ts.tzinfo is not None


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

class TestRecordsToJson:
    def test_empty_returns_empty_array(self):
        result = records_to_json([])
        assert json.loads(result) == []

    def test_single_record(self):
        rec = _make_record(tool="json_tool", status="success", duration_ms=7.5)
        data = json.loads(records_to_json([rec]))
        assert len(data) == 1
        assert data[0]["tool"] == "json_tool"
        assert data[0]["duration_ms"] == 7.5

    def test_multiple_records(self):
        recs = [_make_record(tool=f"tool_{i}") for i in range(5)]
        data = json.loads(records_to_json(recs))
        assert len(data) == 5

    def test_all_columns_present(self):
        rec = _make_record(
            request_id="r1", trace_id="t1", span_id="s1", error="e1"
        )
        data = json.loads(records_to_json([rec]))[0]
        for col in ("timestamp", "tool", "status", "duration_ms", "request_id", "trace_id", "span_id", "error"):
            assert col in data


class TestRecordsToCsv:
    def _parse_csv(self, text: str) -> list[dict]:
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)

    def test_empty_returns_header_only(self):
        result = records_to_csv([])
        rows = self._parse_csv(result)
        assert rows == []
        # Header line must still be present
        assert "timestamp" in result

    def test_header_columns(self):
        result = records_to_csv([])
        header_line = result.splitlines()[0]
        expected = "timestamp,tool,status,duration_ms,request_id,trace_id,span_id,error"
        assert header_line == expected

    def test_single_record(self):
        rec = _make_record(tool="csv_tool", status="error", duration_ms=3.14, error="oops")
        rows = self._parse_csv(records_to_csv([rec]))
        assert len(rows) == 1
        assert rows[0]["tool"] == "csv_tool"
        assert rows[0]["status"] == "error"
        assert rows[0]["error"] == "oops"

    def test_multiple_records(self):
        recs = [_make_record(tool=f"t{i}") for i in range(3)]
        rows = self._parse_csv(records_to_csv(recs))
        assert len(rows) == 3
        assert [r["tool"] for r in rows] == ["t0", "t1", "t2"]

    def test_all_columns_present(self):
        rec = _make_record(
            request_id="r1", trace_id="t1", span_id="s1",
        )
        rows = self._parse_csv(records_to_csv([rec]))
        for col in ("timestamp", "tool", "status", "duration_ms", "request_id", "trace_id", "span_id", "error"):
            assert col in rows[0]


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

class TestDatetimeHelpers:
    def test_parse_utc_with_timezone_info(self):
        ts = "2026-06-01T12:00:00+00:00"
        dt = _parse_utc(ts)
        assert dt.tzinfo is not None

    def test_parse_utc_naive_becomes_utc(self):
        ts = "2026-06-01T12:00:00"
        dt = _parse_utc(ts)
        assert dt.tzinfo == timezone.utc

    def test_as_utc_naive_becomes_utc(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        aware = _as_utc(naive)
        assert aware.tzinfo == timezone.utc

    def test_as_utc_aware_unchanged(self):
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert _as_utc(aware) is aware


# ---------------------------------------------------------------------------
# get_audit_store singleton
# ---------------------------------------------------------------------------

def test_get_audit_store_returns_same_instance():
    s1 = get_audit_store()
    s2 = get_audit_store()
    assert s1 is s2
