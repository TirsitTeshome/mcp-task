"""Issue a short-lived access token for local testing.

This script plays the role of the OAuth 2.0 authorization server so the HTTP
server can be tried without setting up Auth0/Okta/Keycloak. In production a
real authorization server issues tokens after the user logs in and consents.

    MCP_JWT_SECRET=... python scripts/issue_dev_token.py --user alice --scope "postings:read postings:stats"
"""

import argparse
import os
import sys
import time

import jwt


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue a dev access token")
    parser.add_argument("--user", default="dev-user", help="User ID to put in the 'sub' claim")
    parser.add_argument("--scope", default="postings:read", help="Space-separated scopes to grant")
    parser.add_argument("--minutes", type=int, default=15, help="Minutes until the token expires")
    args = parser.parse_args()

    secret = os.environ.get("MCP_JWT_SECRET")
    if not secret:
        sys.exit("Set MCP_JWT_SECRET first (the same value the server uses).")

    now = int(time.time())
    claims = {
        "iss": os.environ.get("MCP_ISSUER_URL", "http://localhost:9000"),
        "aud": os.environ.get("MCP_SERVER_URL", "http://localhost:8000/mcp"),
        "sub": args.user,
        "client_id": "dev-cli",
        "scope": args.scope,
        "iat": now,
        "exp": now + args.minutes * 60,
    }
    print(jwt.encode(claims, secret, algorithm="HS256"))


if __name__ == "__main__":
    main()
