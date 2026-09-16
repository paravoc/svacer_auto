"""Fixtures for system tests against a live Svacer instance.

Requires SVACER_URL, SVACER_LOGIN, SVACER_PASSWORD in the environment. Run with:

    pytest -m system

Tests open an in-memory MCP session inline (`async with
create_connected_server_and_client_session(mcp)`) — same pattern as
tests/integration/. A fixture wrapping the async context-manager triggers an
anyio cancel-scope error on teardown under pytest-asyncio.
"""
import os
import uuid

import httpx
import pytest

from svacer_mcp.auth import SvacerAuth
from svacer_mcp.config import SvacerConfig
from tests.system._demo import PROJECT_NAME


def pytest_configure(config):
    config.addinivalue_line("markers", "system: live-stand tests (require real Svacer)")


@pytest.fixture(scope="session")
def svacer_url() -> str:
    """Override tests/conftest.py: read real URL from env, skip session if absent."""
    url = os.environ.get("SVACER_URL", "")
    if not url:
        pytest.skip("SVACER_URL not set")
    return url


@pytest.fixture(autouse=True)
def svacer_env():
    """Override the autouse stub from tests/conftest.py — system tests need real env."""
    yield


@pytest.fixture(scope="session", autouse=True)
def svacer_creds(svacer_url):
    """Skip the session unless URL+LOGIN+PASSWORD are all in os.environ.

    SvacerConfig defaults (svacer-demo + admin/admin) work against the demo stand,
    but we still gate on explicit env so default `pytest tests/` runs (without env set)
    don't hit the live stand. The .env file is for runtime, not tests.
    """
    if not os.environ.get("SVACER_LOGIN") or not os.environ.get("SVACER_PASSWORD"):
        pytest.skip("SVACER_LOGIN/SVACER_PASSWORD not set in environment")


@pytest.fixture
async def ephemeral_project_group():
    """Create a throwaway project group on the stand with PROJECT_NAME inside.

    Yields (group_name, project_name). The group is removed on teardown so the
    stand doesn't accumulate test artifacts. Uses admin endpoints directly —
    they're not exposed as MCP tools, so there's no need to wire this through
    SvacerAPIClient.
    """
    cfg = SvacerConfig()
    auth = SvacerAuth(cfg.url, cfg.login, cfg.password, cfg.timeout)
    group_name = f"mcp-test-{uuid.uuid4().hex[:8]}"
    containers_url = f"{cfg.url}/api/public/admin/server/containers"
    groups_url = f"{cfg.url}/api/public/admin/server/project-groups"

    async with httpx.AsyncClient(timeout=cfg.timeout) as client:
        auth._http_client = client
        headers = await auth.get_headers()

        resp = await client.post(
            containers_url,
            json={"action": "add", "type": "project-group", "name": group_name},
            headers=headers,
        )
        resp.raise_for_status()
        group_id = resp.json()["Containers"][0]["id"]

        try:
            resp = await client.post(
                groups_url,
                json={
                    "action": "add-project-to-group",
                    "project_group_name_or_id": group_name,
                    "project_name_or_id": PROJECT_NAME,
                },
                headers=headers,
            )
            resp.raise_for_status()

            yield group_name, PROJECT_NAME
        finally:
            try:
                resp = await client.post(
                    containers_url,
                    json={"action": "remove", "type": "project-group", "id": group_id},
                    headers=headers,
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                pass
