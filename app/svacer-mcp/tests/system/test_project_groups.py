"""System test: get_project_groups against live Svacer."""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp

pytestmark = pytest.mark.system


async def test_get_project_groups_returns_pinned_group(ephemeral_project_group):
    group_name, expected_project = ephemeral_project_group

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_project_groups",
            {"name_or_id": group_name},
        )

    assert result.isError is False, result.content[0].text

    payload = json.loads(result.content[0].text)
    assert payload["project_group_name"] == group_name
    assert payload["project_group_id"]

    project_names = {p.get("name") for p in payload["projects"]}
    assert expected_project in project_names, (
        f"expected {expected_project!r} in {sorted(project_names)}"
    )
