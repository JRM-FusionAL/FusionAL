-- migrations/001_api_keys.sql
-- Tenant-scoped API key store for FusionAL gateway.
-- Run once on first deploy. Safe to re-run (IF NOT EXISTS guards).

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash    TEXT PRIMARY KEY,      -- SHA-256 of raw key — never store plaintext
    tenant_id   TEXT NOT NULL,         -- tenant this key belongs to
    label       TEXT NOT NULL,         -- human-readable: "acme-prod-key-1"
    created_at  TEXT NOT NULL,         -- ISO-8601 UTC timestamp
    revoked_at  TEXT,                  -- NULL = active; set = revoked
    revoked_by  TEXT                   -- audit: actor that triggered revocation
);

-- Fast lookup by tenant (list_keys, admin UI)
CREATE INDEX IF NOT EXISTS idx_tenant ON api_keys(tenant_id);

-- Fast lookup of active keys by tenant (validate_key hot path)
CREATE INDEX IF NOT EXISTS idx_tenant_active
    ON api_keys(tenant_id)
    WHERE revoked_at IS NULL;
