"""Tests for checker_info support (issue #4).

Verifies that checker_info=true is:
  - passed as a query parameter to the Svacer API
  - included in filters_applied in the tool output
  - preserved in the warning output when the API returns checkerInfo
"""
import inspect
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from svacer_mcp.tools.warnings import _format_warning, get_warnings
from svacer_mcp.tools.markers import get_markers
from svacer_mcp.tools.diff import get_diff


PROJECT_ID  = "11111111-1111-1111-1111-111111111111"
BRANCH_ID   = "22222222-2222-2222-2222-222222222222"
SNAPSHOT_ID = "33333333-3333-3333-3333-333333333333"

CHECKER_INFO = {
    "name": "DEREF_AFTER_NULL",
    "description": "Pointer dereferenced after NULL check",
    "cwe": "CWE-476",
    "url": "https://example.com/checkers/DEREF_AFTER_NULL",
}

SAMPLE_WARNING = {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "warnClass": "DEREF_AFTER_NULL",
    "file": "/src/main.c",
    "line": 42,
    "msg": "Pointer dereferenced after NULL check",
    "tool": "SvEng",
    "function": "main",
    "mtid": "SvEng.ND.1",
    "review": {"status": "Undecided"},
    "checkerInfo": CHECKER_INFO,
}


def _make_ctx(mock_client):
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"api_client": mock_client}
    return ctx


# ---------------------------------------------------------------------------
# _format_warning
# ---------------------------------------------------------------------------

class TestFormatWarning:
    def test_checker_info_included_when_present(self):
        result = _format_warning(SAMPLE_WARNING)
        assert "checkerInfo" in result
        assert result["checkerInfo"] == CHECKER_INFO

    def test_checker_info_absent_when_not_in_api_response(self):
        w = {k: v for k, v in SAMPLE_WARNING.items() if k != "checkerInfo"}
        result = _format_warning(w)
        assert "checkerInfo" not in result

    def test_checker_info_none_not_included(self):
        w = dict(SAMPLE_WARNING, checkerInfo=None)
        result = _format_warning(w)
        assert "checkerInfo" not in result

    def test_standard_fields_still_present(self):
        result = _format_warning(SAMPLE_WARNING)
        for field in ("id", "warnClass", "file", "line", "msg", "tool", "function", "mtid", "review"):
            assert field in result


# ---------------------------------------------------------------------------
# API client — query param
# ---------------------------------------------------------------------------

