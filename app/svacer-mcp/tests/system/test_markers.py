"""System test: get_markers against live Svacer."""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp
from tests.system._demo import BRANCH_ID, PROJECT_ID, SNAPSHOT_ID

pytestmark = pytest.mark.system


async def test_get_markers_severity_filter_keeps_only_matching():
    """Critical-only must yield markers whose review.severity is Critical (or empty list)."""
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {
                "project_id": PROJECT_ID,
                "branch_id": BRANCH_ID,
                "snapshot_id": SNAPSHOT_ID,
                "severity": ["Critical"],
            },
        )

    assert result.isError is False, result.content[0].text

    payload = json.loads(result.content[0].text)
    assert payload["filters_applied"]["severity"] == ["Critical"]
    for marker in payload["markers"]:
        review = marker.get("review") or {}
        assert review.get("severity") == "Critical", marker


async def test_get_markers_fields_whitelist():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_markers",
            {
                "project_id": PROJECT_ID,
                "branch_id": BRANCH_ID,
                "snapshot_id": SNAPSHOT_ID,
                "fields": ["id", "warnClass"],
            },
        )

    assert result.isError is False, result.content[0].text

    payload = json.loads(result.content[0].text)
    assert payload["filters_applied"]["fields"] == ["id", "warnClass"]
    if payload["markers"]:
        assert set(payload["markers"][0].keys()) == {"id", "warnClass"}
