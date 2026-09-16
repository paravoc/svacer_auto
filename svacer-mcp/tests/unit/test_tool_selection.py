"""Tests for SVACER_TOOLS tool subset selection."""
import importlib

import pytest

from svacer_mcp.config import SvacerConfig
from svacer_mcp.exceptions import SvacerConfigError


class TestAllowedTools:
    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("SVACER_TOOLS", raising=False)
        assert SvacerConfig().allowed_tools() is None

    def test_empty_string_returns_none(self, monkeypatch):
        monkeypatch.setenv("SVACER_TOOLS", "")
        assert SvacerConfig().allowed_tools() is None

    def test_single_tool(self, monkeypatch):
        monkeypatch.setenv("SVACER_TOOLS", "get_projects")
        assert SvacerConfig().allowed_tools() == {"get_projects"}

    def test_csv_with_whitespace(self, monkeypatch):
        monkeypatch.setenv("SVACER_TOOLS", "get_projects, get_snapshots , get_markers")
        assert SvacerConfig().allowed_tools() == {
            "get_projects",
            "get_snapshots",
            "get_markers",
        }

    def test_trailing_comma(self, monkeypatch):
        monkeypatch.setenv("SVACER_TOOLS", "get_projects,,get_snapshots,")
        assert SvacerConfig().allowed_tools() == {"get_projects", "get_snapshots"}


class TestSelectTools:
    def _reload_server(self):
        # server.py reads SvacerConfig at import time; reload to apply env changes.
        import svacer_mcp.server as server
        return importlib.reload(server)

    def test_default_registers_all_eight(self, monkeypatch):
        monkeypatch.delenv("SVACER_TOOLS", raising=False)
        server = self._reload_server()
        registered = {t.name for t in server.mcp._tool_manager.list_tools()}
        assert registered == set(server._ALL_TOOLS)

    def test_subset_registers_only_listed(self, monkeypatch):
        monkeypatch.setenv("SVACER_TOOLS", "get_projects,get_snapshots,get_markers")
        server = self._reload_server()
        registered = {t.name for t in server.mcp._tool_manager.list_tools()}
        assert registered == {"get_projects", "get_snapshots", "get_markers"}

    def test_unknown_tool_raises(self, monkeypatch):
        monkeypatch.setenv("SVACER_TOOLS", "get_projects,not_a_tool")
        with pytest.raises(SvacerConfigError, match="not_a_tool"):
            self._reload_server()

    @pytest.fixture(autouse=True)
    def _restore_default_module(self, monkeypatch):
        # After this class runs, leave svacer_mcp.server reloaded with the
        # default (all-tools) registration so other tests see expected state.
        yield
        monkeypatch.delenv("SVACER_TOOLS", raising=False)
        import svacer_mcp.server as server
        importlib.reload(server)
