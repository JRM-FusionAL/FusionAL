"""
models/api_key.py
Tenant-scoped API key metadata model for FusionAL gateway.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class TenantAPIKey:
    """
    Represents a tenant-scoped API key record.
    Raw keys are never stored — only the SHA-256 hash.
    """
    key_hash: str                          # SHA-256 of raw key
    tenant_id: str                         # e.g. "acme-corp"
    label: str                             # human-readable: "acme-prod-key-1"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None       # audit: who/what triggered revocation

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def to_dict(self) -> dict:
        return {
            "key_hash": self.key_hash,
            "tenant_id": self.tenant_id,
            "label": self.label,
            "created_at": self.created_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revoked_by": self.revoked_by,
            "is_revoked": self.is_revoked,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "TenantAPIKey":
        """Construct from a SQLite row tuple: (key_hash, tenant_id, label, created_at, revoked_at, revoked_by)"""
        key_hash, tenant_id, label, created_at, revoked_at, revoked_by = row
        return cls(
            key_hash=key_hash,
            tenant_id=tenant_id,
            label=label,
            created_at=datetime.fromisoformat(created_at),
            revoked_at=datetime.fromisoformat(revoked_at) if revoked_at else None,
            revoked_by=revoked_by,
        )
