"""The business logic behind each MCP tool.

These functions know nothing about MCP transports or auth. They take plain
Python values, validate them, and return small dictionaries that are easy for
a language model to read. When a request is wrong they raise `ToolError` with a
message that tells the model how to fix its next call.
"""

import difflib
import re
from collections import Counter

from mcp.server.mcpserver.exceptions import ToolError

from .data import JobPosting, Seniority, known_skills, load_postings

MAX_TEXT_LENGTH = 60
POSTING_ID_PATTERN = re.compile(r"^JP-\d{3}$")


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _clean_text(value: str, field: str) -> str:
    """Trim whitespace and reject empty or oversized text."""
    cleaned = value.strip()
    if not cleaned:
        raise ToolError(f"'{field}' must not be empty.")
    if len(cleaned) > MAX_TEXT_LENGTH:
        raise ToolError(f"'{field}' must be at most {MAX_TEXT_LENGTH} characters, got {len(cleaned)}.")
    return cleaned


def _resolve_skill(skill: str, postings: tuple[JobPosting, ...]) -> str:
    """Return the skill exactly as the dataset spells it, or explain what is valid."""
    skill = _clean_text(skill, "skill")
    skills = known_skills(postings)
    by_lowercase = {s.casefold(): s for s in skills}

    if skill.casefold() in by_lowercase:
        return by_lowercase[skill.casefold()]

    suggestions = difflib.get_close_matches(skill.casefold(), by_lowercase.keys(), n=3, cutoff=0.6)
    hint = f" Did you mean: {', '.join(by_lowercase[s] for s in suggestions)}?" if suggestions else ""
    raise ToolError(f"No postings list the skill '{skill}'.{hint} Known skills: {', '.join(skills)}.")


def _compact(posting: JobPosting) -> dict:
    """The fields a model needs to answer most questions, without the noise."""
    return {
        "id": posting.id,
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "remote": posting.remote,
        "seniority": posting.seniority,
        "salary_usd": f"{posting.salary_usd.min:,}-{posting.salary_usd.max:,}",
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def search_postings(
    skill: str,
    location: str | None = None,
    seniority: Seniority | None = None,
    remote_only: bool = False,
    limit: int = 10,
) -> dict:
    """Find postings that require a skill, with optional filters."""
    postings = load_postings()
    skill = _resolve_skill(skill, postings)
    location = _clean_text(location, "location") if location is not None else None

    matches = [
        p
        for p in postings
        if p.has_skill(skill)
        and (location is None or location.casefold() in p.location.casefold())
        and (seniority is None or p.seniority == seniority)
        and (not remote_only or p.remote)
    ]
    # Newest first, so the model sees the most relevant postings at the top.
    matches.sort(key=lambda p: p.posted_date, reverse=True)
    shown = matches[:limit]

    result: dict = {
        "skill": skill,
        "total_matches": len(matches),
        "returned": len(shown),
        "postings": [_compact(p) for p in shown],
    }
    if len(matches) > len(shown):
        result["note"] = f"Showing {len(shown)} of {len(matches)}. Raise 'limit' or add filters to see more."
    if not matches:
        result["note"] = "No postings match all filters. Try removing 'location', 'seniority' or 'remote_only'."
    return result


def count_postings_by_company(skill: str | None = None, top_n: int = 10) -> dict:
    """Count postings per company, optionally only those requiring a skill."""
    postings = load_postings()
    if skill is not None:
        skill = _resolve_skill(skill, postings)
        postings = tuple(p for p in postings if p.has_skill(skill))

    counts = Counter(p.company for p in postings)
    # Highest count first; ties broken alphabetically so results are stable.
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    return {
        "skill": skill or "any",
        "total_postings": len(postings),
        "total_companies": len(ranked),
        "companies": [{"company": name, "postings": n} for name, n in ranked[:top_n]],
    }


def get_posting(posting_id: str) -> dict:
    """Return every field of one posting, including its full skill list."""
    posting_id = _clean_text(posting_id, "posting_id").upper()
    if not POSTING_ID_PATTERN.match(posting_id):
        raise ToolError(
            f"'{posting_id}' is not a valid posting ID. IDs look like 'JP-001'; "
            "get them from search_postings."
        )

    for posting in load_postings():
        if posting.id == posting_id:
            return posting.model_dump()

    raise ToolError(f"No posting has ID '{posting_id}'. Use search_postings to find valid IDs.")

