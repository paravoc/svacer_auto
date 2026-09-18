import pytest

from svacer_mcp.auth_token import StaticTokenVerifier


@pytest.fixture
def verifier():
    return StaticTokenVerifier("good-token")


async def test_verify_valid_token(verifier):
    access = await verifier.verify_token("good-token")
    assert access is not None
    assert access.token == "good-token"
    assert access.client_id == "static"
    assert access.scopes == ["mcp"]


async def test_verify_wrong_token(verifier):
    assert await verifier.verify_token("bad") is None


async def test_verify_empty_token(verifier):
    assert await verifier.verify_token("") is None


def test_constructor_rejects_empty_token():
    with pytest.raises(ValueError):
        StaticTokenVerifier("")
