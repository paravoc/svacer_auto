"""Tests for select_fields and apply_limit."""
from svacer_mcp.utils.response import (
    select_fields,
    apply_limit,
    COMPACT_FIELDS,
)


FULL_MARKER = {
    "id": "m1",
    "warnClass": "DEREF_AFTER_NULL",
    "file": "src/main.c",
    "line": 42,
    "msg": "null deref",
    "function": "main",
    "tool": "svace",
    "mtid": "deref-001",
    "review": {"status": "Confirmed", "severity": "Critical"},
    "traces": [{"file": "src/main.c", "line": 40}],
    "checkerInfo": {"cwe": "CWE-476"},
    "review_history": [{"status": "Unclear"}],
    "comments": [{"text": "looks real"}],
}


class TestSelectFields:
    def test_default_returns_compact_preset(self):
        marker = {k: FULL_MARKER[k] for k in COMPACT_FIELDS}
        result = select_fields(marker, None)
        assert set(result.keys()) == set(COMPACT_FIELDS)

    def test_default_keeps_optional_fields_when_present(self):
        marker = {**{k: FULL_MARKER[k] for k in COMPACT_FIELDS}, "traces": FULL_MARKER["traces"]}
        result = select_fields(marker, None)
        assert "traces" in result
        assert "checkerInfo" not in result
        assert "review_history" not in result

    def test_default_drops_tool_and_mtid(self):
        result = select_fields(FULL_MARKER, None)
        assert "tool" not in result
        assert "mtid" not in result

    def test_star_returns_full_marker(self):
        result = select_fields(FULL_MARKER, ["*"])
        assert result == FULL_MARKER

    def test_star_mixed_with_other_keys_still_returns_full(self):
        result = select_fields(FULL_MARKER, ["id", "*"])
        assert result == FULL_MARKER

    def test_explicit_whitelist(self):
        result = select_fields(FULL_MARKER, ["id", "warnClass"])
        assert result == {"id": "m1", "warnClass": "DEREF_AFTER_NULL"}

    def test_explicit_whitelist_drops_missing_keys(self):
        result = select_fields({"id": "m1"}, ["id", "warnClass", "file"])
        assert result == {"id": "m1"}

    def test_review_kept_as_whole_object(self):
        result = select_fields(FULL_MARKER, ["review"])
        assert result == {"review": FULL_MARKER["review"]}


class TestApplyLimit:
    def test_under_limit(self):
        items = [1, 2, 3]
        out, total, truncated = apply_limit(items, 10)
        assert out == [1, 2, 3]
        assert total == 3
        assert truncated is False

    def test_at_limit(self):
        items = [1, 2, 3]
        out, total, truncated = apply_limit(items, 3)
        assert out == [1, 2, 3]
        assert total == 3
        assert truncated is False

    def test_over_limit(self):
        items = list(range(100))
        out, total, truncated = apply_limit(items, 30)
        assert len(out) == 30
        assert out == list(range(30))
        assert total == 100
        assert truncated is True

    def test_limit_zero_disables_cap(self):
        items = list(range(50))
        out, total, truncated = apply_limit(items, 0)
        assert out == items
        assert total == 50
        assert truncated is False

    def test_negative_limit_disables_cap(self):
        items = list(range(50))
        out, total, truncated = apply_limit(items, -1)
        assert out == items
        assert truncated is False

    def test_empty_list(self):
        out, total, truncated = apply_limit([], 10)
        assert out == []
        assert total == 0
        assert truncated is False
