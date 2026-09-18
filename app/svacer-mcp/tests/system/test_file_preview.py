"""System test: get_advanced_file_preview against live Svacer."""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp
from tests.system._demo import FILE_PATH, SNAPSHOT_ID

pytestmark = pytest.mark.system


async def test_get_advanced_file_preview_returns_content():
    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_advanced_file_preview",
            {"snapshot_id": SNAPSHOT_ID, "file_path": FILE_PATH, "line": 1, "before": 0, "after": 50},
        )

    assert result.isError is False, result.content[0].text

    payload = json.loads(result.content[0].text)
    # /api/public/advanced_file_preview returns JSON (output=json); shape varies by
    # Svacer version, so we only assert the response is a non-empty object.
    assert isinstance(payload, dict)
    assert payload, "preview payload is empty"
