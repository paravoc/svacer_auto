"""Unit tests for _extract_commit helper and FilterBuilder snapshot filter."""
import base64
import json

from svacer_mcp.tools.snapshots import _extract_commit, _extract_commit_from_name
from svacer_mcp.utils.filters import FilterBuilder


class TestExtractCommit:
    def test_dict_shape_exact_key(self):
        details = {"custom_properties": {"commit": "deadbeef"}}
        assert _extract_commit(details) == "deadbeef"

    def test_dict_shape_compound_key(self):
        details = {"custom_properties": {"git_commit_sha": "abc123"}}
        assert _extract_commit(details) == "abc123"

    def test_dict_shape_case_insensitive(self):
        details = {"custom_properties": {"GitCommit": "abc123"}}
        assert _extract_commit(details) == "abc123"

    def test_list_shape(self):
        details = {
            "custom_properties": [
                {"name": "build", "value": "42"},
                {"name": "commit_sha", "value": "abc123"},
            ]
        }
        assert _extract_commit(details) == "abc123"

    def test_no_matching_key(self):
        details = {"custom_properties": {"build": "42"}}
        assert _extract_commit(details) is None

    def test_no_custom_properties(self):
        assert _extract_commit({}) is None

    def test_none_details(self):
        assert _extract_commit(None) is None  # type: ignore[arg-type]

    def test_empty_value_skipped(self):
        details = {"custom_properties": {"commit": ""}}
        assert _extract_commit(details) is None


class TestExtractCommitFromName:
    def test_short_hex_prefix(self):
        assert _extract_commit_from_name("e20758f0 - Mon, 13 Dec 2021 13_23_41  0300.snap") == "e20758f0"

    def test_full_sha1_prefix(self):
        name = "abc1234567890abcdef1234567890abcdef12345 - foo"
        assert _extract_commit_from_name(name) == "abc1234567890abcdef1234567890abcdef12345"

    def test_no_dash_separator(self):
        assert _extract_commit_from_name("Snapshot 2023-05-17 17:30:51 +0300") is None

    def test_too_short_prefix(self):
        assert _extract_commit_from_name("e207 - foo") is None

    def test_non_hex_prefix(self):
        assert _extract_commit_from_name("release - 2023") is None

    def test_empty_name(self):
        assert _extract_commit_from_name("") is None

    def test_none(self):
        assert _extract_commit_from_name(None) is None  # type: ignore[arg-type]

    def test_upper_case_hex(self):
        assert _extract_commit_from_name("DEADBEEF - build") == "DEADBEEF"


class TestSnapshotsFilter:
    PID = "aaaaaaaa-0000-0000-0000-000000000001"
    BID = "bbbbbbbb-0000-0000-0000-000000000002"

    def _decode(self, b64: str) -> dict:
        return json.loads(base64.b64decode(b64.encode("ascii")).decode("utf-8"))

    def test_filter_without_name(self):
        b64 = FilterBuilder().build_snapshots_filter(self.PID, self.BID)
        data = self._decode(b64)
        assert data["project"]["id"] == self.PID
        assert data["branch"]["id"] == self.BID
        assert "snapshot" not in data

    def test_filter_with_name(self):
        b64 = FilterBuilder().build_snapshots_filter(self.PID, self.BID, name="release")
        data = self._decode(b64)
        assert data["snapshot"]["name"] == "release"

    def test_filter_passes_regex_alternatives(self):
        b64 = FilterBuilder().build_snapshots_filter(self.PID, self.BID, name="v1|v2")
        data = self._decode(b64)
        assert data["snapshot"]["name"] == "v1|v2"
