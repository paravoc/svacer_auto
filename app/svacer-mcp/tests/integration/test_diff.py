"""Integration tests for the get_diff tool via in-memory MCP session."""
import json

import httpx
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp

BASE_SNAP = "11111111-1111-4111-8111-111111111111"
HEAD_SNAP = "22222222-2222-4222-8222-222222222222"


async def test_get_diff_returns_diff_payload(mock_svacer):
    diff_route = mock_svacer.get("/api/public/diff").mock(
        return_value=httpx.Response(
            200,
            json={
                "stats": {"new": 1, "missing": 0, "matched": 0, "modified": 0},
                "markers": {
                    "new_markers": ["m-1"],
                    "missing_markers": [],
                    "matched_markers": [],
                    "modified_markers": [],
                },
            },
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_diff",
            {
                "base_snapshot_id": BASE_SNAP,
                "head_snapshot_id": HEAD_SNAP,
                "level": 1,
            },
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["stats"]["new"] == 1
    # level<2 — категории не оборачиваются, проходят насквозь.
    assert payload["markers"]["new_markers"] == ["m-1"]

    params = diff_route.calls.last.request.url.params
    assert params["snapshot_v1"] == BASE_SNAP
    assert params["snapshot_v2"] == HEAD_SNAP
    assert params["level"] == "1"


async def test_get_diff_level_zero_is_passed(mock_svacer):
    diff_route = mock_svacer.get("/api/public/diff").mock(
        return_value=httpx.Response(
            200,
            json={"stats": {"added": 5, "removed": 2}, "links": {}},
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_diff",
            {
                "base_snapshot_id": BASE_SNAP,
                "head_snapshot_id": HEAD_SNAP,
                "level": 0,
            },
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert "markers" not in payload
    assert payload["stats"] == {"added": 5, "removed": 2}

    params = diff_route.calls.last.request.url.params
    assert params["level"] == "0"


def _full_marker(mid: str) -> dict:
    return {
        "id": mid,
        "warnClass": "DEREF.NULL",
        "file": f"src/{mid}.c",
        "line": 1,
        "msg": "null pointer",
        "tool": "svace",
        "function": "fn",
        "mtid": f"mt-{mid}",
        "review": {"severity": "Critical", "status": "Confirmed"},
    }


def _diff_payload(**categories) -> dict:
    """Shape the response exactly like Svacer's /api/public/diff?level=2:
    top-level stats + markers{new_markers, missing_markers, matched_markers,
    modified_markers}. Missing keys default to empty lists."""
    return {
        "stats": {k.replace("_markers", ""): len(v) for k, v in categories.items()},
        "markers": {
            "new_markers": categories.get("new_markers", []),
            "missing_markers": categories.get("missing_markers", []),
            "matched_markers": categories.get("matched_markers", []),
            "modified_markers": categories.get("modified_markers", []),
        },
    }


async def test_get_diff_level_2_truncates_per_category(mock_svacer):
    """level=2 wraps each category with total_count/returned_count/truncated."""
    mock_svacer.get("/api/public/diff").mock(
        return_value=httpx.Response(
            200,
            json=_diff_payload(
                new_markers=[_full_marker(f"a{i}") for i in range(50)],
                missing_markers=[_full_marker(f"r{i}") for i in range(5)],
                modified_markers=[],
                matched_markers=[],
            ),
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_diff",
            {
                "base_snapshot_id": BASE_SNAP, "head_snapshot_id": HEAD_SNAP,
                "level": 2,
            },
        )

    payload = json.loads(result.content[0].text)
    assert payload["stats"]["new"] == 50
    assert payload["stats"]["missing"] == 5

    cats = payload["markers"]
    # new_markers: больше дефолта (20) — truncated
    assert cats["new_markers"]["total_count"] == 50
    assert cats["new_markers"]["returned_count"] == 20
    assert cats["new_markers"]["truncated"] is True
    assert len(cats["new_markers"]["markers"]) == 20

    # missing_markers: меньше дефолта — не обрезано
    assert cats["missing_markers"]["total_count"] == 5
    assert cats["missing_markers"]["returned_count"] == 5
    assert cats["missing_markers"]["truncated"] is False

    # modified_markers: пустой список — обёртка тоже есть, всё по нулям
    assert cats["modified_markers"]["total_count"] == 0
    assert cats["modified_markers"]["truncated"] is False


async def test_get_diff_level_2_default_fields_are_compact(mock_svacer):
    mock_svacer.get("/api/public/diff").mock(
        return_value=httpx.Response(
            200,
            json=_diff_payload(new_markers=[_full_marker("a1")]),
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_diff",
            {"base_snapshot_id": BASE_SNAP, "head_snapshot_id": HEAD_SNAP, "level": 2},
        )

    payload = json.loads(result.content[0].text)
    marker = payload["markers"]["new_markers"]["markers"][0]
    assert "tool" not in marker
    assert "mtid" not in marker
    assert marker["id"] == "a1"


async def test_get_diff_level_2_fields_star_returns_full(mock_svacer):
    mock_svacer.get("/api/public/diff").mock(
        return_value=httpx.Response(
            200,
            json=_diff_payload(new_markers=[_full_marker("a1")]),
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_diff",
            {
                "base_snapshot_id": BASE_SNAP, "head_snapshot_id": HEAD_SNAP,
                "level": 2, "fields": ["*"],
            },
        )

    payload = json.loads(result.content[0].text)
    marker = payload["markers"]["new_markers"]["markers"][0]
    assert marker["tool"] == "svace"
    assert marker["mtid"] == "mt-a1"


async def test_get_diff_level_1_does_not_wrap_categories(mock_svacer):
    """At level<2 categories are not wrapped — output stays a plain list."""
    mock_svacer.get("/api/public/diff").mock(
        return_value=httpx.Response(
            200,
            json={
                "stats": {"new": 2},
                "markers": {
                    "new_markers": ["m-1", "m-2"],
                    "missing_markers": [],
                    "matched_markers": [],
                    "modified_markers": [],
                },
            },
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_diff",
            {"base_snapshot_id": BASE_SNAP, "head_snapshot_id": HEAD_SNAP, "level": 1},
        )

    payload = json.loads(result.content[0].text)
    assert isinstance(payload["markers"]["new_markers"], list)
    assert payload["markers"]["new_markers"] == ["m-1", "m-2"]


async def test_get_diff_level_2_limit_zero_disables_cap(mock_svacer):
    mock_svacer.get("/api/public/diff").mock(
        return_value=httpx.Response(
            200,
            json=_diff_payload(
                new_markers=[_full_marker(f"a{i}") for i in range(50)],
            ),
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_diff",
            {
                "base_snapshot_id": BASE_SNAP, "head_snapshot_id": HEAD_SNAP,
                "level": 2, "limit": 0,
            },
        )

    payload = json.loads(result.content[0].text)
    cat = payload["markers"]["new_markers"]
    assert cat["returned_count"] == 50
    assert cat["truncated"] is False


async def test_get_diff_snapshot_not_found(mock_svacer):
    mock_svacer.get("/api/public/diff").mock(
        return_value=httpx.Response(404, text="snapshot not found")
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_diff",
            {"base_snapshot_id": BASE_SNAP, "head_snapshot_id": HEAD_SNAP},
        )

    assert result.isError is True
    assert "404" in result.content[0].text
