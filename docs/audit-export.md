# Audit Export – Operator Guide

FusionAL records every MCP tool invocation in an in-memory audit store and exposes two export endpoints so pilots and compliance conversations can download portable artifacts.

## Audit record schema

Each audit record contains the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string (ISO 8601 UTC) | Time the tool call was recorded |
| `tool` | string | Name of the MCP tool or endpoint (`execute_code`, `generate_and_execute`, `generate_mcp_project`) |
| `status` | string | `"success"` or `"error"` |
| `duration_ms` | number | Wall-clock elapsed time in milliseconds |
| `request_id` | string | Inbound `X-Request-ID` header value (or generated UUID) |
| `trace_id` | string | OpenTelemetry trace ID (empty when tracing is disabled) |
| `span_id` | string | OpenTelemetry span ID (empty when tracing is disabled) |
| `error` | string | Error message on failure; empty on success |

---

## Export endpoints

Both endpoints require the standard `X-API-Key` header when security is enabled.

### JSON export

```
GET /audit/export/json
```

**Query parameters**

| Parameter | Format | Description |
|-----------|--------|-------------|
| `start` | ISO 8601 (optional) | Lower bound (inclusive). Example: `2026-01-01T00:00:00Z` |
| `end` | ISO 8601 (optional) | Upper bound (inclusive). Example: `2026-12-31T23:59:59Z` |

**Response**

`Content-Type: application/json` — a JSON array of audit records.  
Returns `[]` when no records match the requested range.

**Example**

```bash
curl -H "X-API-Key: $API_KEY" \
  "http://localhost:8009/audit/export/json?start=2026-01-01T00:00:00Z&end=2026-12-31T23:59:59Z" \
  -o audit_export.json
```

---

### CSV export

```
GET /audit/export/csv
```

**Query parameters** — same as the JSON endpoint.

**Response**

`Content-Type: text/csv` — a CSV file with a header row and one data row per audit record.  
Returns a header-only file when no records match the requested range.

**CSV columns (in order)**

```
timestamp,tool,status,duration_ms,request_id,trace_id,span_id,error
```

**Example**

```bash
curl -H "X-API-Key: $API_KEY" \
  "http://localhost:8009/audit/export/csv?start=2026-01-01T00:00:00Z" \
  -o audit_export.csv
```

---

## Configuration

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `AUDIT_MAX_RECORDS` | `10000` | Maximum records held in memory. Oldest records are evicted once the limit is reached. |
| `AUDIT_STORE_PATH` | _(empty)_ | Optional file path for newline-delimited JSON persistence. When set, every new record is appended to the file so audit data survives restarts. |

---

## Empty results

- `GET /audit/export/json` returns `[]` (a valid empty JSON array).
- `GET /audit/export/csv` returns a header row with no data rows.

Both behaviours are safe for downstream consumers — no HTTP 4xx errors are raised for empty result sets.

---

## Bounded date ranges (recommended)

Omitting both `start` and `end` returns all records currently in memory.  For large deployments or compliance exports covering a specific period, always supply a bounded range:

```bash
# Export January 2026 only
curl -H "X-API-Key: $API_KEY" \
  "http://localhost:8009/audit/export/json?start=2026-01-01T00:00:00Z&end=2026-01-31T23:59:59Z"
```

---

## Notes

- The audit store is **in-memory only** by default. If the server restarts without `AUDIT_STORE_PATH` set, historical records are lost.
- Audit recording is enabled automatically when `core/common/audit.py` is importable. No additional configuration is required.
- The store is a fixed-size ring buffer. Once `AUDIT_MAX_RECORDS` is reached the oldest records are silently evicted. Size this appropriately for your expected call rate and export frequency.
