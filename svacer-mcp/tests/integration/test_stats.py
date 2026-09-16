"""Integration tests for the get_project_stats tool.

get_project_stats has no dedicated backend endpoint — it aggregates over
/fullmarkers (see api_client.py:165). So we mock the same URL as get_warnings.
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


async def test_get_project_stats_aggregates_warnings(mock_svacer):
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "w-1",
                    "warnClass": "DEREF.NULL",
                    "review": {"severity": "Critical", "status": "Confirmed"},
                },
                {
                    "id": "w-2",
                    "warnClass": "DEREF.NULL",
                    "review": {"severity": "Major", "status": "Suspicious"},
                },
                {
                    "id": "w-3",
                    "warnClass": "RESOURCE.LEAK",
                    "review": {"severity": "Critical", "status": "Confirmed"},
                },
            ],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_project_stats",
            {"project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP},
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["total_warnings"] == 3
    assert payload["by_severity"] == {"Critical": 2, "Major": 1}
    assert payload["by_review_status"] == {"Confirmed": 2, "Suspicious": 1}
    assert payload["by_checker"] == {"DEREF.NULL": 2, "RESOURCE.LEAK": 1}


async def test_get_project_stats_backend_400(mock_svacer):
    mock_svacer.get(FULLMARKERS_URL).mock(
        return_value=httpx.Response(400, text="bad request")
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_project_stats",
            {"project_id": PROJ, "branch_id": BRANCH, "snapshot_id": SNAP},
        )

    assert result.isError is True
    assert "400" in result.content[0].text
