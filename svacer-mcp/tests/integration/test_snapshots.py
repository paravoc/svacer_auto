"""Integration tests for the get_snapshots tool.

This tool makes N+1 HTTP calls: one to /snapshots and one to /markers per
snapshot to compute markers_count. Tests cover both shapes of
details.custom_properties (dict and list) handled by _extract_commit.
"""
import base64
import json

import httpx
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp

PROJ = "11111111-1111-4111-8111-111111111111"
BRANCH = "22222222-2222-4222-8222-222222222222"
SNAP_A = "33333333-3333-4333-8333-333333333333"
SNAP_B = "44444444-4444-4444-8444-444444444444"


async def test_get_snapshots_with_marker_counts_and_commit_extraction(mock_svacer):
    mock_svacer.get("/api/public/snapshots").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "project_id": PROJ,
                    "branch_id": BRANCH,
                    "snapshots": [
                        {
                            "id": SNAP_A,
                            "name": "build-1",
                            "import_time": "2025-01-01T10:00:00Z",
                            "details": {"custom_properties": {"git_commit": "abc123"}},
                            "link": "https://svacer/snap/A",
                        },
                        {
                            "id": SNAP_B,
                            "name": "build-2",
                            "import_time": "2025-01-02T10:00:00Z",
                            "details": {
                                "custom_properties": [
                                    {"name": "commit_sha", "value": "def456"},
                                ]
                            },
                            "link": "https://svacer/snap/B",
                        },
                    ],
                },
            ],
        )
    )
    mock_svacer.get("/api/public/markers").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[{"markers": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]}],
            ),
            httpx.Response(200, json=[{"markers": []}]),
        ]
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_snapshots",
            {"project_id": PROJ, "branch_id": BRANCH},
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert len(payload) == 2
    assert payload[0] == {
        "snapshot_id": SNAP_A,
        "name": "build-1",
        "import_time": "2025-01-01T10:00:00Z",
        "commit_hash": "abc123",
        "markers_count": 3,
        "link": "https://svacer/snap/A",
    }
    assert payload[1] == {
        "snapshot_id": SNAP_B,
        "name": "build-2",
        "import_time": "2025-01-02T10:00:00Z",
        "commit_hash": "def456",
        "markers_count": 0,
        "link": "https://svacer/snap/B",
    }


async def test_get_snapshots_empty_skips_marker_count(mock_svacer):
    mock_svacer.get("/api/public/snapshots").mock(
        return_value=httpx.Response(200, json=[])
    )
    markers_route = mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(200, json=[])
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_snapshots",
            {"project_id": PROJ, "branch_id": BRANCH},
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload == []
    assert not markers_route.called


async def test_get_snapshots_empty_wrapper_skips_marker_count(mock_svacer):
    """Svacer may return the wrapper with an empty `snapshots` list; treat as empty."""
    mock_svacer.get("/api/public/snapshots").mock(
        return_value=httpx.Response(
            200,
            json=[{"project_id": PROJ, "branch_id": BRANCH, "snapshots": []}],
        )
    )
    markers_route = mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(200, json=[])
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_snapshots",
            {"project_id": PROJ, "branch_id": BRANCH},
        )

    assert result.isError is False
    assert json.loads(result.content[0].text) == []
    assert not markers_route.called


async def test_get_snapshots_commit_hash_from_name_prefix(mock_svacer):
    """Real-world demo snapshots have no custom_properties — commit hash sits in
    the name prefix (e.g. ``"e20758f0 - Mon, 13 Dec 2021 …"``)."""
    snap_id = "55555555-5555-4555-8555-555555555555"
    mock_svacer.get("/api/public/snapshots").mock(
        return_value=httpx.Response(
            200,
            json=[{
                "project_id": PROJ,
                "branch_id": BRANCH,
                "snapshots": [{
                    "id": snap_id,
                    "name": "e20758f0 - Mon, 13 Dec 2021 13_23_41  0300.snap",
                    "import_time": "2021-12-13T13:23:42Z",
                    "details": {"analysis-info": "Svace version: 3.2.0\n..."},
                    "link": "https://svacer/snap/X",
                }],
            }],
        )
    )
    mock_svacer.get("/api/public/markers").mock(
        return_value=httpx.Response(200, json=[{"markers": []}])
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_snapshots",
            {"project_id": PROJ, "branch_id": BRANCH},
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert len(payload) == 1
    assert payload[0]["snapshot_id"] == snap_id
    assert payload[0]["commit_hash"] == "e20758f0"


SID_1 = "11111111-0000-0000-0000-000000000001"
SID_2 = "22222222-0000-0000-0000-000000000002"


async def test_get_snapshots_marker_count_per_snapshot_id(mock_svacer):
    """Marker count is fetched per snapshot id and matched correctly."""
    mock_svacer.get("/api/public/snapshots").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "project_id": PROJ,
                    "branch_id": BRANCH,
                    "snapshots": [
                        {
                            "id": SID_1,
                            "name": "release",
                            "import_time": "2025-01-01T00:00:00Z",
                            "details": {"custom_properties": {"git_commit": "abc1234"}},
                        },
                        {
                            "id": SID_2,
                            "name": "main",
                            "import_time": "2025-01-02T00:00:00Z",
                        },
                    ],
                },
            ],
        )
    )

    def markers_route(request: httpx.Request) -> httpx.Response:
        filters_b64 = request.url.params["filters"]
        decoded = json.loads(base64.b64decode(filters_b64).decode())
        sid = decoded["snapshot"]["id"]
        counts = {SID_1: 3, SID_2: 7}
        markers = [{"id": f"m{i}"} for i in range(counts[sid])]
        return httpx.Response(200, json=[{"markers": markers}])

    mock_svacer.get("/api/public/markers").mock(side_effect=markers_route)

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_snapshots",
            {"project_id": PROJ, "branch_id": BRANCH},
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    by_id = {s["snapshot_id"]: s for s in payload}
    assert by_id[SID_1]["markers_count"] == 3
    assert by_id[SID_2]["markers_count"] == 7
    assert by_id[SID_1]["commit_hash"] == "abc1234"
    assert by_id[SID_2]["commit_hash"] is None
