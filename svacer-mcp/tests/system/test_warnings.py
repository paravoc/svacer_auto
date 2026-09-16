"""System test: get_warnings against live Svacer."""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp
from tests.system._demo import BRANCH_ID, PROJECT_ID, SNAPSHOT_ID

pytestmark = pytest.mark.system


async def test_get_warnings_returns_warnings_for_pinned_snapshot():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_warnings",
            {"project_id": PROJECT_ID, "branch_id": BRANCH_ID, "snapshot_id": SNAPSHOT_ID},
        )

    assert result.isError is False, result.content[0].text

    payload = json.loads(result.content[0].text)
    assert payload["total_count"] > 0
    assert payload["returned_count"] > 0
    assert len(payload["warnings"]) == payload["returned_count"]

    sample = payload["warnings"][0]
    for field in ("id", "warnClass", "file", "line"):
        assert field in sample, f"missing {field!r} in {sample}"
