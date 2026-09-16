"""System test: get_diff against live Svacer."""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp
from tests.system._demo import SNAPSHOT_ID, SNAPSHOT_PREV_ID

pytestmark = pytest.mark.system


async def test_get_diff_level_zero_returns_summary():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_diff",
            {
                "base_snapshot_id": SNAPSHOT_PREV_ID,
                "head_snapshot_id": SNAPSHOT_ID,
                "level": 0,
            },
        )

    assert result.isError is False, result.content[0].text

    payload = json.loads(result.content[0].text)
    assert isinstance(payload, dict)
    # level=0 — категории маркеров не раскрываются в обёртку с total_count.
    markers = payload.get("markers") or {}
    if isinstance(markers, dict):
        for cat in ("new_markers", "missing_markers", "modified_markers", "matched_markers"):
            val = markers.get(cat)
            if val is None:
                continue
            assert not isinstance(val, dict), f"{cat} unexpectedly wrapped at level=0: {val}"
