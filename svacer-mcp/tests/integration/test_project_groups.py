"""Integration tests for the get_project_groups tool.

get_project_groups makes two POSTs: first to /admin/server/project-groups (action=get)
to resolve the group, then to /admin/server/containers (action=list) to fetch the
projects. The "not found" edge verifies the second call is skipped when the first
returns no project_group_id.
"""
import json

import httpx
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp


async def test_get_project_groups_returns_group_with_projects(mock_svacer):
    group_route = mock_svacer.post("/api/public/admin/server/project-groups").mock(
        return_value=httpx.Response(
            200,
            json={
                "project_group_id": "grp-1",
                "project_group_name": "TestGroup",
            },
        )
    )
    containers_route = mock_svacer.post("/api/public/admin/server/containers").mock(
        return_value=httpx.Response(
            200,
            json={
                "Containers": [
                    {"id": "p-1", "name": "ProjA"},
                    {"id": "p-2", "name": "ProjB"},
                ]
            },
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_project_groups",
            {"name_or_id": "TestGroup"},
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["project_group_id"] == "grp-1"
    assert payload["project_group_name"] == "TestGroup"
    assert len(payload["projects"]) == 2
    assert payload["projects"][0]["name"] == "ProjA"

    assert group_route.called
    assert containers_route.called
    body = json.loads(containers_route.calls.last.request.content)
    assert body == {"action": "list", "parent": "grp-1", "type": "project"}


async def test_get_project_groups_group_not_found(mock_svacer):
    group_route = mock_svacer.post("/api/public/admin/server/project-groups").mock(
        return_value=httpx.Response(200, json={})
    )
    containers_route = mock_svacer.post("/api/public/admin/server/containers").mock(
        return_value=httpx.Response(200, json={"Containers": []})
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_project_groups",
            {"name_or_id": "Missing"},
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["project_group_id"] is None
    assert payload["project_group_name"] is None
    assert payload["projects"] == []

    assert group_route.called
    assert not containers_route.called
