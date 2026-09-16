import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from .config import SvacerConfig
from .auth import SvacerAuth
from .auth_token import StaticTokenVerifier
from .api_client import SvacerAPIClient
from .exceptions import SvacerAuthError, SvacerConfigError
from .tools import (
    get_projects,
    get_snapshots,
    get_warnings,
    get_markers,
    get_project_stats,
    get_project_groups,
    get_advanced_file_preview,
    get_diff,
    prepare_markup_import,
    apply_markup_import,
)
from .tools.descriptions import SERVER_INSTRUCTIONS


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("svacer-mcp")


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict]:
    try:
        config = SvacerConfig()
        logger.info(f"Loaded config: URL={config.url}")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        raise SvacerConfigError(f"Failed to load config: {e}") from e

    if config.login == "admin" and config.password == "admin":
        logger.warning(
            "Using default credentials (admin/admin). "
            "Set SVACER_LOGIN and SVACER_PASSWORD environment variables for production."
        )

    try:
        auth = SvacerAuth(config.url, config.login, config.password, config.timeout)
        api_client = SvacerAPIClient(auth)
        await api_client.connect()
        await auth.authenticate()
        logger.info("Successfully authenticated with Svacer")
    except SvacerAuthError:
        raise
    except Exception as e:
        logger.error(f"Failed to authenticate: {e}")
        raise SvacerAuthError(f"Failed to authenticate: {e}") from e

    try:
        yield {"api_client": api_client}
    finally:
        await api_client.aclose()
        logger.info("HTTP client closed")


_ALL_TOOLS = {
    "get_projects": get_projects,
    "get_snapshots": get_snapshots,
    "get_warnings": get_warnings,
    "get_markers": get_markers,
    "get_project_stats": get_project_stats,
    "get_project_groups": get_project_groups,
    "get_advanced_file_preview": get_advanced_file_preview,
    "get_diff": get_diff,
    "prepare_markup_import": prepare_markup_import,
    "apply_markup_import": apply_markup_import,
}


def _select_tools(allowed: set[str] | None) -> dict:
    if allowed is None:
        return _ALL_TOOLS
    unknown = allowed - _ALL_TOOLS.keys()
    if unknown:
        raise SvacerConfigError(
            f"SVACER_TOOLS contains unknown tools: {sorted(unknown)}. "
            f"Available: {sorted(_ALL_TOOLS)}"
        )
    return {name: _ALL_TOOLS[name] for name in allowed}


def build_mcp(*, token: str | None = None, resource_url: str | None = None) -> FastMCP:
    kwargs: dict = dict(name="svacer", instructions=SERVER_INSTRUCTIONS, lifespan=_lifespan)
    if token:
        kwargs["token_verifier"] = StaticTokenVerifier(token)
        kwargs["auth"] = AuthSettings(
            issuer_url=resource_url,
            resource_server_url=resource_url,
            required_scopes=["mcp"],
            # StaticTokenVerifier compares the configured local bearer token
            # directly; it does not issue JWTs with a resource audience.
            validate_token_resource=False,
        )
    server = FastMCP(**kwargs)
    selected = _select_tools(SvacerConfig().allowed_tools())
    for fn in selected.values():
        server.add_tool(fn)
    logger.info(f"Registered tools: {sorted(selected)}")
    return server


# Validate SVACER_TOOLS at import time — raise on unknown names early,
# before any tool call. Cheap (no FastMCP/network), avoids surprising
# failures deep in the request path.
_select_tools(SvacerConfig().allowed_tools())

_mcp_singleton: FastMCP | None = None


def _stdio_mcp() -> FastMCP:
    """Lazy singleton used by STDIO transport and by tests that import `mcp`.

    HTTP-режим в main() строит отдельный инстанс с auth через build_mcp(token=...).
    """
    global _mcp_singleton
    if _mcp_singleton is None:
        _mcp_singleton = build_mcp()
    return _mcp_singleton


def __getattr__(name: str):
    if name == "mcp":
        return _stdio_mcp()
    raise AttributeError(f"module 'svacer_mcp.server' has no attribute {name!r}")


def main():
    transport = os.getenv("SVACER_TRANSPORT", "stdio")
    config = SvacerConfig()
    if transport == "http":
        if not config.mcp_token:
            raise SvacerConfigError(
                "SVACER_MCP_TOKEN is required when SVACER_TRANSPORT=http. "
                "Generate one with: openssl rand -hex 32"
            )
        resource_url = config.mcp_resource_url or f"http://localhost:{config.http_port}"
        server = build_mcp(token=config.mcp_token, resource_url=resource_url)
        server.settings.host = "0.0.0.0"
        server.settings.port = config.http_port

        enable_dns_protection = os.getenv("MCP_ENABLE_DNS_REBINDING_PROTECTION", "true").lower() == "true"
        allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
        if enable_dns_protection:
            extra_hosts = os.getenv("MCP_ALLOWED_HOSTS", "")
            if extra_hosts:
                allowed_hosts.extend(h.strip() for h in extra_hosts.split(",") if h.strip())
            extra_origins = os.getenv("MCP_ALLOWED_ORIGINS", "")
            if extra_origins:
                allowed_origins.extend(o.strip() for o in extra_origins.split(",") if o.strip())
        server.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=enable_dns_protection,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )

        logger.info(
            f"Starting Svacer MCP Server (Streamable HTTP, auth enabled) on port {config.http_port}..."
        )
        logger.info(f"DNS rebinding protection: {enable_dns_protection}")
        if enable_dns_protection:
            logger.info(f"Allowed hosts: {allowed_hosts}")
            logger.info(f"Allowed origins: {allowed_origins}")
        server.run("streamable-http")
    else:
        logger.info("Starting Svacer MCP Server (STDIO)...")
        _stdio_mcp().run("stdio")


if __name__ == "__main__":
    main()
