"""Smoke tests for HTTP and STDIO transports.

These verify the server starts and answers the basic JSON-RPC handshake
(initialize + tools/list) over each transport. Tool logic is covered by the
per-tool integration tests; this is just transport plumbing.

Both tests use pytest-httpserver as the Svacer mock — it gives us a real
local HTTP endpoint, which works equally well for the in-process HTTP smoke
(respx would also intercept the localhost MCP request) and for the STDIO
subprocess (which can't see in-process patches at all).
"""
import asyncio
import socket
import sys
import time

import pytest
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from svacer_mcp.server import mcp
from tests.conftest import _make_jwt

EXPECTED_TOOLS = {
    "get_projects",
    "get_snapshots",
    "get_warnings",
    "get_markers",
    "get_project_stats",
    "get_project_groups",
    "get_advanced_file_preview",
    "get_diff",
}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def real_svacer(httpserver, monkeypatch):
    """Real local HTTP server mocking just /login — enough for lifespan auth.

    Overrides SVACER_URL set by the autouse svacer_env fixture so both the
    in-process server and any subprocess hit the local httpserver instead.
    """
    jwt = _make_jwt({"exp": int(time.time()) + 3600})
    httpserver.expect_request(
        "/api/public/login", method="POST"
    ).respond_with_json({"token": jwt})
    monkeypatch.setenv("SVACER_URL", httpserver.url_for("").rstrip("/"))


# ---------------------------------------------------------------- HTTP smoke


class _NoSignalServer(uvicorn.Server):
    """uvicorn.Server that does not register SIGINT/SIGTERM handlers.

    Default uvicorn would override pytest's signal handling (Ctrl+C, etc.) for
    the rest of the process. Tests don't need OS-signal-driven shutdown — we
    flip ``should_exit`` directly. Pattern from encode/uvicorn#1103.
    """

    def install_signal_handlers(self) -> None:
        return None


@pytest.fixture
async def http_server(real_svacer):
    """Run mcp.streamable_http_app() on a free local port via uvicorn.Server."""
    port = _free_port()
    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = _NoSignalServer(config)

    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await serve_task


async def test_http_smoke_lists_tools(http_server):
    async with streamable_http_client(f"{http_server}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    assert {t.name for t in tools.tools} == EXPECTED_TOOLS


# --------------------------------------------------------------- STDIO smoke


async def test_stdio_smoke_lists_tools(real_svacer, monkeypatch):
    monkeypatch.setenv("PYTHONUNBUFFERED", "1")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "svacer_mcp.server"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    assert {t.name for t in tools.tools} == EXPECTED_TOOLS
