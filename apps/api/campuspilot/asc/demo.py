"""Demo mode (CONNECTORS_DEMO=true): synthetic ASC pages from data/fixtures/asc.

The demo goes through the same parsers as the real thing, so it also shows they work.
"""

from __future__ import annotations

from functools import lru_cache

from campuspilot.config import REPO_ROOT

FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "asc"
_FILES = {"courses": "courses.html", "timetable": "timetable.html", "grades": "grades.html"}


@lru_cache
def page(name: str) -> str:
    return (FIXTURE_DIR / _FILES[name]).read_text(encoding="utf-8")
