"""Live, read-only ASC check (`make asc-check`). Prints COUNTS ONLY: never names, roll number,
amounts, grades or URLs. Uses the LDAP login saved in the macOS Keychain (Settings -> ASC).
Needs the campus network or the IITB VPN.

Run from apps/api:  .venv/bin/python ../../scripts/asc_check.py
"""

from __future__ import annotations

import asyncio
import sys

from campuspilot import asc
from campuspilot.asc import credentials
from campuspilot.connectors.errors import ConnectorError
from campuspilot.schemas.connectors import (
    AscCurrentCoursesInput,
    AscFeeStatusInput,
    AscMyTimetableInput,
    AscOfferedCoursesInput,
    AscProfileInput,
    AscRegistrationStatusInput,
)


async def check(label: str, call) -> str:
    try:
        return f"{label}: {await call()}"
    except ConnectorError as exc:
        return f"{label}: failed ({exc.code})"


async def timetable() -> int:
    return len((await asc.asc_my_timetable(AscMyTimetableInput())).slots)


async def courses() -> int:
    return len((await asc.asc_my_current_courses(AscCurrentCoursesInput())).courses)


async def registration() -> str:
    out = await asc.asc_registration_status(AscRegistrationStatusInput())
    return f"window {'open' if out.window_open else 'closed'}, {len(out.courses)} courses"


async def fees() -> int:
    return len((await asc.asc_fee_status(AscFeeStatusInput())).items)


async def profile() -> int:
    p = (await asc.asc_profile(AscProfileInput())).profile
    fields = (p.department, p.program, p.status, p.validity, p.academic_standing, p.advisors)
    return sum(1 for f in fields if f)


async def offered() -> int:
    out = await asc.asc_offered_courses(
        AscOfferedCoursesInput(dept="IE", year=2026, semester="autumn")
    )
    return len(out.courses)


async def main() -> int:
    if credentials.load() is None:
        print("ASC is not connected. Save your LDAP login: Settings -> Connectors -> ASC.")
        return 1
    for label, call in (
        ("timetable slots", timetable),
        ("current courses", courses),
        ("registration", registration),
        ("fee rows", fees),
        ("profile fields filled", profile),
        ("offered IE courses, Autumn 2026", offered),
    ):
        print(await check(label, call))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