class TestApiClientCheckerInfo:
    def _make_client(self):
        from svacer_mcp.api_client import SvacerAPIClient
        auth = MagicMock()
        auth.url = "http://svacer"
        auth.timeout = 10
        client = SvacerAPIClient.__new__(SvacerAPIClient)
        client.auth = auth
        client.base_url = auth.url
        client.timeout = auth.timeout
        return client

    async def test_get_warnings_sends_checker_info_param(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[]"
        mock_resp.json.return_value = []

        mock_req = AsyncMock(return_value=mock_resp)
        with patch.object(client, "_request", new=mock_req):
            await client.get_warnings(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, checker_info=True)
            sent_params = mock_req.call_args.kwargs.get("params", {}) or {}
            assert sent_params.get("checker_info") == "true"

    async def test_get_warnings_no_checker_info_by_default(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[]"
        mock_resp.json.return_value = []

        mock_req = AsyncMock(return_value=mock_resp)
        with patch.object(client, "_request", new=mock_req):
            await client.get_warnings(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID)
            sent_params = mock_req.call_args.kwargs.get("params", {}) or {}
            assert "checker_info" not in sent_params

    async def test_get_markers_sends_checker_info_param(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[]"
        mock_resp.json.return_value = []

        mock_req = AsyncMock(return_value=mock_resp)
        with patch.object(client, "_request", new=mock_req):
            await client.get_markers(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, checker_info=True)
            sent_params = mock_req.call_args.kwargs.get("params", {}) or {}
            assert sent_params.get("checker_info") == "true"

    async def test_get_diff_sends_checker_info_param(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {}

        mock_req = AsyncMock(return_value=mock_resp)
        with patch.object(client, "_request", new=mock_req):
            await client.get_diff(SNAPSHOT_ID, checker_info=True)
            sent_params = mock_req.call_args.kwargs.get("params", {}) or {}
            assert sent_params.get("checker_info") == "true"


# ---------------------------------------------------------------------------
# get_warnings — filters_applied and output
# ---------------------------------------------------------------------------

class TestGetWarnings:
    def _make_client(self, api_warnings):
        mock_client = MagicMock()
        mock_client.get_warnings = AsyncMock(return_value=api_warnings)
        return mock_client

    async def test_checker_info_in_filters_applied(self):
        ctx = _make_ctx(self._make_client([]))
        result = json.loads(await get_warnings(
            PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, checker_info=True
        ))
        assert result["filters_applied"].get("checker_info") is True

    async def test_checker_info_not_in_filters_applied_when_false(self):
        ctx = _make_ctx(self._make_client([]))
        result = json.loads(await get_warnings(
            PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx
        ))
        assert "checker_info" not in result["filters_applied"]

    async def test_checker_info_passed_to_api_client(self):
        mock_client = self._make_client([])
        ctx = _make_ctx(mock_client)
        await get_warnings(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, checker_info=True)
        mock_client.get_warnings.assert_called_once()
        assert mock_client.get_warnings.call_args.kwargs.get("checker_info") is True

    async def test_checker_info_field_in_warning_output(self):
        ctx = _make_ctx(self._make_client([SAMPLE_WARNING]))
        result = json.loads(await get_warnings(
            PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, checker_info=True
        ))
        assert result["warnings"][0]["checkerInfo"] == CHECKER_INFO

    def test_checker_info_schema_has_param(self):
        sig = inspect.signature(get_warnings)
        assert "checker_info" in sig.parameters


# ---------------------------------------------------------------------------
# get_markers — filters_applied
# ---------------------------------------------------------------------------

class TestGetMarkers:
    def _make_client(self, api_response):
        mock_client = MagicMock()
        mock_client.get_markers = AsyncMock(return_value=api_response)
        return mock_client

    async def test_checker_info_in_filters_applied(self):
        ctx = _make_ctx(self._make_client([]))
        result = json.loads(await get_markers(
            PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, checker_info=True
        ))
        assert result["filters_applied"].get("checker_info") is True

    async def test_checker_info_passed_to_api_client(self):
        mock_client = self._make_client([])
        ctx = _make_ctx(mock_client)
        await get_markers(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, checker_info=True)
        assert mock_client.get_markers.call_args.kwargs.get("checker_info") is True

    def test_checker_info_schema_has_param(self):
        sig = inspect.signature(get_markers)
        assert "checker_info" in sig.parameters


# ---------------------------------------------------------------------------
# get_diff
# ---------------------------------------------------------------------------

class TestGetDiff:
    def _make_client(self, api_response):
        mock_client = MagicMock()
        mock_client.get_diff = AsyncMock(return_value=api_response)
        return mock_client

    async def test_checker_info_passed_to_api_client(self):
        mock_client = self._make_client({})
        ctx = _make_ctx(mock_client)
        await get_diff(SNAPSHOT_ID, ctx=ctx, checker_info=True)
        assert mock_client.get_diff.call_args.kwargs.get("checker_info") is True

    async def test_checker_info_not_passed_when_false(self):
        mock_client = self._make_client({})
        ctx = _make_ctx(mock_client)
        await get_diff(SNAPSHOT_ID, ctx=ctx)
        assert not mock_client.get_diff.call_args.kwargs.get("checker_info")

    def test_checker_info_schema_has_param(self):
        sig = inspect.signature(get_diff)
        assert "checker_info" in sig.parameters
