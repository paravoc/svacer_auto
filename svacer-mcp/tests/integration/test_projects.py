"""Integration tests for the get_projects tool via in-memory MCP session."""
import json

import httpx
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp


async def test_get_projects_returns_formatted_list(mock_svacer):
    mock_svacer.get("/api/public/projects").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "project": {
                        "id": "proj-1",
                        "name": "TestProj",
                        "time": "2025-01-01T00:00:00Z",
                        "created_by": {"string": "admin", "valid": True},
                    },
                    "branches": [
                        {"id": "br-1", "name": "main", "time": "2025-01-01T00:00:00Z"},
                    ],
                }
            ],
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_projects", {})

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert len(payload) == 1
    assert payload[0]["project_id"] == "proj-1"
    assert payload[0]["project_name"] == "TestProj"
    assert payload[0]["created_by"] == "admin"
    assert payload[0]["branches"] == [
        {"branch_id": "br-1", "branch_name": "main", "created": "2025-01-01T00:00:00Z"},
    ]


async def test_get_projects_backend_500(mock_svacer):
    mock_svacer.get("/api/public/projects").mock(
        return_value=httpx.Response(500, text="internal server error")
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_projects", {})

    assert result.isError is True
    assert "500" in result.content[0].text
