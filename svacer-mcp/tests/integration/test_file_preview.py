"""Integration tests for the get_advanced_file_preview tool."""
import json

import httpx
from mcp.shared.memory import create_connected_server_and_client_session

from svacer_mcp.server import mcp

SNAP = "33333333-3333-4333-8333-333333333333"


async def test_get_advanced_file_preview_returns_content(mock_svacer):
    preview_route = mock_svacer.get("/api/public/advanced_file_preview").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": "int main() { return 0; }",
                "first_line": 10,
                "last_line": 12,
            },
        )
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_advanced_file_preview",
            {
                "snapshot_id": SNAP,
                "file_path": "src/main.c",
                "line": 11,
                "before": 1,
                "after": 1,
            },
        )

    assert result.isError is False
    payload = json.loads(result.content[0].text)
    assert payload["content"].startswith("int main")
    assert payload["first_line"] == 10

    params = preview_route.calls.last.request.url.params
    assert params["file"] == "src/main.c"
    assert params["snapshot"] == SNAP
    assert params["line"] == "11"
    assert params["before"] == "1"
    assert params["after"] == "1"
    assert params["output"] == "json"


async def test_get_advanced_file_preview_file_not_found(mock_svacer):
    mock_svacer.get("/api/public/advanced_file_preview").mock(
        return_value=httpx.Response(404, text="file not found")
    )

    async with create_connected_server_and_client_session(mcp) as session:
        result = await session.call_tool(
            "get_advanced_file_preview",
            {"snapshot_id": SNAP, "file_path": "src/missing.c"},
        )

    assert result.isError is True
    assert "404" in result.content[0].text
