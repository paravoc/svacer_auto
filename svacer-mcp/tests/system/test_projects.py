"""System test: get_projects against live Svacer."""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp
from tests.system._demo import BRANCH_NAME, PROJECT_NAME

pytestmark = pytest.mark.system


async def test_get_projects_contains_demo_project():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool("get_projects", {})

    assert result.isError is False, result.content[0].text

    payload = json.loads(result.content[0].text)
    by_name = {p["project_name"]: p for p in payload}
    assert PROJECT_NAME in by_name, f"expected {PROJECT_NAME!r} in {sorted(by_name)}"

    demo = by_name[PROJECT_NAME]
    for field in ("project_id", "project_name", "created", "branches"):
        assert field in demo

    branch_names = {b["branch_name"] for b in demo["branches"]}
    assert BRANCH_NAME in branch_names, f"expected branch {BRANCH_NAME!r} in {sorted(branch_names)}"
