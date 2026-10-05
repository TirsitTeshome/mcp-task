"""Bearer token checks for the HTTP transport.

In production the tokens would come from a real OAuth 2.0 authorization server
(Auth0, Okta, Keycloak, ...) and be signed with its private key (RS256), with the
public keys fetched from its JWKS endpoint. For this demo the "authorization
server" is `scripts/issue_dev_token.py`, which signs tokens with a shared HS256
secret. The checks below are the same either way: signature, expiry, issuer,
audience and scopes.
"""

import logging

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.mcpserver.exceptions import ToolError

logger = logging.getLogger(__name__)

# Scopes this server understands. Keep them narrow: least privilege.
SCOPE_READ = "postings:read"  # search postings and read single postings
SCOPE_STATS = "postings:stats"  # aggregate counts across companies


class JWTTokenVerifier(TokenVerifier):
    """Validate a JWT access token and turn it into an `AccessToken`.

    The SDK's bearer middleware calls `verify_token` on every HTTP request.
    Returning `None` makes the middleware answer 401 Unauthorized.
    """

    def __init__(self, secret: str, issuer: str, audience: str) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],  # never let the token choose its own algorithm
                issuer=self._issuer,
                audience=self._audience,  # reject tokens minted for a different API
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.InvalidTokenError as error:
            # Log why, but never log the token itself.
            logger.warning("Rejected access token: %s", error)
            return None

        return AccessToken(
            token=token,
            client_id=claims.get("client_id", "unknown"),
            scopes=claims.get("scope", "").split(),
            expires_at=claims["exp"],
            resource=self._audience,
            subject=claims["sub"],
        )


def require_scope(scope: str) -> str:
    """Stop the tool call unless the caller's token grants `scope`.

    Returns the user ID (`sub` claim) so the caller can log who did what.
    """
    token = get_access_token()
    if token is None:
        # Only reachable if auth is misconfigured; fail closed, not open.
        raise ToolError("This request is not authenticated.")
    if scope not in token.scopes:
        raise ToolError(f"Your access token is missing the '{scope}' scope needed for this tool.")
    return token.subject or token.client_id
