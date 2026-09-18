#!/usr/bin/env python3
"""Run one shared, authenticated Svacer MCP server on loopback only."""

from __future__ import annotations

import os

from mcp.server.transport_security import TransportSecuritySettings

from svacer_mcp.config import SvacerConfig
from svacer_mcp.exceptions import SvacerConfigError
from svacer_mcp.server import build_mcp


def main() -> None:
    config = SvacerConfig()
    token = config.mcp_token
    if not token:
        raise SvacerConfigError("SVACER_MCP_TOKEN is required")

    host = "127.0.0.1"
    port = config.http_port
    resource_url = config.mcp_resource_url or f"http://{host}:{port}"
    server = build_mcp(token=token, resource_url=resource_url)
    server.settings.host = host
    server.settings.port = port
    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
    )
    server.run("streamable-http")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    main()
