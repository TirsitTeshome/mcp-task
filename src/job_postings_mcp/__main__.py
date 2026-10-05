"""Command-line entry point.

    python -m job_postings_mcp          # stdio, for Claude Desktop / MCP Inspector
    python -m job_postings_mcp --http   # Streamable HTTP, every request needs a bearer token
"""

import argparse
import logging
import os
import sys

from mcp.server.auth.settings import AuthSettings

from .auth import SCOPE_READ, JWTTokenVerifier
from .server import build_server

MIN_SECRET_LENGTH = 32


def build_http_auth(port: int) -> tuple[JWTTokenVerifier, AuthSettings]:
    """Read auth config from the environment. Refuse to start without a strong secret."""
    secret = os.environ.get("MCP_JWT_SECRET", "")
    if len(secret) < MIN_SECRET_LENGTH:
        sys.exit(
            f"MCP_JWT_SECRET must be set to at least {MIN_SECRET_LENGTH} characters to run over HTTP. "
            "See .env.example."
        )

    issuer = os.environ.get("MCP_ISSUER_URL", "http://localhost:9000")
    server_url = os.environ.get("MCP_SERVER_URL", f"http://localhost:{port}/mcp")

    verifier = JWTTokenVerifier(secret=secret, issuer=issuer, audience=server_url)
    auth = AuthSettings(
        issuer_url=issuer,
        resource_server_url=server_url,
        required_scopes=[SCOPE_READ],  # baseline scope for any request
        validate_token_resource=False,  # our verifier already checks the `aud` claim
    )
    return verifier, auth


def main() -> None:
    parser = argparse.ArgumentParser(description="Job postings MCP server")
    parser.add_argument("--http", action="store_true", help="Serve over Streamable HTTP with bearer token auth")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000)")
    args = parser.parse_args()

    # Logs go to stderr: on stdio, stdout is reserved for MCP protocol messages.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.http:
        verifier, auth = build_http_auth(args.port)
        build_server(verifier, auth).run("streamable-http", host=args.host, port=args.port)
    else:
        build_server().run()


if __name__ == "__main__":
    main()
