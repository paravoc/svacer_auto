"""Tests for Svacer advanced-filter expressions."""

import inspect
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from svacer_mcp.api_client import SvacerAPIClient
from svacer_mcp.tools.markers import get_markers
from svacer_mcp.tools.warnings import get_warnings


PROJECT_ID = "11111111-1111-1111-1111-111111111111"
BRANCH_ID = "22222222-2222-2222-2222-222222222222"
SNAPSHOT_ID = "33333333-3333-3333-3333-333333333333"
EXPRESSION = 'filter(markers, "ГОСТ 71207-2024" in .checker_labels)'


def _ctx(client):
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"api_client": client}
    return ctx


def _marker(marker_id):
    return {
        "id": marker_id,
        "warnClass": "TEST",
        "file": "/src/test.cc",
        "line": 1,
        "msg": "test",
    }


def _api_client():
    auth = MagicMock()
    auth.url = "http://svacer"
    auth.timeout = 10
    client = SvacerAPIClient.__new__(SvacerAPIClient)
    client.auth = auth
    client.base_url = auth.url
    client.timeout = auth.timeout
    return client


async def test_api_client_posts_expression_and_snapshot_ids():
    client = _api_client()
    response = MagicMock()
    response.status_code = 200
    response.content = b'{"marker_ids":["keep"]}'
    response.json.return_value = {"marker_ids": ["keep"]}
    request = AsyncMock(return_value=response)

    with patch.object(client, "_request", new=request):
        result = await client.apply_advanced_filter(EXPRESSION, [SNAPSHOT_ID])

    assert result == ["keep"]
    request.assert_awaited_once_with(
        "POST",
        "http://svacer/api/public/afilters/apply",
        json={"filter": EXPRESSION, "snapshot_id": [SNAPSHOT_ID]},
    )


async def test_get_markers_keeps_only_advanced_filter_ids():
    client = MagicMock()
    client.apply_advanced_filter = AsyncMock(return_value=["keep"])
    client.get_markers = AsyncMock(return_value=[{
        "markers": [_marker("keep"), _marker("drop")]
    }])

    result = json.loads(await get_markers(
        PROJECT_ID, BRANCH_ID, SNAPSHOT_ID,
        ctx=_ctx(client), advanced_filter=EXPRESSION, limit=0,
    ))

    assert [m["id"] for m in result["markers"]] == ["keep"]
    assert result["filters_applied"]["advanced_filter"] == EXPRESSION
    client.apply_advanced_filter.assert_awaited_once_with(EXPRESSION, [SNAPSHOT_ID])


async def test_get_warnings_keeps_only_advanced_filter_ids():
    client = MagicMock()
    client.apply_advanced_filter = AsyncMock(return_value=["keep"])
    client.get_warnings = AsyncMock(return_value=[_marker("keep"), _marker("drop")])

    result = json.loads(await get_warnings(
        PROJECT_ID, BRANCH_ID, SNAPSHOT_ID,
        ctx=_ctx(client), advanced_filter=EXPRESSION, limit=0,
    ))

    assert [m["id"] for m in result["warnings"]] == ["keep"]
    assert result["filters_applied"]["advanced_filter"] == EXPRESSION
    client.apply_advanced_filter.assert_awaited_once_with(EXPRESSION, [SNAPSHOT_ID])


def test_tool_schemas_expose_advanced_filter():
    assert "advanced_filter" in inspect.signature(get_markers).parameters
    assert "advanced_filter" in inspect.signature(get_warnings).parameters


async def test_filter_failure_never_falls_back_to_full_snapshot():
    client = MagicMock()
    client.apply_advanced_filter = AsyncMock(side_effect=RuntimeError("synthetic filter error"))
    client.get_markers = AsyncMock()
    with pytest.raises(RuntimeError):
        await get_markers(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID,
                          ctx=_ctx(client), advanced_filter=EXPRESSION, limit=0)
    client.get_markers.assert_not_awaited()


async def test_missing_marker_in_inventory_is_an_error():
    client = MagicMock()
    client.apply_advanced_filter = AsyncMock(return_value=["keep", "missing"])
    client.get_markers = AsyncMock(return_value=[{"markers": [_marker("keep")]}])
    with pytest.raises(ValueError, match="Incomplete inventory"):
        await get_markers(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID,
                          ctx=_ctx(client), advanced_filter=EXPRESSION, limit=0)


async def test_no_severity_is_excluded_and_empty_filter_is_empty():
    client = MagicMock()
    markers = [{**_marker(str(i)), "severity": severity} for i, severity in enumerate(
        ["CRITICAL", "MAJOR", "NORMAL", "MINOR", "UNDEFINED"])]
    client.apply_advanced_filter = AsyncMock(return_value=[m["id"] for m in markers])
    client.get_markers = AsyncMock(return_value=[{"markers": markers}])
    result = json.loads(await get_markers(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID,
                        ctx=_ctx(client), advanced_filter=EXPRESSION, limit=0))
    assert len(result["markers"]) == 5
    client.apply_advanced_filter.return_value = []
    result = json.loads(await get_markers(PROJECT_ID, BRANCH_ID, SNAPSHOT_ID,
                        ctx=_ctx(client), advanced_filter=EXPRESSION, limit=0))
    assert result["markers"] == [] and result["total_count"] == 0


@pytest.mark.parametrize("payload", [{}, {"marker_ids": None}, {"marker_ids": [None]}, {"marker_ids": "keep"}])
async def test_malformed_filter_response_is_not_silently_empty(payload):
    from svacer_mcp.exceptions import SvacerAPIError
    client = _api_client()
    response = MagicMock()
    response.status_code = 200
    response.content = json.dumps(payload).encode()
    response.json.return_value = payload
    with patch.object(client, "_request", new=AsyncMock(return_value=response)):
        with pytest.raises(SvacerAPIError):
            await client.apply_advanced_filter(EXPRESSION, [SNAPSHOT_ID])
