"""Load the sample job postings dataset from disk."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "job_postings.json"

Seniority = Literal["intern", "junior", "mid", "senior"]


class SalaryRange(BaseModel):
    min: int
    max: int


class JobPosting(BaseModel):
    id: str
    title: str
    company: str
    location: str
    remote: bool
    seniority: Seniority
    skills: list[str]
    salary_usd: SalaryRange
    posted_date: str

    def has_skill(self, skill: str) -> bool:
        """Case-insensitive skill match, so "python" finds "Python"."""
        return skill.casefold() in (s.casefold() for s in self.skills)


@lru_cache(maxsize=1)
def load_postings(path: Path = DATA_FILE) -> tuple[JobPosting, ...]:
    """Read and validate every posting once, then reuse the result.

    Validating the file with Pydantic means a broken dataset fails loudly at
    startup instead of producing confusing tool results later.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(JobPosting.model_validate(item) for item in raw["postings"])


def known_skills(postings: tuple[JobPosting, ...]) -> list[str]:
    """All distinct skills in the dataset, sorted alphabetically."""
    return sorted({skill for posting in postings for skill in posting.skills}, key=str.casefold)

