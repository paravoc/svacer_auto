"""System test: get_snapshots against live Svacer."""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp
from tests.system._demo import BRANCH_ID, PROJECT_ID, SNAPSHOT_ID

pytestmark = pytest.mark.system


async def test_get_snapshots_contains_pinned_snapshot():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_snapshots",
            {"project_id": PROJECT_ID, "branch_id": BRANCH_ID},
        )

    assert result.isError is False, result.content[0].text

    payload = json.loads(result.content[0].text)
    assert len(payload) > 0

    ids = {s["snapshot_id"] for s in payload}
    assert SNAPSHOT_ID in ids, f"pinned snapshot {SNAPSHOT_ID!r} not in {sorted(ids)}"

    pinned = next(s for s in payload if s["snapshot_id"] == SNAPSHOT_ID)
    for field in ("name", "import_time", "markers_count"):
        assert field in pinned
    assert isinstance(pinned["markers_count"], int)
