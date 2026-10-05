"""MCP server that exposes the job postings dataset as tools.

The tool descriptions and parameter descriptions below are what the AI
assistant reads when deciding which tool to call and how to fill it in, so
they are written for a model, not just for humans.
"""

import logging
from typing import Annotated

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import tools
from .auth import SCOPE_READ, SCOPE_STATS, JWTTokenVerifier, require_scope
from .data import Seniority

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
Tools for exploring a sample dataset of 40 tech job postings.
Use search_postings to find jobs needing a skill, count_postings_by_company to
see which companies hire most for a skill, and get_posting for full details of
one posting. Skill names are matched case-insensitively.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

# Reusable, documented parameter types. Pydantic turns these into the JSON
# Schema the model sees, and rejects bad values before our code runs.
SkillParam = Annotated[
    str,
    Field(
        description="A skill or technology, e.g. 'Python', 'Rust', 'OAuth 2.0'. Case-insensitive.",
        min_length=1,
        max_length=tools.MAX_TEXT_LENGTH,
    ),
]


def build_server(verifier: JWTTokenVerifier | None = None, auth: AuthSettings | None = None) -> MCPServer:
    """Create the server.

    With no verifier (stdio), the server runs as a local process owned by the
    user, so there is no token to check. With a verifier (HTTP), every request
    must carry a valid bearer token and each tool checks its own scope.
    """
    auth_enabled = verifier is not None
    server = MCPServer(
        name="job-postings",
        instructions=INSTRUCTIONS,
        token_verifier=verifier,
        auth=auth,
    )

    def authorize(tool_name: str, scope: str) -> None:
        """Check the scope (HTTP only) and write an audit log line."""
        user = require_scope(scope) if auth_enabled else "local-user"
        logger.info("tool=%s user=%s", tool_name, user)

    @server.tool(annotations=READ_ONLY)
    def search_postings(
        skill: SkillParam,
        location: Annotated[
            str | None,
            Field(
                description="Optional city or country to filter by, e.g. 'Nairobi' or 'Kenya'. Partial match.",
                max_length=tools.MAX_TEXT_LENGTH,
            ),
        ] = None,
        seniority: Annotated[
            Seniority | None,
            Field(description="Optional seniority level to filter by."),
        ] = None,
        remote_only: Annotated[bool, Field(description="If true, only return remote-friendly postings.")] = False,
        limit: Annotated[int, Field(description="Maximum postings to return (1-25).", ge=1, le=25)] = 10,
    ) -> dict:
        """Search job postings that require a given skill, newest first.

        Use this to answer questions like "which Python jobs are open in
        Nairobi?" or "find remote Rust roles". Returns a short summary of each
        match (ID, title, company, location, remote, seniority, salary range in
        USD) plus the total number of matches. Call get_posting with an ID for
        the full skill list.
        """
        authorize("search_postings", SCOPE_READ)
        return tools.search_postings(skill, location, seniority, remote_only, limit)

    @server.tool(annotations=READ_ONLY)
    def count_postings_by_company(
        skill: Annotated[
            str | None,
            Field(
                description="Optional skill to count postings for, e.g. 'Python'. Omit to count all postings.",
                min_length=1,
                max_length=tools.MAX_TEXT_LENGTH,
            ),
        ] = None,
        top_n: Annotated[int, Field(description="How many companies to return (1-50).", ge=1, le=50)] = 10,
    ) -> dict:
        """Count job postings per company, ranked from most to fewest.

        Use this for questions like "which companies hire the most Rust
        engineers?" or "how many postings does each company have?". Returns
        counts only, not the postings themselves.
        """
        authorize("count_postings_by_company", SCOPE_STATS)
        return tools.count_postings_by_company(skill, top_n)

    @server.tool(annotations=READ_ONLY)
    def get_posting(
        posting_id: Annotated[
            str,
            Field(description="The posting ID from search_postings, e.g. 'JP-007'.", min_length=1, max_length=10),
        ],
    ) -> dict:
        """Get every detail of one job posting by its ID.

        Use this after search_postings when you need the full skill list,
        exact salary numbers or the date it was posted.
        """
        authorize("get_posting", SCOPE_READ)
        return tools.get_posting(posting_id)

    return server
