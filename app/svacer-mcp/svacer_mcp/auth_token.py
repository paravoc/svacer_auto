import secrets

from mcp.server.auth.provider import AccessToken, TokenVerifier


class StaticTokenVerifier(TokenVerifier):
    def __init__(self, token: str):
        if not token:
            raise ValueError("token must be non-empty")
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token, self._token):
            return AccessToken(token=token, client_id="static", scopes=["mcp"])
        return None
