"""Shared fixtures for integration tests."""
import base64
import json
import time

import httpx
import pytest
import respx


def _make_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.fakesig"


@pytest.fixture
def svacer_url() -> str:
    return "https://svacer-demo.ispras.ru"


@pytest.fixture(autouse=True)
def svacer_env(monkeypatch, svacer_url):
    monkeypatch.setenv("SVACER_URL", svacer_url)
    monkeypatch.setenv("SVACER_LOGIN", "test")
    monkeypatch.setenv("SVACER_PASSWORD", "test")
    monkeypatch.setenv("SVACER_TIMEOUT", "30")


@pytest.fixture
def mock_svacer(svacer_url):
    jwt = _make_jwt({"exp": int(time.time()) + 3600})
    with respx.mock(base_url=svacer_url, assert_all_called=False) as rsx:
        rsx.post("/api/public/login").mock(
            return_value=httpx.Response(200, json={"token": jwt})
        )
        yield rsx
