"""
Authentication management for Svacer API
"""
import asyncio
import base64
import json
import logging
import time
import httpx
from typing import Optional

from .exceptions import SvacerAuthError

logger = logging.getLogger("svacer-mcp")


def _token_expires_soon(token: str, margin_seconds: int = 60) -> bool:
    """Check if JWT payload has exp in the past or within margin_seconds."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return True
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        if exp is None:
            return False
        return time.time() >= (exp - margin_seconds)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Failed to parse JWT token, treating as expired")
        return True


class SvacerAuth:
    """Manages JWT authentication with Svacer"""

    def __init__(self, url: str, login: str, password: str, timeout: int = 30,
                 http_client: Optional[httpx.AsyncClient] = None):
        self.url = url.rstrip('/')
        self.login = login
        self.password = password
        self.timeout = timeout
        self._token: Optional[str] = None
        self._http_client = http_client
        self._lock = asyncio.Lock()

    def invalidate_token(self) -> None:
        """Clear cached token so next get_token() will re-authenticate."""
        self._token = None

    async def authenticate(self) -> str:
        """
        Get JWT token from Svacer

        Returns:
            JWT token string

        Raises:
            SvacerAuthError: If authentication fails
        """
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    f"{self.url}/api/public/login",
                    json={"login": self.login, "password": self.password},
                    timeout=self.timeout
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.url}/api/public/login",
                        json={"login": self.login, "password": self.password},
                    )
            response.raise_for_status()

            data = response.json()
            self._token = data.get("token")

            if not self._token:
                raise SvacerAuthError("No token in authentication response")

            return self._token

        except httpx.HTTPStatusError as e:
            raise SvacerAuthError(
                f"Authentication failed with status {e.response.status_code}: {e}"
            ) from e
        except httpx.HTTPError as e:
            raise SvacerAuthError(
                f"Authentication request failed: {e}"
            ) from e

    async def get_token(self) -> str:
        """
        Get current token, re-authenticate if missing or expires soon.

        Returns:
            Valid JWT token
        """
        if self._token and not _token_expires_soon(self._token):
            return self._token
        async with self._lock:
            if self._token and not _token_expires_soon(self._token):
                return self._token
            await self.authenticate()
            return self._token

    async def get_headers(self) -> dict:
        """Get authorization headers with current token"""
        return {
            "Authorization": f"Bearer {await self.get_token()}"
        }
