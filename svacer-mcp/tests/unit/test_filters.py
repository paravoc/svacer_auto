"""Tests for FilterBuilder"""
import json
import base64
import pytest
from svacer_mcp.utils.filters import FilterBuilder


class TestFilterBuilder:
    def test_empty_build(self):
        builder = FilterBuilder()
        assert builder.build() == ""

    def test_review_filter(self):
        result = FilterBuilder().with_review(["Confirmed"]).build()
        decoded = json.loads(base64.b64decode(result))
        assert decoded["marker"]["review"] == "Confirmed"

    def test_checker_filter(self):
        result = FilterBuilder().with_checker(["DEREF_AFTER_NULL"]).build()
        decoded = json.loads(base64.b64decode(result))
        assert decoded["marker"]["checker"] == "DEREF_AFTER_NULL"

    def test_file_filter(self):
        result = FilterBuilder().with_file(["main.c", "util.c"]).build()
        decoded = json.loads(base64.b64decode(result))
        assert decoded["marker"]["file"] == "main.c|util.c"

    def test_build_markers_filter(self):
        project_id = "11111111-1111-1111-1111-111111111111"
        branch_id = "22222222-2222-2222-2222-222222222222"
        snapshot_id = "33333333-3333-3333-3333-333333333333"

        result = (
            FilterBuilder()
            .with_checker(["NULL_CHECK"])
            .build_markers_filter(project_id, branch_id, snapshot_id)
        )
        decoded = json.loads(base64.b64decode(result))
        assert decoded["project"]["id"] == project_id
        assert decoded["branch"]["id"] == branch_id
        assert decoded["snapshot"]["id"] == snapshot_id
        assert decoded["marker"]["checker"] == "NULL_CHECK"

    def test_markers_filter_no_marker_filters(self):
        result = FilterBuilder().build_markers_filter("p", "b", "s")
        decoded = json.loads(base64.b64decode(result))
        assert "marker" not in decoded
