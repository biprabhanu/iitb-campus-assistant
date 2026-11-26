"""Demo mode: fake fixtures from data/fixtures/moodle, with dates shifted to "now"."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from campuspilot.config import REPO_ROOT
from campuspilot.schemas.tools import Course, CourseResource, CourseSection, Deadline

FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "moodle"


@lru_cache
def _load(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def demo_courses() -> list[Course]:
    return [Course(**row) for row in _load("courses.json")]


def demo_deadlines(now: datetime | None = None) -> list[Deadline]:
    """Fixtures store `due_in_hours`, so deadlines always fall in the coming days."""
    now = now or datetime.now(UTC)
    result = []
    for row in _load("deadlines.json"):
        due = now + timedelta(hours=row["due_in_hours"])
        result.append(
            Deadline(
                id=row["id"],
                title=row["title"],
                course=row["course"],
                due_at=due,
                activity_url=row.get("activity_url"),
                kind=row["kind"],
            )
        )
    return sorted(result, key=lambda d: d.due_at)


def demo_contents(short_name: str) -> list[CourseSection]:
    rows = _load("contents.json").get(short_name, [])
    return [
        CourseSection(name=s["name"], resources=[CourseResource(**r) for r in s["resources"]])
        for s in rows
    ]
