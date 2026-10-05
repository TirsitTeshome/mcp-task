# Job Postings MCP Server

A small [Model Context Protocol](https://modelcontextprotocol.io) server, built with the official
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (v2), that lets an AI assistant
search a sample dataset of 40 tech job postings.

It runs in two modes:

- **stdio** for local use with Claude Desktop or the MCP Inspector
- **Streamable HTTP**, where **every request must carry a valid bearer token** and each tool checks its own scope

It also includes a small [Rust program](#rust-reader) that reads the same dataset.

---

## Tools

| Tool | What it answers | Inputs |
|---|---|---|
| `search_postings` | "Which remote Rust jobs are open?" | `skill` (required), `location`, `seniority` (`intern`/`junior`/`mid`/`senior`), `remote_only`, `limit` (1-25, default 10) |
| `count_postings_by_company` | "Which companies hire the most Python engineers?" | `skill` (optional), `top_n` (1-50, default 10) |
| `get_posting` | "Show me the full details of JP-038" | `posting_id` (e.g. `JP-038`) |

All three are marked read-only (`readOnlyHint`), so clients know they change nothing.

### Design choices for the model

- **Descriptions say *when* to use a tool**, not only what it does, so the model can choose between
  `search_postings` (rows) and `count_postings_by_company` (totals).
- **Every parameter has a description, type and limit** in its JSON Schema, so the model sees the rules before it calls.
- **Compact results.** Search returns seven short fields per posting plus `total_matches`. When results are
  cut off, a `note` says so and explains how to see more, so the model does not assume it saw everything.
  Full detail is one `get_posting` call away.
- **Stable ordering.** Search returns newest first. Counts are ranked highest first, with ties sorted alphabetically.
- **Forgiving where it is safe.** Skill names are case-insensitive (`rust` finds `Rust`), and IDs are upper-cased (`jp-001` works).

## Input validation

Bad input never crashes the server. The model gets an error result (`isError: true`) with a message it
can act on:

| Request | Error the model sees |
|---|---|
| `search_postings(skill="Pyhton")` | `No postings list the skill 'Pyhton'. Did you mean: Python? Known skills: Airflow, AWS, ...` |
| `search_postings(skill="   ")` | `'skill' must not be empty.` |
| `search_postings(skill="Python", limit=500)` | `limit: Input should be less than or equal to 25` |
| `search_postings(skill="Python", seniority="principal")` | `Input should be 'intern', 'junior', 'mid' or 'senior'` |
| `get_posting(posting_id="JP-7")` | `'JP-7' is not a valid posting ID. IDs look like 'JP-001'; get them from search_postings.` |
| `get_posting(posting_id="JP-999")` | `No posting has ID 'JP-999'. Use search_postings to find valid IDs.` |
| `search_postings(skill="Rust", location="Lagos")` | Not an error: 0 results and a `note` suggesting which filters to remove. |

Validation happens in two layers:

1. **Schema (Pydantic):** types, enums, required fields, number ranges and string lengths are checked
   before any of our code runs.
2. **Business rules (`tools.py`):** whether the skill exists (with spelling suggestions), the ID format,
   blank strings and unknown IDs. These raise `ToolError`, the SDK's way of saying "expected failure,
   show this message to the model".

See [docs/demo-output.txt](docs/demo-output.txt) for real output from every tool, including errors.

---

## Quick start

Requires Python 3.10+.

```bash
git clone https://github.com/TirsitTeshome/mcp-task.git
cd mcp-task
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest                            # 33 tests
python scripts/demo_client.py     # starts the server over stdio and calls every tool
```

### Try it in the MCP Inspector

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m job_postings_mcp
```

Open the URL it prints, click **Connect**, then **Tools → List Tools**, and call a tool.

### Use it from Claude Desktop

Add this to `claude_desktop_config.json` (use absolute paths), then restart Claude Desktop:

```json
{
  "mcpServers": {
    "job-postings": {
      "command": "/absolute/path/to/mcp-task/.venv/bin/python",
      "args": ["-m", "job_postings_mcp"]
    }
  }
}
```

Then ask, for example: *"Which companies are hiring the most for Python, and show me the remote ones in Kenya."*

### Run over HTTP with token checks

```bash
export MCP_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m job_postings_mcp --http --port 8000

# In another terminal (same MCP_JWT_SECRET), issue a 15-minute dev token:
TOKEN=$(python scripts/issue_dev_token.py --user alice --scope "postings:read postings:stats")

curl -i -X POST http://localhost:8000/mcp                         # 401 + WWW-Authenticate header
curl http://localhost:8000/.well-known/oauth-protected-resource/mcp  # where to get a token
npx @modelcontextprotocol/inspector   # choose "Streamable HTTP", URL http://localhost:8000/mcp,
                                      # and add header  Authorization: Bearer $TOKEN
```

The server refuses to start without a secret of at least 32 characters. Secrets come only from the
environment and are never committed (see [.env.example](.env.example)).

### Deploy to Railway

The [Dockerfile](Dockerfile) runs the authenticated HTTP server and listens on Railway's `$PORT`.

1. In Railway, create a project from this GitHub repo. Railway builds it with the Dockerfile.
2. Under **Settings → Networking**, click **Generate Domain**.
3. Under **Variables**, set:
   - `MCP_JWT_SECRET`: a new random secret (`python -c 'import secrets; print(secrets.token_urlsafe(32))'`)
   - `MCP_SERVER_URL`: `https://<your-domain>.up.railway.app/mcp`
4. Issue a token locally with the same values, and connect the Inspector to the Railway URL:

```bash
MCP_JWT_SECRET=<same secret> MCP_SERVER_URL=https://<your-domain>.up.railway.app/mcp \
  python scripts/issue_dev_token.py --scope "postings:read postings:stats"
```

---

## Protecting the server with OAuth 2.0

### Roles

| OAuth role | In this system |
|---|---|
| **Resource owner** | The Revelio customer (a person at a company with a data licence) |
| **Client** | The AI assistant's MCP client (Claude, ChatGPT, an in-house agent) |
| **Authorization server** | A dedicated identity provider (Auth0, Okta, Keycloak, ...). The MCP server never sees passwords. |
| **Resource server** | This MCP server. It only *validates* tokens; it never issues them. |

### Which flow: Authorization Code + PKCE

The MCP authorization spec requires **Authorization Code with PKCE** for user-facing clients, and it is
the right fit:

- A **real user** must log in and consent, so we know *who* is asking, not only *which app*.
  Client Credentials would identify only the app.
- MCP clients are often **public clients** (desktop apps, CLIs) that cannot keep a client secret.
  PKCE ties the code to the client that started the flow, so a stolen authorization code is useless.
- The Implicit and Password grants are deprecated in OAuth 2.1 and are not used.

### The flow, step by step

```
 MCP client                    MCP server (resource server)          Authorization server
     |  1. POST /mcp (no token)          |                                    |
     |---------------------------------->|                                    |
     |  2. 401 WWW-Authenticate:         |                                    |
     |     resource_metadata=".../.well-known/oauth-protected-resource/mcp"   |
     |<----------------------------------|                                    |
     |  3. GET protected resource metadata (RFC 9728)                         |
     |     -> authorization_servers, scopes_supported                         |
     |  4. GET AS metadata (RFC 8414): authorize + token endpoints            |
     |----------------------------------------------------------------------->|
     |  5. Browser: /authorize?response_type=code&code_challenge=S256(...)    |
     |     &scope=postings:read&resource=https://mcp.example.com/mcp          |
     |----------------------------------------------------------------------->|
     |           user logs in, sees the scopes, and consents                  |
     |  6. redirect back with ?code=...                                       |
     |<-----------------------------------------------------------------------|
     |  7. POST /token: code + code_verifier                                  |
     |     -> access_token (JWT, ~15 min) + refresh_token                     |
     |<-----------------------------------------------------------------------|
     |  8. POST /mcp  Authorization: Bearer <access_token>                    |
     |---------------------------------->|  validate token, check scope, run tool
```

Steps 1 to 3 are implemented and tested here (`test_request_without_token_gets_401` checks the
`WWW-Authenticate` header). The `resource` parameter in step 5 (RFC 8707 resource indicators) makes the
authorization server put this server's URL in the token's `aud` claim, so a token for another API
cannot be replayed here.

**Refresh tokens:** access tokens are short-lived (about 15 minutes). The client uses the refresh token
to get a new one without a new login. Refresh tokens should be **rotated** on every use, and reuse of
an old one should revoke the whole chain, which is a strong sign it was stolen.

### Where tokens are checked

Every HTTP request passes through three checks, in this order:

1. **Bearer middleware (SDK, every request).** Missing or invalid token → `401` with a
   `WWW-Authenticate` header that points to the metadata. A valid token without the baseline
   `postings:read` scope → `403`.
2. **`JWTTokenVerifier.verify_token`** ([auth.py](src/job_postings_mcp/auth.py)), called by that
   middleware. It checks:
   - the **signature**, accepting only the algorithm we expect, so `alg: none` and forged tokens fail
   - **`exp`**, so expired tokens fail
   - **`iss`**, so the token must come from our authorization server
   - **`aud`**, so the token must be issued *for this server*
   - **`sub`**, which is required, because every request must be tied to a user
3. **Per-tool scope check (`require_scope`)** inside each tool, for permissions beyond the baseline.
   It fails closed: if no token is found, the call is refused, not allowed.

Tokens are never logged, and the server **never forwards the client's token** to other APIs
(the MCP spec forbids this "token passthrough"). If it needed to call another service, it would get
its own token for that service.

In this demo the authorization server is `scripts/issue_dev_token.py`, which signs tokens with a shared
HS256 secret. In production the server would verify **RS256/ES256** tokens with public keys fetched from
the authorization server's **JWKS** endpoint, so the MCP server holds no signing secret at all.

### Scopes

| Scope | Grants | Tools |
|---|---|---|
| `postings:read` | Search postings and read single postings. Baseline, required for any request. | `search_postings`, `get_posting` |
| `postings:stats` | Aggregate counts across companies | `count_postings_by_company` |
| `postings:export` *(future)* | Large or bulk results | none yet; kept separate so normal assistant use never needs bulk access |

Scopes are kept narrow so a user can grant an assistant only what it needs (least privilege). They are
tested end to end: a `postings:read` token can search but gets a clear error from
`count_postings_by_company` naming the missing `postings:stats` scope.

### Beyond scopes: which data a user may see

Scopes say *what kind of action* is allowed. Revelio also needs to control *which data*: a customer
should only see the datasets, regions or companies their contract covers. In production I would:

- put a tenant or entitlement claim in the token (for example `org_id`), or look entitlements up by `sub`
- apply that filter **inside the data layer**, before results are built, so no tool can forget it
- never trust tool arguments for identity: the user always comes from the validated token, not from
  anything the model sends

### Threats I considered

| Threat | Mitigation |
|---|---|
| Stolen access token | Short expiry, HTTPS only, `aud` binding, never logged |
| Token minted for another API replayed here | `aud` check (test: `wrong-audience`) |
| Forged or unsigned token | Signature check with a fixed algorithm list (tests: `bad-signature`, `unsigned`) |
| Stolen authorization code | PKCE |
| Over-privileged assistant | Narrow scopes, checked per tool |
| Model sends huge or malicious input | Schema limits on every string and number; text is only compared, never executed or used in queries |
| Model or user floods the server | `limit`/`top_n` caps. **Next step:** per-user rate limiting keyed on `sub` (for example a token bucket) returning `429` |
| Prompt injection through data (a posting whose text says "ignore previous instructions") | Return structured JSON fields, keep tools read-only, and never let tool output trigger privileged actions |
| DNS rebinding against a local HTTP server | Binds to `127.0.0.1` by default; the SDK's transport security validates the `Host` header |
| Secrets in git | Secrets only from env vars; `.env` is git-ignored; the server refuses to start with a weak secret |

### What runs over stdio?

The stdio server has no token check. That follows the MCP spec: a stdio server is a local process
started by the user's own client, so it runs with the user's own permissions and gets credentials from
its environment. OAuth applies to the HTTP transport, where the server is reachable over the network.

---

## Rust reader

[rust_reader/](rust_reader/) is a small Rust program that reads the same `data/job_postings.json` with
`serde` and prints the postings that need a skill, plus a count per company. It uses the same
case-insensitive matching as the Python server, so both agree (10 Rust postings).

```bash
cd rust_reader
cargo run -- rust
```

```
10 of 40 postings need 'rust':

  JP-016  Senior Robotics Engineer at Lumen Robotics, Berlin, Germany (remote)
  ...
Postings per company:
   3  Harbor Security
   5  Lumen Robotics
   2  Orbit Cloud
```

Bad input exits with a clear message and a non-zero code (`usage: rust_reader <skill> [path-to-json]`).

---

## Project layout

```
data/job_postings.json        Sample dataset (40 postings, fictional companies)
src/job_postings_mcp/
  data.py                     Loads and validates the dataset (Pydantic)
  tools.py                    Tool logic and business-rule validation (no MCP or auth code)
  server.py                   Registers the tools: names, descriptions, typed inputs
  auth.py                     JWT verifier and per-tool scope check
  __main__.py                 CLI: stdio by default, --http for authenticated HTTP
scripts/
  demo_client.py              Calls every tool over stdio (output in docs/demo-output.txt)
  issue_dev_token.py          Stand-in authorization server for local testing
tests/
  test_tools.py               Tool behaviour and bad input, through a real MCP client
  test_auth.py                Verifier unit tests + end-to-end HTTP tests (401/403/scopes)
rust_reader/                  Rust program over the same dataset
```

## What I learned along the way

- **The SDK changed under me.** The latest SDK is v2, where `FastMCP` was renamed `MCPServer`. Most
  tutorials still show v1 code. I read the installed SDK source to find the current API instead of
  pinning an old version.
- **Plain exceptions hide the message from the model.** At first I raised `ValueError` for bad input.
  In SDK v2 that is treated as a crash, and the model sees only `Error executing tool search_postings`,
  with nothing to fix. Raising `ToolError` sends the real message, so the model can correct itself.
- **On stdio, logging must go to stderr.** stdout carries the protocol messages, and a stray `print`
  would corrupt them.
- **`required_scopes` does two jobs in the SDK.** It is enforced on every request *and* advertised as
  `scopes_supported` in the metadata. So I used it for the baseline `postings:read` scope and kept
  finer-grained scopes as per-tool checks.
