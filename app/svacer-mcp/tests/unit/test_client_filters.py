"""Tests for client-side severity filtering (used only by get_warnings / fullmarkers)"""
import pytest
from svacer_mcp.tools.warnings import _apply_severity_filter


def _w(severity=None):
    """Helper to create a minimal warning dict."""
    w = {"warnClass": "CLS", "file": "src/a.c"}
    if severity:
        w["review"] = {"severity": severity}
    return w


class TestApplySeverityFilter:
    def test_no_filter_returns_all(self):
        warnings = [_w("Critical"), _w("Major"), _w()]
        result = _apply_severity_filter(warnings, {})
        assert len(result) == 3

    def test_severity_filter(self):
        warnings = [_w("Critical"), _w("Major"), _w()]
        result = _apply_severity_filter(warnings, {"severity": ["Critical"]})
        assert len(result) == 1
        assert result[0]["review"]["severity"] == "Critical"

    def test_multiple_severities(self):
        warnings = [_w("Critical"), _w("Major"), _w("Unspecified")]
        result = _apply_severity_filter(warnings, {"severity": ["Critical", "Major"]})
        assert len(result) == 2

    def test_no_review_excluded(self):
        warnings = [_w(), _w("Critical")]
        result = _apply_severity_filter(warnings, {"severity": ["Critical"]})
        assert len(result) == 1

    def test_empty_warnings_list(self):
        assert _apply_severity_filter([], {"severity": ["Critical"]}) == []
