"""Tests for tool behaviour, called through a real MCP client in memory."""

import json

import pytest
from mcp import Client

from job_postings_mcp.server import build_server


async def call(tool: str, args: dict) -> tuple[bool, str]:
    """Call a tool the way an AI assistant would. Returns (is_error, text)."""
    async with Client(build_server()) as client:
        result = await client.call_tool(tool, args)
        return result.is_error, result.content[0].text


async def call_ok(tool: str, args: dict) -> dict:
    is_error, text = await call(tool, args)
    assert not is_error, text
    return json.loads(text)


async def test_lists_three_tools_with_descriptions():
    async with Client(build_server()) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == {"search_postings", "count_postings_by_company", "get_posting"}
    for tool in tools:
        assert tool.description, f"{tool.name} has no description"
        for name, schema in tool.input_schema["properties"].items():
            assert schema.get("description"), f"{tool.name}.{name} has no description"


# --- search_postings --------------------------------------------------------


async def test_search_is_case_insensitive():
    result = await call_ok("search_postings", {"skill": "rust"})
    assert result["skill"] == "Rust"
    assert result["total_matches"] > 0


async def test_search_respects_limit_and_explains_truncation():
    result = await call_ok("search_postings", {"skill": "Python", "limit": 2})
    assert result["returned"] == 2
    assert result["total_matches"] > 2
    assert "Showing 2 of" in result["note"]


async def test_search_filters_combine():
    result = await call_ok(
        "search_postings", {"skill": "Python", "location": "kenya", "remote_only": True, "limit": 25}
    )
    for posting in result["postings"]:
        assert "Kenya" in posting["location"]
        assert posting["remote"] is True


async def test_search_with_no_matches_suggests_relaxing_filters():
    result = await call_ok("search_postings", {"skill": "Rust", "location": "Lagos"})
    assert result["total_matches"] == 0
    assert "Try removing" in result["note"]


async def test_search_suggests_correct_spelling():
    is_error, text = await call("search_postings", {"skill": "Pyhton"})
    assert is_error
    assert "Did you mean: Python?" in text


@pytest.mark.parametrize(
    "args, expected",
    [
        ({"skill": ""}, "at least 1 character"),
        ({"skill": "   "}, "must not be empty"),
        ({"skill": "x" * 100}, "at most 60 characters"),
        ({"skill": "Python", "limit": 0}, "greater than or equal to 1"),
        ({"skill": "Python", "limit": 500}, "less than or equal to 25"),
        ({"skill": "Python", "seniority": "principal"}, "'intern', 'junior', 'mid' or 'senior'"),
        ({}, "skill"),
    ],
)
async def test_search_rejects_bad_input(args, expected):
    is_error, text = await call("search_postings", args)
    assert is_error
    assert expected in text


# --- count_postings_by_company ---------------------------------------------


async def test_count_all_postings():
    result = await call_ok("count_postings_by_company", {"top_n": 50})
    assert result["skill"] == "any"
    assert sum(c["postings"] for c in result["companies"]) == result["total_postings"] == 40


async def test_count_is_sorted_most_first():
    result = await call_ok("count_postings_by_company", {"skill": "Python"})
    counts = [c["postings"] for c in result["companies"]]
    assert counts == sorted(counts, reverse=True)


async def test_count_rejects_unknown_skill():
    is_error, text = await call("count_postings_by_company", {"skill": "COBOL"})
    assert is_error
    assert "Known skills:" in text


# --- get_posting ------------------------------------------------------------


async def test_get_posting_accepts_lowercase_id():
    result = await call_ok("get_posting", {"posting_id": "jp-001"})
    assert result["id"] == "JP-001"
    assert result["skills"]


@pytest.mark.parametrize(
    "posting_id, expected",
    [
        ("JP-7", "not a valid posting ID"),
        ("'; DROP TABLE postings;--", "at most 10 characters"),
        ("JP-999", "No posting has ID 'JP-999'"),
    ],
)
async def test_get_posting_rejects_bad_ids(posting_id, expected):
    is_error, text = await call("get_posting", {"posting_id": posting_id})
    assert is_error
    assert expected in text
