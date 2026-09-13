"""Tests for the epistemic envelope engine (core/epistemics.py)."""

import pytest

from .epistemics import STATUS_MAP, classify_tool, result_sha256, wrap_result


class TestClassifyTool:
    def test_readonly_default(self):
        assert classify_tool("recall_search") == "READONLY"
        assert classify_tool("bi_nl_query") == "READONLY"

    @pytest.mark.parametrize(
        "name",
        [
            "github_delete_issue",
            "content_remove_page",
            "api_send_email",
            "github_create_issue",
            "github_merge_pr",
            "content_post_article",
            "deploy_update_service",
            "kb_approve_draft",
        ],
    )
    def test_write_verbs(self, name):
        assert classify_tool(name) == "WRITE"

    @pytest.mark.parametrize(
        "name",
        [
            "db_drop_table",
            "cache_purge_all",
            "fs_wipe_disk",
            "auth_revoke_token",
            "vm_terminate_instance",
        ],
    )
    def test_destructive_verbs(self, name):
        assert classify_tool(name) == "DESTRUCTIVE"

    def test_write_verb_not_read_as_destructive(self):
        # "delete" is WRITE; "delete_all"/"force_delete" are DESTRUCTIVE.
        assert classify_tool("github_delete_issue") == "WRITE"
        assert classify_tool("github_force_delete_branch") == "DESTRUCTIVE"

    def test_env_override_wins(self, monkeypatch):
        import json as _json
        monkeypatch.setattr(
            "core.epistemics._tool_tier_overrides",
            _json.loads('{"recall_search": "DESTRUCTIVE"}'),
        )
        assert classify_tool("recall_search") == "DESTRUCTIVE"


class TestResultSha256:
    def test_stable_across_key_order(self):
        a = result_sha256({"b": 1, "a": 2})
        b = result_sha256({"a": 2, "b": 1})
        assert a == b

    def test_known_vector(self):
        assert (
            result_sha256("hello")
            == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        )

    def test_non_string_input(self):
        assert result_sha256({"x": 1}) == result_sha256('{"x": 1}')


class TestWrapResult:
    def _content(self, text="ok"):
        return {"content": [{"type": "text", "text": text}]}

    def test_readonly_envelope(self):
        out = wrap_result("recall_search", self._content())
        ep = out["epistemic"]
        assert ep["tier"] == "READONLY"
        assert ep["epistemic_status"] == "OBSERVATION"
        assert ep["downstream_use"] is True
        assert ep["human_review_required"] is False
        assert ep["graph_mutation_authorized"] is False
        assert len(ep["sha256"]) == 64

    def test_write_envelope(self):
        out = wrap_result("github_create_issue", self._content())
        ep = out["epistemic"]
        assert ep["tier"] == "WRITE"
        assert ep["epistemic_status"] == "PENDING_REVIEW"
        assert ep["downstream_use"] is False
        assert ep["human_review_required"] is True

    def test_destructive_envelope(self):
        out = wrap_result("db_drop_table", self._content())
        ep = out["epistemic"]
        assert ep["tier"] == "DESTRUCTIVE"
        assert ep["epistemic_status"] == "QUARANTINED"
        assert ep["downstream_use"] is False

    def test_original_payload_preserved(self):
        content = [{"type": "text", "text": "payload intact"}]
        out = wrap_result("bi_nl_query", content)
        assert out["content"] == content

    def test_sha_matches_payload(self):
        raw = self._content("deterministic")
        out = wrap_result("bi_nl_query", raw)
        assert out["epistemic"]["sha256"] == result_sha256(raw)

    def test_all_statuses_defined(self):
        assert set(STATUS_MAP) == {"READONLY", "WRITE", "DESTRUCTIVE"}
