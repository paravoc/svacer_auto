"""Tests for JWT token parsing and authentication logic"""
import asyncio
import time
import httpx
import pytest
import respx
from unittest.mock import AsyncMock, MagicMock

from svacer_mcp.auth import _token_expires_soon, SvacerAuth
from svacer_mcp.exceptions import SvacerAuthError
from tests.conftest import _make_jwt


def _mock_http_client_returning(response):
    """Build an AsyncMock that mimics httpx.AsyncClient.post returning *response*."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    return client


def _mock_http_client_raising(exc):
    client = AsyncMock()
    client.post = AsyncMock(side_effect=exc)
    return client


class TestTokenExpiresSoon:
    def test_expired_token(self):
        token = _make_jwt({"exp": int(time.time()) - 100})
        assert _token_expires_soon(token) is True

    def test_token_within_margin(self):
        token = _make_jwt({"exp": int(time.time()) + 30})
        assert _token_expires_soon(token, margin_seconds=60) is True

    def test_valid_token(self):
        token = _make_jwt({"exp": int(time.time()) + 3600})
        assert _token_expires_soon(token) is False

    def test_no_exp_field(self):
        token = _make_jwt({"sub": "user"})
        assert _token_expires_soon(token) is False

    def test_invalid_token_format(self):
        assert _token_expires_soon("not.a.valid.jwt.token") is True
        assert _token_expires_soon("") is True
        assert _token_expires_soon("single") is True

    def test_corrupted_base64(self):
        assert _token_expires_soon("header.!!!invalid!!!.sig") is True


class TestSvacerAuth:
    async def test_authenticate_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "test-token-123"}
        mock_response.raise_for_status = MagicMock()

        client = _mock_http_client_returning(mock_response)
        auth = SvacerAuth("https://example.com", "user", "pass", http_client=client)
        token = await auth.authenticate()
        assert token == "test-token-123"
        assert auth._token == "test-token-123"

    async def test_authenticate_no_token_in_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        client = _mock_http_client_returning(mock_response)
        auth = SvacerAuth("https://example.com", "user", "pass", http_client=client)
        with pytest.raises(SvacerAuthError, match="No token"):
            await auth.authenticate()

    async def test_authenticate_http_error(self):
        import httpx
        client = _mock_http_client_raising(httpx.ConnectError("connection refused"))
        auth = SvacerAuth("https://example.com", "user", "pass", http_client=client)
        with pytest.raises(SvacerAuthError, match="request failed"):
            await auth.authenticate()

    def test_invalidate_token(self):
        auth = SvacerAuth("https://example.com", "user", "pass")
        auth._token = "old-token"
        auth.invalidate_token()
        assert auth._token is None

    async def test_get_token_refreshes_when_expired(self):
        expired_token = _make_jwt({"exp": int(time.time()) - 100})
        new_token = _make_jwt({"exp": int(time.time()) + 3600})

        mock_response = MagicMock()
        mock_response.json.return_value = {"token": new_token}
        mock_response.raise_for_status = MagicMock()

        client = _mock_http_client_returning(mock_response)
        auth = SvacerAuth("https://example.com", "user", "pass", http_client=client)
        auth._token = expired_token

        token = await auth.get_token()
        assert token == new_token

    async def test_get_headers_returns_bearer(self):
        auth = SvacerAuth("https://example.com", "user", "pass")
        valid_token = _make_jwt({"exp": int(time.time()) + 3600})
        auth._token = valid_token
        headers = await auth.get_headers()
        assert headers["Authorization"] == f"Bearer {valid_token}"

    async def test_reuses_http_client_when_provided(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "token-via-client"}
        mock_response.raise_for_status = MagicMock()

        mock_client = _mock_http_client_returning(mock_response)
        auth = SvacerAuth("https://example.com", "user", "pass", http_client=mock_client)
        token = await auth.authenticate()
        assert token == "token-via-client"
        mock_client.post.assert_called_once()

    async def test_concurrent_get_token_logs_in_once(self):
        """5 параллельных get_token() с пустым токеном дают ровно 1 POST /login."""
        new_token = _make_jwt({"exp": int(time.time()) + 3600})
        url = "https://example.com"

        with respx.mock(base_url=url, assert_all_called=False) as rsx:
            route = rsx.post("/api/public/login").mock(
                return_value=httpx.Response(200, json={"token": new_token})
            )
            async with httpx.AsyncClient() as client:
                auth = SvacerAuth(url, "user", "pass", http_client=client)
                tokens = await asyncio.gather(*[auth.get_token() for _ in range(5)])

            assert route.call_count == 1
            assert all(t == new_token for t in tokens)
