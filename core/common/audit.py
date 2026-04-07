"""Tool-call audit store for FusionAL.

Tracks each MCP tool invocation with timing and correlation data.
Export recorded audits to JSON or CSV via the /audit/export/* endpoints.

Environment variables:
    AUDIT_MAX_RECORDS  - Maximum records to keep in memory (default: 10 000).
    AUDIT_STORE_PATH   - Optional file path to persist records as
                         newline-delimited JSON.  When set, records are
                         appended on each write so the file survives restarts.
"""

import csv
import io
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger("mcp.audit")

AUDIT_MAX_RECORDS = int(os.getenv("AUDIT_MAX_RECORDS", "10000"))

# Canonical column order for CSV exports
_CSV_COLUMNS = [
    "timestamp",
    "tool",
    "status",
    "duration_ms",
    "request_id",
    "trace_id",
    "span_id",
    "error",
]


class AuditRecord(BaseModel):
    """A single tool-call audit record."""

    timestamp: str      # ISO 8601 UTC
    tool: str           # Tool or endpoint name
    status: str         # "success" | "error"
    duration_ms: float  # Wall-clock elapsed time in milliseconds
    request_id: str = ""  # Inbound X-Request-ID or generated UUID
    trace_id: str = ""    # OpenTelemetry trace ID (empty when unavailable)
    span_id: str = ""     # OpenTelemetry span ID  (empty when unavailable)
    error: str = ""       # Error message; empty on success


class AuditStore:
    """Thread-safe in-memory ring-buffer for audit records.

    Older records are evicted once *max_records* is reached so that memory
    usage stays bounded during long-running deployments.
    """

    def __init__(self, max_records: int = AUDIT_MAX_RECORDS) -> None:
        self._lock = threading.Lock()
        self._records: list[AuditRecord] = []
        self._max = max_records
        self._store_path: Optional[str] = os.getenv("AUDIT_STORE_PATH", "").strip() or None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, record: AuditRecord) -> None:
        """Add *record* to the store, evicting the oldest entry if needed."""
        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max:
                self._records = self._records[-self._max :]
        self._persist(record)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[AuditRecord]:
        """Return records whose timestamps fall within [*start*, *end*].

        Both bounds are inclusive and optional.  Naive datetimes are treated
        as UTC.
        """
        with self._lock:
            records = list(self._records)

        if start is None and end is None:
            return records

        result: list[AuditRecord] = []
        for rec in records:
            ts = _parse_utc(rec.timestamp)
            if start is not None and ts < _as_utc(start):
                continue
            if end is not None and ts > _as_utc(end):
                continue
            result.append(rec)
        return result

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _persist(self, record: AuditRecord) -> None:
        if not self._store_path:
            return
        try:
            with open(self._store_path, "a", encoding="utf-8") as fh:
                fh.write(record.model_dump_json() + "\n")
        except OSError as exc:
            logger.warning("audit.persist_failed path=%s error=%s", self._store_path, exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store = AuditStore()


def get_audit_store() -> AuditStore:
    """Return the module-level AuditStore singleton."""
    return _store


def record_tool_call(
    tool: str,
    status: str,
    duration_ms: float,
    *,
    request_id: str = "",
    trace_id: str = "",
    span_id: str = "",
    error: str = "",
) -> None:
    """Append one tool-call audit record to the singleton store."""
    rec = AuditRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        tool=tool,
        status=status,
        duration_ms=round(duration_ms, 2),
        request_id=request_id,
        trace_id=trace_id,
        span_id=span_id,
        error=error,
    )
    _store.append(rec)
    logger.debug(
        "audit.tool_call tool=%s status=%s duration_ms=%.2f request_id=%s",
        tool,
        status,
        duration_ms,
        request_id,
    )


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------


def records_to_json(records: list[AuditRecord]) -> str:
    """Serialise *records* as a JSON array string."""
    return json.dumps([r.model_dump() for r in records], indent=2)


def records_to_csv(records: list[AuditRecord]) -> str:
    """Serialise *records* as a CSV string with a header row."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for rec in records:
        writer.writerow(rec.model_dump())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_utc(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a UTC-aware datetime."""
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Return *dt* with UTC timezone info, treating naive datetimes as UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
