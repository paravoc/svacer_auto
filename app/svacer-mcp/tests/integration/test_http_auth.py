"""HTTP /mcp must reject requests without a valid bearer token.

Builds a fresh auth-enabled FastMCP instance via build_mcp(token=...) and
runs it on a free local port using the same _NoSignalServer pattern as
test_smoke.py. Svacer is mocked by httpserver via the real_svacer fixture.
"""
import asyncio
import socket
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from svacer_mcp.server import build_mcp
from tests.conftest import _make_jwt

TOKEN = "test-secret-token-do-not-use-in-prod"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _NoSignalServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        return None


@pytest.fixture
def real_svacer(httpserver, monkeypatch):
    jwt = _make_jwt({"exp": int(time.time()) + 3600})
    httpserver.expect_request(
        "/api/public/login", method="POST"
    ).respond_with_json({"token": jwt})
    monkeypatch.setenv("SVACER_URL", httpserver.url_for("").rstrip("/"))


@pytest.fixture
async def http_server(real_svacer):
    port = _free_port()
    auth_mcp = build_mcp(token=TOKEN, resource_url=f"http://127.0.0.1:{port}")
    app = auth_mcp.streamable_http_app()
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


_INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
_INITIALIZE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


async def test_no_authorization_returns_401(http_server):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{http_server}/mcp",
            json=_INITIALIZE_BODY,
            headers=_INITIALIZE_HEADERS,
        )
    assert resp.status_code == 401
    www_auth = resp.headers.get("WWW-Authenticate", "")
    assert www_auth.lower().startswith("bearer")
    assert "resource_metadata" in www_auth


async def test_wrong_token_returns_401(http_server):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{http_server}/mcp",
            json=_INITIALIZE_BODY,
            headers={**_INITIALIZE_HEADERS, "Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401


async def test_valid_token_lists_tools(http_server):
    client = httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"})
    async with client:
        async with streamable_http_client(
            f"{http_server}/mcp", http_client=client
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
    names = {t.name for t in tools.tools}
    assert "get_projects" in names
    assert "get_snapshots" in names
