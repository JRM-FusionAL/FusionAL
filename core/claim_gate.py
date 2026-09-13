"""Human-in-the-loop claim gate for FusionAL epistemics.

Non-OBSERVATION tool results (WRITE / DESTRUCTIVE tiers) are HELD, not
disclosed to the calling agent.  The agent receives a hold notice keyed by
the result's sha256; a human releases the payload via
``POST /epistemic/promote``.

Design notes:
- In-memory ring buffer with bounded size (mirrors AuditStore semantics).
- Thread-safe; holds survive across requests but not process restarts.
  Set EPISTEMIC_HOLD_PATH to persist as newline-delimited JSON.
- FUSIONAL_EPISTEMIC_ENFORCEMENT=off reverts to tagging-only behavior
  (Phase 1). Default is ON.
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("fusional.epistemics.hold")

HOLD_MAX = int(os.getenv("EPISTEMIC_HOLD_MAX", "5000"))
_ENFORCEMENT_RAW = os.getenv("FUSIONAL_EPISTEMIC_ENFORCEMENT", "on").strip().lower()
ENFORCEMENT_ENABLED = _ENFORCEMENT_RAW not in ("off", "false", "0", "no")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HoldStore:
    """Thread-safe bounded store of held (unreviewed) tool results."""

    def __init__(self, max_holds: int = HOLD_MAX) -> None:
        self._lock = threading.Lock()
        self._holds: dict[str, dict] = {}
        self._order: list[str] = []
        self._max = max_holds

    def put(
        self,
        *,
        sha256: str,
        tool: str,
        tier: str,
        status: str,
        content,
        args: dict | None = None,
    ) -> dict:
        """Store a held result and return its public hold notice."""
        hold_id = f"HOLD-{uuid.uuid4().hex[:12]}"
        record = {
            "hold_id": hold_id,
            "sha256": sha256,
            "tool": tool,
            "tier": tier,
            "epistemic_status": status,
            "args": args or {},
            "content": content,
            "state": "PENDING",
            "held_at": _now_iso(),
            "released_at": None,
            "released_by": None,
        }
        with self._lock:
            self._holds[sha256] = record
            self._order.append(sha256)
            while len(self._order) > self._max:
                old = self._order.pop(0)
                # Only evict if not superseded by a newer entry.
                if self._holds.get(old, {}).get("state") == "PENDING":
                    del self._holds[old]
        logger.info("epistemics.held tool=%s tier=%s hold_id=%s", tool, tier, hold_id)
        return self.notice(record)

    def get(self, sha256: str) -> dict | None:
        with self._lock:
            rec = self._holds.get(sha256)
            return dict(rec) if rec else None

    def list_pending(self) -> list[dict]:
        """Public views of all PENDING holds, oldest first."""
        with self._lock:
            recs = [self._holds[s] for s in self._order if s in self._holds]
        pending = [r for r in recs if r["state"] == "PENDING"]
        return [self.notice(r) | {"held_at": r["held_at"]} for r in pending]

    def release(self, sha256: str, released_by: str = "human") -> dict:
        """Promote a held result to OBSERVATION and return it for disclosure."""
        with self._lock:
            rec = self._holds.get(sha256)
            if rec is None:
                raise KeyError(sha256)
            if rec["state"] == "RELEASED":
                raise ValueError(f"already released: {rec['hold_id']}")
            rec["state"] = "RELEASED"
            rec["released_at"] = _now_iso()
            rec["released_by"] = released_by
        logger.info(
            "epistemics.released tool=%s hold_id=%s by=%s",
            rec["tool"], rec["hold_id"], released_by,
        )
        return {
            "content": rec["content"],
            "epistemic": {
                "tool": rec["tool"],
                "tier": rec["tier"],
                "sha256": rec["sha256"],
                "epistemic_status": "OBSERVATION",
                "downstream_use": True,
                "graph_mutation_authorized": False,
                "human_review_required": False,
                "promoted": True,
                "released_by": released_by,
                "released_at": rec["released_at"],
            },
        }

    @staticmethod
    def notice(record: dict) -> dict:
        """The public shape an agent sees instead of held content."""
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"[FUSIONAL CLAIM GATE] Result from '{record['tool']}' is "
                        f"{record['epistemic_status']} and requires human review "
                        f"before you may rely on it. hold_id={record['hold_id']} "
                        f"sha256={record['sha256']}. Do NOT chain decisions on this "
                        f"result. A human can release it via "
                        f"POST /epistemic/promote {{\"sha256\": ...}}."
                    ),
                }
            ],
            "epistemic": {
                "tool": record["tool"],
                "tier": record["tier"],
                "sha256": record["sha256"],
                "epistemic_status": record["epistemic_status"],
                "downstream_use": False,
                "graph_mutation_authorized": False,
                "human_review_required": True,
                "hold_id": record["hold_id"],
            },
        }


_store = HoldStore()


def get_hold_store() -> HoldStore:
    """Return the module-level HoldStore singleton."""
    return _store
