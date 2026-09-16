"""Integration tests for the get_warnings tool.

The "severity filtered out everything" edge case targets _apply_severity_filter
in tools/warnings.py — the /fullmarkers endpoint's server-side severity param
matches checker_severity (a static checker property), not review.severity, so
review.severity filtering is done client-side.
"""
import json

import httpx
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp

PROJ = "11111111-1111-4111-8111-111111111111"
BRANCH = "22222222-2222-4222-8222-222222222222"
SNAP = "33333333-3333-4333-8333-333333333333"

FULLMARKERS_URL = (
    f"/api/public/projects/{PROJ}/branch/{BRANCH}/snapshots/{SNAP}/fullmarkers"
)


def _warning(wid: str, severity: str) -> dict:
    return {
        "id": wid,
        "warnClass": "DEREF.NULL",
        "file": f"src/{wid}.c",
        "line": 1,
        "msg": "null pointer",
        "tool": "svace",
        "function": "fn",
        "mtid": f"mt-{wid}",
        "review": {"severity": severity, "status": "Confirmed"},
    }


async def test_get_warnings_returns_all_warnings_with_review_history_flag(mock_svacer):
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                _warning("w1", "Critical"),
                _warning("w2", "Major"),
                _warning("w3", "Minor"),
            ],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_warnings",
            {
                "project_id": PROJ,
                "branch_id": BRANCH,
                "snapshot_id": SNAP,
                "review_history": True,
            },
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["total_count"] == 3
    assert payload["filters_applied"]["review_history"] is True
    assert {w["id"] for w in payload["warnings"]} == {"w1", "w2", "w3"}


async def test_get_warnings_truncates_to_default_limit(mock_svacer):
    """Default warning limit is 30. Mock 50 warnings → returned_count=30."""
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[_warning(f"w{i}", "Critical") for i in range(50)],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_warnings",
            {"project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP},
        )

    payload = json.loads(result.content[0].text)
    assert payload["total_count"] == 50
    assert payload["returned_count"] == 30
    assert payload["truncated"] is True
    assert "limit" not in payload["filters_applied"]


async def test_get_warnings_heavy_limit_kicks_in_when_traces_enabled(mock_svacer):
    """traces=True without explicit limit → DEFAULT_HEAVY_LIMIT (8)."""
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[_warning(f"w{i}", "Critical") for i in range(20)],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_warnings",
            {
                "project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP,
                "traces": True,
            },
        )

    payload = json.loads(result.content[0].text)
    assert payload["total_count"] == 20
    assert payload["returned_count"] == 8
    assert payload["truncated"] is True
    # heavy fallback не светим в filters_applied как «явный limit»
    assert "limit" not in payload["filters_applied"]
    assert payload["filters_applied"]["traces"] is True


async def test_get_warnings_explicit_limit_overrides_heavy_default(mock_svacer):
    """Explicit limit wins over both heavy and normal defaults."""
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[_warning(f"w{i}", "Critical") for i in range(50)],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_warnings",
            {
                "project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP,
                "traces": True,
                "limit": 15,
            },
        )

    payload = json.loads(result.content[0].text)
    assert payload["returned_count"] == 15
    assert payload["filters_applied"]["limit"] == 15


async def test_get_warnings_limit_zero_disables_cap(mock_svacer):
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[_warning(f"w{i}", "Critical") for i in range(50)],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_warnings",
            {
                "project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP,
                "limit": 0,
            },
        )

    payload = json.loads(result.content[0].text)
    assert payload["total_count"] == 50
    assert payload["returned_count"] == 50
    assert payload["truncated"] is False


async def test_get_warnings_default_fields_are_compact(mock_svacer):
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(200, json=[_warning("w1", "Critical")])
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_warnings",
            {"project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP},
        )

    payload = json.loads(result.content[0].text)
    w = payload["warnings"][0]
    assert "tool" not in w
    assert "mtid" not in w
    assert "review" in w


async def test_get_warnings_fields_star_returns_full(mock_svacer):
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(200, json=[_warning("w1", "Critical")])
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_warnings",
            {
                "project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP,
                "fields": ["*"],
            },
        )

    payload = json.loads(result.content[0].text)
    w = payload["warnings"][0]
    assert w["tool"] == "svace"
    assert w["mtid"] == "mt-w1"


async def test_get_warnings_severity_filter_removes_all_client_side(mock_svacer):
    """Backend returns warnings with Major/Minor/Major review.severity. Client
    asks for severity=Critical → _apply_severity_filter drops everything."""
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                _warning("w1", "Major"),
                _warning("w2", "Minor"),
                _warning("w3", "Major"),
            ],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_warnings",
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
    assert payload["warnings"] == []
    assert payload["filters_applied"]["severity"] == ["Critical"]
