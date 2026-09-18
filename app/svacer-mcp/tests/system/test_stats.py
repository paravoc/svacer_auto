"""System test: get_project_stats against live Svacer."""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp
from tests.system._demo import BRANCH_ID, PROJECT_ID, SNAPSHOT_ID

pytestmark = pytest.mark.system


async def test_get_project_stats_aggregates_pinned_snapshot():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_project_stats",
            {"project_id": PROJECT_ID, "branch_id": BRANCH_ID, "snapshot_id": SNAPSHOT_ID},
        )

    assert result.isError is False, result.content[0].text

    payload = json.loads(result.content[0].text)
    assert payload["total_warnings"] > 0

    by_sev = payload["by_severity"]
    assert by_sev, "by_severity is empty"
    assert sum(by_sev.values()) == payload["total_warnings"]

    by_status = payload["by_review_status"]
    assert by_status, "by_review_status is empty"
    assert sum(by_status.values()) == payload["total_warnings"]

    by_checker = payload["by_checker"]
    assert by_checker, "by_checker is empty"
    assert sum(by_checker.values()) == payload["total_warnings"]
