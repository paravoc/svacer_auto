"""main() must fail loudly if SVACER_TRANSPORT=http and no SVACER_MCP_TOKEN."""
import pytest

from svacer_mcp import server
from svacer_mcp.exceptions import SvacerConfigError


def test_http_without_token_raises(monkeypatch):
    monkeypatch.setenv("SVACER_TRANSPORT", "http")
    monkeypatch.delenv("SVACER_MCP_TOKEN", raising=False)

    called = []
    monkeypatch.setattr(server.mcp, "run", lambda *a, **kw: called.append(("stdio_mcp", a)))

    with pytest.raises(SvacerConfigError, match="SVACER_MCP_TOKEN"):
        server.main()

    assert called == []


def test_stdio_does_not_require_token(monkeypatch):
    monkeypatch.setenv("SVACER_TRANSPORT", "stdio")
    monkeypatch.delenv("SVACER_MCP_TOKEN", raising=False)

    runs = []
    monkeypatch.setattr(server.mcp, "run", lambda transport: runs.append(transport))

    server.main()

    assert runs == ["stdio"]
