"""Live, read-only Moodle check. Prints only safe facts (counts), never secrets or content.

Run from apps/api:  .venv/bin/python ../../scripts/moodle_check.py
"""

from __future__ import annotations

import asyncio

from campuspilot.moodle.client import MoodleClient
from campuspilot.moodle.tools import (
    MoodleError,
    get_my_deadlines,
    list_my_courses,
    moodle_status,
    resolve_source,
)
from campuspilot.schemas.tools import GetMyDeadlinesInput, ListMyCoursesInput

SETUP_HELP = """Moodle is not configured. To connect it (read-only):
  1. Moodle -> Preferences -> Security keys -> copy the "Moodle mobile web service" key,
     then put MOODLE_TOKEN=... in the untracked .env at the repo root
     (or save it in the app Settings).
  2. If IITB has web services off: Moodle -> Calendar -> Export calendar, copy the URL,
     and put MOODLE_ICAL_URL=... in .env.
Never share your IITB password; this app never asks for it."""


async def main() -> int:
    status, mode = await moodle_status()
    if status == "not_configured" and mode == "none":
        print(SETUP_HELP)
        return 0
    print(f"mode: {mode}  status: {status}")
    if mode == "demo":
        print("(demo fixtures; nothing real is connected)")
    try:
        source = resolve_source()
        if source.mode == "rest":
            print(f"site: {(await MoodleClient(source.secret).site_info()).get('sitename', '?')}")
        courses = await list_my_courses(ListMyCoursesInput())
        deadlines = await get_my_deadlines(GetMyDeadlinesInput(days_ahead=14))
    except MoodleError as err:
        print(f"Moodle error [{err.code}]: {err.message}")
        return 1
    print(f"courses: {len(courses.courses)}" + (f"  ({courses.note})" if courses.note else ""))
    print(f"deadlines in next 14 days: {len(deadlines.deadlines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
