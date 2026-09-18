"""Tests for comment_history support (issue #6).

Verifies that comment_history=true is:
  - passed as a query parameter to the Svacer API
  - included in filters_applied in the tool output
  - preserved in the warning output when the API returns comments
"""
import inspect
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from svacer_mcp.tools.warnings import _format_warning, get_warnings
from svacer_mcp.tools.markers import get_markers


PROJECT_ID  = "11111111-1111-1111-1111-111111111111"
BRANCH_ID   = "22222222-2222-2222-2222-222222222222"
SNAPSHOT_ID = "33333333-3333-3333-3333-333333333333"

COMMENTS = [
    {"text": "looks like a real bug", "author": "alice", "created_at": "2024-01-15T10:00:00Z"},
    {"text": "confirmed, fixing", "author": "bob", "created_at": "2024-01-16T09:00:00Z"},
]

SAMPLE_WARNING = {
    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "warnClass": "DEREF_AFTER_NULL",
    "file": "/src/main.c",
    "line": 42,
    "msg": "Pointer dereferenced after NULL check",
    "tool": "SvEng",
    "function": "main",
    "mtid": "SvEng.ND.1",
    "review": {"status": "Confirmed"},
    "comments": COMMENTS,
}


def _make_ctx(mock_client):
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"api_client": mock_client}
    return ctx


# ---------------------------------------------------------------------------
# _format_warning
# ---------------------------------------------------------------------------

class TestFormatWarning:
    def test_comments_included_when_present(self):
        result = _format_warning(SAMPLE_WARNING)
        assert "comments" in result
        assert result["comments"] == COMMENTS

    def test_comments_absent_when_not_in_api_response(self):
        w = {k: v for k, v in SAMPLE_WARNING.items() if k != "comments"}
        result = _format_warning(w)
        assert "comments" not in result

    def test_comments_none_not_included(self):
        w = dict(SAMPLE_WARNING, comments=None)
        result = _format_warning(w)
        assert "comments" not in result


# ---------------------------------------------------------------------------
# API client — query param
# ---------------------------------------------------------------------------

class TestApiClientCommentHistory:
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

    async def test_get_warnings_sends_comment_history_param(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[]"
        mock_resp.json.return_value = []

        mock_req = AsyncMock(return_value=mock_resp)
        with patch.object(client, "_request", new=mock_req):
            await client.get_warnings(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, comment_history=True)
            sent_params = mock_req.call_args.kwargs.get("params", {}) or {}
            assert sent_params.get("comment_history") == "true"

    async def test_get_warnings_no_comment_history_by_default(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[]"
        mock_resp.json.return_value = []

        mock_req = AsyncMock(return_value=mock_resp)
        with patch.object(client, "_request", new=mock_req):
            await client.get_warnings(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID)
            sent_params = mock_req.call_args.kwargs.get("params", {}) or {}
            assert "comment_history" not in sent_params

    async def test_get_markers_sends_comment_history_param(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[]"
        mock_resp.json.return_value = []

        mock_req = AsyncMock(return_value=mock_resp)
        with patch.object(client, "_request", new=mock_req):
            await client.get_markers(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, comment_history=True)
            sent_params = mock_req.call_args.kwargs.get("params", {}) or {}
            assert sent_params.get("comment_history") == "true"


# ---------------------------------------------------------------------------
# get_warnings
# ---------------------------------------------------------------------------

class TestGetWarnings:
    def _make_client(self, api_warnings):
        mock_client = MagicMock()
        mock_client.get_warnings = AsyncMock(return_value=api_warnings)
        return mock_client

    async def test_comment_history_in_filters_applied(self):
        ctx = _make_ctx(self._make_client([]))
        result = json.loads(await get_warnings(
            PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, comment_history=True
        ))
        assert result["filters_applied"].get("comment_history") is True

    async def test_comment_history_not_in_filters_applied_when_false(self):
        ctx = _make_ctx(self._make_client([]))
        result = json.loads(await get_warnings(
            PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx
        ))
        assert "comment_history" not in result["filters_applied"]

    async def test_comment_history_passed_to_api_client(self):
        mock_client = self._make_client([])
        ctx = _make_ctx(mock_client)
        await get_warnings(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, comment_history=True)
        assert mock_client.get_warnings.call_args.kwargs.get("comment_history") is True

    async def test_comments_field_in_warning_output(self):
        ctx = _make_ctx(self._make_client([SAMPLE_WARNING]))
        result = json.loads(await get_warnings(
            PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, comment_history=True
        ))
        assert result["warnings"][0]["comments"] == COMMENTS

    def test_comment_history_schema_has_param(self):
        sig = inspect.signature(get_warnings)
        assert "comment_history" in sig.parameters


# ---------------------------------------------------------------------------
# get_markers
# ---------------------------------------------------------------------------

class TestGetMarkers:
    def _make_client(self, api_response):
        mock_client = MagicMock()
        mock_client.get_markers = AsyncMock(return_value=api_response)
        return mock_client

    async def test_comment_history_in_filters_applied(self):
        ctx = _make_ctx(self._make_client([]))
        result = json.loads(await get_markers(
            PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, comment_history=True
        ))
        assert result["filters_applied"].get("comment_history") is True

    async def test_comment_history_passed_to_api_client(self):
        mock_client = self._make_client([])
        ctx = _make_ctx(mock_client)
        await get_markers(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID, ctx=ctx, comment_history=True)
        assert mock_client.get_markers.call_args.kwargs.get("comment_history") is True

    def test_comment_history_schema_has_param(self):
        sig = inspect.signature(get_markers)
        assert "comment_history" in sig.parameters
