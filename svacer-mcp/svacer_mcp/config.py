"""
Configuration management for Svacer MCP Connector
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class SvacerConfig(BaseSettings):
    """Svacer connection configuration"""

    url: str = "https://svacer-demo.ispras.ru"
    login: str = "admin"
    password: str = "admin"
    timeout: int = 30
    http_port: int = 8000
    tools: str | None = None
    mcp_token: str | None = None
    mcp_resource_url: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="SVACER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def allowed_tools(self) -> set[str] | None:
        """Parse SVACER_TOOLS into a set of tool names, or None when not set."""
        if self.tools is None:
            return None
        names = {part.strip() for part in self.tools.split(",")}
        names.discard("")
        return names or None
