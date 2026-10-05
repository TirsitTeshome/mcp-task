"""Tests for token checks: the verifier on its own, then the real HTTP server."""

import json
import os
import socket
import subprocess
import sys
import time

import httpx2
import jwt
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from job_postings_mcp.auth import JWTTokenVerifier

SECRET = "test-secret-that-is-at-least-32-characters-long"
ISSUER = "http://localhost:9000"


def make_token(audience: str, scope: str = "postings:read", **overrides) -> str:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": audience, "sub": "alice", "scope": scope, "iat": now, "exp": now + 300}
    claims.update(overrides)
    secret = claims.pop("secret", SECRET)
    return jwt.encode(claims, secret, algorithm="HS256")


# --- Verifier unit tests ----------------------------------------------------

AUDIENCE = "http://localhost:8000/mcp"
verifier = JWTTokenVerifier(secret=SECRET, issuer=ISSUER, audience=AUDIENCE)


async def test_valid_token_is_accepted():
    access = await verifier.verify_token(make_token(AUDIENCE, scope="postings:read postings:stats"))
    assert access is not None
    assert access.subject == "alice"
    assert access.scopes == ["postings:read", "postings:stats"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 10},  # expired
        {"aud": "http://some-other-api"},  # minted for a different API
        {"iss": "http://evil-issuer"},  # wrong issuer
        {"secret": "a-different-secret-that-is-also-32-chars"},  # forged signature
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "bad-signature"],
)
async def test_bad_tokens_are_rejected(overrides):
    assert await verifier.verify_token(make_token(AUDIENCE, **overrides)) is None


async def test_unsigned_token_is_rejected():
    unsigned = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "exp": 9999999999}, None, algorithm="none")
    assert await verifier.verify_token(unsigned) is None


async def test_token_without_subject_is_rejected():
    now = int(time.time())
    token = jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "exp": now + 60}, SECRET, algorithm="HS256")
    assert await verifier.verify_token(token) is None


# --- End-to-end over HTTP ---------------------------------------------------


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    """Start the real server with --http and stop it after the tests."""
    port = free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    env = {**os.environ, "MCP_JWT_SECRET": SECRET, "MCP_ISSUER_URL": ISSUER, "MCP_SERVER_URL": url}
    process = subprocess.Popen(
        [sys.executable, "-m", "job_postings_mcp", "--http", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        process.kill()
        pytest.fail("Server did not start")
    yield url
    process.terminate()
    process.wait(timeout=5)


async def call_tool(url: str, token: str, tool: str, args: dict):
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(headers=headers) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            return await client.call_tool(tool, args)


async def test_request_without_token_gets_401(server_url):
    async with httpx2.AsyncClient() as http:
        response = await http.post(server_url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
    # Tells the client where to discover how to get a token (RFC 9728).
    assert "resource_metadata" in response.headers["www-authenticate"]


async def test_request_with_garbage_token_gets_401(server_url):
    headers = {"Authorization": "Bearer not-a-real-token"}
    async with httpx2.AsyncClient(headers=headers) as http:
        response = await http.post(server_url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401


async def test_token_without_read_scope_gets_403(server_url):
    headers = {"Authorization": f"Bearer {make_token(server_url, scope='postings:stats')}"}
    async with httpx2.AsyncClient(headers=headers) as http:
        response = await http.post(server_url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 403


async def test_read_scope_can_search(server_url):
    result = await call_tool(server_url, make_token(server_url), "search_postings", {"skill": "Python"})
    assert not result.is_error
    assert json.loads(result.content[0].text)["total_matches"] > 0


async def test_read_scope_cannot_count(server_url):
    result = await call_tool(server_url, make_token(server_url), "count_postings_by_company", {})
    assert result.is_error
    assert "postings:stats" in result.content[0].text


async def test_stats_scope_can_count(server_url):
    token = make_token(server_url, scope="postings:read postings:stats")
    result = await call_tool(server_url, token, "count_postings_by_company", {})
    assert not result.is_error
