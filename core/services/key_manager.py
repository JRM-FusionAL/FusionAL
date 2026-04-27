"""
services/key_manager.py
Tenant-scoped API key lifecycle manager for FusionAL gateway.

Responsibilities:
  - Issue keys (returns raw key once, stores only hash)
  - Validate key + tenant scope on every request
  - Revoke keys with immediate effect
  - Append-only audit log for all revocation events
"""

import hashlib
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from models.api_key import TenantAPIKey

logger = logging.getLogger("fusional.key_manager")

# ---------------------------------------------------------------------------
# Config — override via env vars if needed
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("FUSIONAL_KEYS_DB", "/data/fusional/keys.db")
AUDIT_LOG_PATH = os.getenv("FUSIONAL_AUDIT_LOG", "/data/fusional/audit.log")
KEY_PREFIX = "fal_"   # FusionAL key prefix — makes keys identifiable in logs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash(raw_key: str) -> str:
    """SHA-256 hash of a raw key. Only this value is persisted."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _audit(event: str, tenant_id: str, key_hash: str, actor: Optional[str] = None) -> None:
    """Append a single audit event to the audit log. Never raises."""
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        actor_str = f" actor={actor}" if actor else ""
        line = f"{ts} {event} tenant={tenant_id} hash={key_hash[:12]}...{actor_str}\n"
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(line)
        logger.info(line.strip())
    except Exception as exc:
        logger.error("audit log write failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Idempotent schema init. Call once on gateway startup.
    Also handled by migrations/001_api_keys.sql — this is the in-process fallback.
    """
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key_hash    TEXT PRIMARY KEY,
                tenant_id   TEXT NOT NULL,
                label       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                revoked_at  TEXT,
                revoked_by  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tenant ON api_keys(tenant_id);
        """)
    logger.info("key_manager: DB initialised at %s", DB_PATH)


def issue_key(tenant_id: str, label: str) -> str:
    """
    Generate and persist a new tenant-scoped API key.

    Returns the raw key exactly ONCE. The caller must deliver it securely —
    FusionAL stores only the hash from this point forward.

    Args:
        tenant_id: Unique tenant identifier (e.g. "acme-corp")
        label:     Human-readable label (e.g. "acme-prod-key-1")

    Returns:
        Raw API key string (prefix + 40 hex chars)
    """
    raw_key = KEY_PREFIX + secrets.token_hex(20)
    h = _hash(raw_key)
    now = datetime.now(timezone.utc).isoformat()

    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO api_keys (key_hash, tenant_id, label, created_at) VALUES (?, ?, ?, ?)",
            (h, tenant_id, label, now),
        )

    _audit("KEY_ISSUED", tenant_id, h)
    logger.info("Issued key for tenant=%s label=%s", tenant_id, label)
    return raw_key


def validate_key(raw_key: str, tenant_id: str) -> bool:
    """
    Validate a raw key against the expected tenant scope.

    - Returns False (and logs) if the key is revoked.
    - Returns False if the key doesn't exist or belongs to a different tenant.
    - Revocation is checked on every call — effect is immediate after revoke_key().

    Args:
        raw_key:   The key from the request header
        tenant_id: The tenant claimed by the request header

    Returns:
        True if valid and active, False otherwise
    """
    h = _hash(raw_key)

    with _get_conn() as conn:
        row = conn.execute(
            "SELECT revoked_at FROM api_keys WHERE key_hash = ? AND tenant_id = ?",
            (h, tenant_id),
        ).fetchone()

    if row is None:
        logger.warning("validate_key: unknown key or tenant mismatch tenant=%s", tenant_id)
        return False

    if row["revoked_at"] is not None:
        _audit("REVOKED_KEY_ATTEMPT", tenant_id, h)
        return False

    return True


def revoke_key(raw_key: str, revoked_by: str) -> bool:
    """
    Revoke a key immediately. Effect is synchronous — the next call to
    validate_key() with this key will return False.

    Args:
        raw_key:    The raw key to revoke
        revoked_by: Identifier of the actor performing revocation (for audit)

    Returns:
        True if the key was found and revoked, False if not found or already revoked
    """
    h = _hash(raw_key)
    now = datetime.now(timezone.utc).isoformat()

    with _get_conn() as conn:
        # Only update if not already revoked
        cur = conn.execute(
            "UPDATE api_keys SET revoked_at = ?, revoked_by = ? "
            "WHERE key_hash = ? AND revoked_at IS NULL",
            (now, revoked_by, h),
        )
        tenant_row = conn.execute(
            "SELECT tenant_id FROM api_keys WHERE key_hash = ?", (h,)
        ).fetchone()

    if cur.rowcount == 0:
        logger.warning("revoke_key: key not found or already revoked hash=%s", h[:12])
        return False

    tenant_id = tenant_row["tenant_id"] if tenant_row else "unknown"
    _audit("KEY_REVOKED", tenant_id, h, actor=revoked_by)
    logger.info("Key revoked tenant=%s by=%s", tenant_id, revoked_by)
    return True


def list_keys(tenant_id: str) -> list[TenantAPIKey]:
    """
    Return all key records for a tenant (active and revoked).
    Never returns raw key values — only metadata.
    """
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT key_hash, tenant_id, label, created_at, revoked_at, revoked_by "
            "FROM api_keys WHERE tenant_id = ? ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
    return [TenantAPIKey.from_row(tuple(r)) for r in rows]


def get_key_info(raw_key: str) -> Optional[TenantAPIKey]:
    """Lookup metadata for a raw key without validating or logging."""
    h = _hash(raw_key)
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT key_hash, tenant_id, label, created_at, revoked_at, revoked_by "
            "FROM api_keys WHERE key_hash = ?",
            (h,),
        ).fetchone()
    return TenantAPIKey.from_row(tuple(row)) if row else None
