"""Tests for the epistemic claim gate (core/claim_gate.py)."""

import pytest

from .claim_gate import HoldStore, get_hold_store


def _put(store, tool="github_create_issue", tier="WRITE", status="PENDING_REVIEW"):
    """Store one hold and return (notice, secret_text)."""
    return (
        store.put(
            sha256="abc123",
            tool=tool,
            tier=tier,
            status=status,
            content=[{"type": "text", "text": "secret payload"}],
            args={"title": "x"},
        ),
        "secret payload",
    )


class TestHoldStore:

    def test_put_returns_notice_not_content(self):
        store = HoldStore()
        notice, secret = _put(store)
        text = notice["content"][0]["text"]
        assert secret not in text
        assert "[FUSIONAL CLAIM GATE]" in text
        assert notice["epistemic"]["hold_id"]
        assert notice["epistemic"]["downstream_use"] is False

    def test_get_roundtrip(self):
        store = HoldStore()
        _put(store)
        rec = store.get("abc123")
        assert rec is not None
        assert rec["state"] == "PENDING"
        assert rec["content"][0]["text"] == "secret payload"

    def test_release_promotes_to_observation(self):
        store = HoldStore()
        _put(store)
        released = store.release("abc123", released_by="jonathan")
        ep = released["epistemic"]
        assert ep["epistemic_status"] == "OBSERVATION"
        assert ep["downstream_use"] is True
        assert ep["promoted"] is True
        assert ep["released_by"] == "jonathan"
        assert released["content"][0]["text"] == "secret payload"
        # Record now shows RELEASED state.
        assert store.get("abc123")["state"] == "RELEASED"

    def test_release_twice_conflict(self):
        store = HoldStore()
        _put(store)
        store.release("abc123")
        with pytest.raises(ValueError):
            store.release("abc123")

    def test_release_unknown_sha(self):
        with pytest.raises(KeyError):
            HoldStore().release("nonexistent")

    def test_list_pending_excludes_released(self):
        store = HoldStore()
        _put(store)
        assert len(store.list_pending()) == 1
        store.release("abc123")
        assert len(store.list_pending()) == 0

    def test_eviction_bounded(self):
        store = HoldStore(max_holds=5)
        for i in range(10):
            store.put(
                sha256=f"sha-{i}",
                tool=f"tool_{i}",
                tier="WRITE",
                status="PENDING_REVIEW",
                content=[{"type": "text", "text": f"payload-{i}"}],
            )
        pending = store.list_pending()
        assert len(pending) <= 5

    def test_singleton_exists(self):
        assert get_hold_store() is not None


class TestNoticeShape:
    def test_notice_epistemic_fields(self):
        store = HoldStore()
        notice, _ = _put(store, tool="db_drop_table", tier="DESTRUCTIVE", status="QUARANTINED")
        ep = notice["epistemic"]
        assert ep["tier"] == "DESTRUCTIVE"
        assert ep["epistemic_status"] == "QUARANTINED"
        assert ep["graph_mutation_authorized"] is False
        assert ep["human_review_required"] is True
        assert "promote" in notice["content"][0]["text"]
