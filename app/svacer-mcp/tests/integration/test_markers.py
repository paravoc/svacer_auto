"""Integration tests for the get_markers tool.

The 401 retry test is the only place we exercise SvacerAPIClient._request's
retry-on-401 path (api_client.py:40-43). The conftest login mock returns a
fresh JWT on every call, so re-auth after invalidate_token works without
any test-side overrides.
"""
import json

import httpx
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp

PROJ = "11111111-1111-4111-8111-111111111111"
BRANCH = "22222222-2222-4222-8222-222222222222"
SNAP = "33333333-3333-4333-8333-333333333333"


async def test_get_markers_returns_filtered_markers(mock_svacer):
    mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "markers": [
                        {
                            "id": "m-1",
                            "warnClass": "DEREF.NULL",
                            "file": "src/a.c",
                            "line": 10,
                            "msg": "null pointer",
                            "tool": "svace",
                            "function": "foo",
                            "mtid": "mt-1",
                            "review": {"severity": "Critical", "status": "Confirmed"},
                        },
                        {
                            "id": "m-2",
                            "warnClass": "DEREF.NULL",
                            "file": "src/b.c",
                            "line": 20,
                            "msg": "null pointer",
                            "tool": "svace",
                            "function": "bar",
                            "mtid": "mt-2",
                            "review": {"severity": "Critical", "status": "Suspicious"},
                        },
                    ]
                }
            ],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {
                "project_id": PROJ,
                "branch_id": BRANCH,
                "snapshot_id": SNAP,
                "severity": ["Critical"],
                "warnClass": ["DEREF.NULL"],
            },
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["total_count"] == 2
    assert payload["filters_applied"] == {
        "severity": ["Critical"],
        "warnClass": ["DEREF.NULL"],
    }
    assert payload["markers"][0]["id"] == "m-1"
    assert payload["markers"][1]["id"] == "m-2"


async def test_get_markers_severity_filter_drops_non_matching_client_side(mock_svacer):
    """Backend ignores server-side severity (it matches checker_severity, not review.severity),
    so the tool must filter client-side. Mock returns Major/Minor/Major; severity=Critical → empty."""
    def _m(mid: str, sev: str) -> dict:
        return {
            "id": mid,
            "warnClass": "DEREF.NULL",
            "file": f"src/{mid}.c",
            "line": 1,
            "msg": "null pointer",
            "tool": "svace",
            "function": "fn",
            "mtid": f"mt-{mid}",
            "review": {"severity": sev, "status": "Confirmed"},
        }

    mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(
            200,
            json=[{"markers": [_m("m1", "Major"), _m("m2", "Minor"), _m("m3", "Major")]}],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {
                "project_id": PROJ,
                "branch_id": BRANCH,
                "snapshot_id": SNAP,
                "severity": ["Critical"],
            },
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["total_count"] == 0
    assert payload["markers"] == []
    assert payload["filters_applied"]["severity"] == ["Critical"]


def _m(mid: str, sev: str = "Critical") -> dict:
    return {
        "id": mid,
        "warnClass": "DEREF.NULL",
        "file": f"src/{mid}.c",
        "line": 1,
        "msg": "null pointer",
        "tool": "svace",
        "function": "fn",
        "mtid": f"mt-{mid}",
        "review": {"severity": sev, "status": "Confirmed"},
    }


async def test_get_markers_truncates_to_default_limit(mock_svacer):
    """Default limit is 30. Mock 50 markers → returned_count=30, total_count=50, truncated=true."""
    mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(
            200,
            json=[{"markers": [_m(f"m{i}") for i in range(50)]}],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {"project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP},
        )

    payload = json.loads(result.content[0].text)
    assert payload["total_count"] == 50
    assert payload["returned_count"] == 30
    assert payload["truncated"] is True
    assert len(payload["markers"]) == 30
    # limit at default → не светим в filters_applied
    assert "limit" not in payload["filters_applied"]


async def test_get_markers_limit_zero_disables_cap(mock_svacer):
    mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(200, json=[{"markers": [_m(f"m{i}") for i in range(50)]}])
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {"project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP, "limit": 0},
        )

    payload = json.loads(result.content[0].text)
    assert payload["total_count"] == 50
    assert payload["returned_count"] == 50
    assert payload["truncated"] is False
    assert payload["filters_applied"]["limit"] == 0


async def test_get_markers_default_fields_are_compact(mock_svacer):
    """Default fields preset drops tool/mtid."""
    mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(200, json=[{"markers": [_m("m1")]}])
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {"project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP},
        )

    payload = json.loads(result.content[0].text)
    marker = payload["markers"][0]
    assert "id" in marker
    assert "warnClass" in marker
    assert "review" in marker
    assert "tool" not in marker
    assert "mtid" not in marker


async def test_get_markers_fields_star_returns_full(mock_svacer):
    mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(200, json=[{"markers": [_m("m1")]}])
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {
                "project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP,
                "fields": ["*"],
            },
        )

    payload = json.loads(result.content[0].text)
    marker = payload["markers"][0]
    assert marker["tool"] == "svace"
    assert marker["mtid"] == "mt-m1"
    assert payload["filters_applied"]["fields"] == ["*"]


async def test_get_markers_explicit_fields_whitelist(mock_svacer):
    mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(200, json=[{"markers": [_m("m1")]}])
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {
                "project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP,
                "fields": ["id", "warnClass"],
            },
        )

    payload = json.loads(result.content[0].text)
    assert payload["markers"][0] == {"id": "m1", "warnClass": "DEREF.NULL"}
    assert payload["filters_applied"]["fields"] == ["id", "warnClass"]


async def test_get_markers_retries_on_401(mock_svacer):
    """First /markers returns 401, _request invalidates token and retries; second
    call succeeds. Verifies the auth retry path end-to-end."""
    markers_route = mock_svacer.get("/api/public/markers").mock(
        side_effect=[
            httpx.Response(401, text="token expired"),
            httpx.Response(
                200,
                json=[{"markers": [{"id": "m-after-retry"}]}],
            ),
        ]
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {"project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP},
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["total_count"] == 1
    assert payload["markers"][0]["id"] == "m-after-retry"
    assert markers_route.call_count == 2
