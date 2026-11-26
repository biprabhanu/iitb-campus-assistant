"""The ASC tools and Settings actions: read pages (GET only), parse, answer.

Grades and pages are sensitive: nothing here logs page content, and error messages are fixed
friendly sentences.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from campuspilot.asc import credentials, demo, pages, parsers
from campuspilot.asc.client import AscSession
from campuspilot.asc.login import (
    STATE,
    Pending,
    authenticate,
    forget,
    gate,
    is_asc_host,
    login,
    looks_like_login,
    submit_otp,
)
from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.schemas.connectors import (
    AscCoursesOutput,
    AscGradesOutput,
    AscTimetableOutput,
    ConnectorLoginRequest,
    ConnectorOtpRequest,
    ConnectorStatus,
    GetMyGradesInput,
    GetMyRegisteredCoursesInput,
    GetMyTimetableInput,
)

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_background: set[asyncio.Task[None]] = set()  # keeps close() tasks alive until they finish


# ---------- reading pages ----------


def _today() -> date:
    return datetime.now(IST).date()


async def _silent_login(creds: tuple[str, str]) -> None:
    """Log in again with the Keychain credentials, without bothering the student."""
    try:
        result = await authenticate(*creds)
    except ConnectorError as exc:
        if exc.code == "auth_failed":
            raise ConnectorError(
                "session_expired", "Your ASC login no longer works. Connect ASC again in Settings."
            ) from None
        raise
    if isinstance(result, Pending):
        await result.session.aclose()
        raise ConnectorError(
            "session_expired", "ASC needs a one-time code. Connect ASC again in Settings."
        )
    STATE.session = result


async def _read(path: str, creds: tuple[str, str]) -> str:
    base = get_settings().asc_base_url.rstrip("/")
    for attempt in (1, 2):
        if STATE.session is None:
            await _silent_login(creds)
        assert STATE.session is not None
        response = await STATE.session.request("GET", base + path)  # GET only: enforced inside
        bounced = (
            response.status_code in (401, 403)
            or not is_asc_host(str(response.url))
            or looks_like_login(response.text)
        )
        if not bounced:
            if response.status_code >= 400:
                raise ConnectorError("unreachable", "ASC isn't answering properly right now.")
            return response.text
        # The session ran out. Drop it and (once) log in again.
        await STATE.session.aclose()
        STATE.session = None
        if attempt == 2:
            break
    raise ConnectorError(
        "session_expired", "Your ASC session ended. Connect ASC again in Settings."
    )


async def page_html(key: str, path: str) -> str:
    """HTML of one ASC page: demo fixture, or a (briefly cached) live read."""
    settings = get_settings()
    if settings.connectors_demo:
        return demo.page(key)
    async with gate():
        creds = credentials.load()
        if creds is None:
            raise ConnectorError("not_connected", "Connect ASC in Settings first.")
        hit = STATE.cache.get(path)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        try:
            html = await _read(path, creds)
        except ConnectorError as exc:
            STATE.last_error = exc.message
            raise
        STATE.last_error = None
        if settings.asc_cache_ttl_s > 0:
            STATE.cache[path] = (time.monotonic() + settings.asc_cache_ttl_s, html)
        return html


# ---------- tools ----------


def _dates_for(when: str, on_date: date | None) -> list[date]:
    if on_date is not None:
        return [on_date]
    today = _today()
    if when == "tomorrow":
        return [today + timedelta(days=1)]
    if when == "this_week":
        monday = today - timedelta(days=today.weekday())
        return [monday + timedelta(days=i) for i in range(7)]
    return [today]


async def get_my_timetable(args: GetMyTimetableInput) -> AscTimetableOutput:
    html = await page_html("timetable", pages.PAGE_TIMETABLE)
    weekly, note = parsers.parse_timetable(html)
    dates = _dates_for(args.when, args.on_date)
    days = {_WEEKDAYS[d.weekday()] for d in dates}
    slots = [s for s in weekly if s.day in days]
    slots.sort(key=lambda s: (_WEEKDAYS.index(s.day), s.start))
    if not slots and not note:
        note = "No classes found on ASC for that day."
    return AscTimetableOutput(
        slots=slots,
        for_dates=dates,
        demo=get_settings().connectors_demo,
        note=note,
    )


async def get_my_registered_courses(args: GetMyRegisteredCoursesInput) -> AscCoursesOutput:
    html = await page_html("courses", pages.PAGE_COURSES)
    courses, semester, registration_note = parsers.parse_courses(html)
    note = ""
    if args.semester:
        wanted = args.semester.lower()
        courses = [c for c in courses if wanted in c.semester.lower()]
        semester = args.semester if courses else semester
        if not courses:
            note = "ASC's course page shows no courses for that semester."
    return AscCoursesOutput(
        courses=courses,
        semester=semester,
        registration_note=registration_note,
        demo=get_settings().connectors_demo,
        note=note,
    )


async def get_my_grades(args: GetMyGradesInput) -> AscGradesOutput:
    html = await page_html("grades", pages.PAGE_GRADES)
    grades, spi, cpi = parsers.parse_grades(html)
    note = ""
    if args.semester:
        wanted = args.semester.lower()
        grades = [g for g in grades if wanted in g.semester.lower()]
        if not grades:
            note = "ASC's grades page shows no grades for that semester."
    elif spi is None and len(grades) > 0:
        note = "ASC shows more than one SPI (or none), so none is given here."
    return AscGradesOutput(
        grades=grades, spi=spi, cpi=cpi, demo=get_settings().connectors_demo, note=note
    )


# ---------- Settings: status, login, OTP, logout ----------


def _status() -> ConnectorStatus:
    if get_settings().connectors_demo:
        return ConnectorStatus(
            name="asc",
            enabled=True,
            state="connected",
            account="demo",
            demo=True,
            message="Demo data",
        )
    if STATE.pending:
        challenge_id = next(reversed(STATE.pending))
        return ConnectorStatus(
            name="asc",
            enabled=True,
            state="needs_otp",
            challenge_id=challenge_id,
            message="Enter the one-time code ASC asked for.",
        )
    account = credentials.username()
    if account is None:
        return ConnectorStatus(name="asc", enabled=True, state="not_connected")
    if STATE.last_error:
        return ConnectorStatus(
            name="asc", enabled=True, state="error", account=account, message=STATE.last_error
        )
    return ConnectorStatus(name="asc", enabled=True, state="connected", account=account)


async def asc_status() -> ConnectorStatus:
    return _status()


async def _adopt(session: AscSession, username: str, password: str) -> None:
    """Make a freshly logged-in session the current one and remember the credentials."""
    old, STATE.session = STATE.session, session
    STATE.cache.clear()
    STATE.last_error = None
    credentials.save(username, password)  # only after a successful login
    if old is not None:
        await old.aclose()


async def asc_login(req: ConnectorLoginRequest) -> ConnectorStatus:
    if get_settings().connectors_demo:
        return _status()
    async with gate():
        session, challenge_id = await login(req.username, req.password)
        if session is None:
            return ConnectorStatus(
                name="asc",
                enabled=True,
                state="needs_otp",
                challenge_id=challenge_id,
                message="Enter the one-time code ASC asked for.",
            )
        await _adopt(session, req.username, req.password)
        return _status()


async def asc_submit_otp(req: ConnectorOtpRequest) -> ConnectorStatus:
    if get_settings().connectors_demo:
        return _status()
    async with gate():
        session, username, password = await submit_otp(req.challenge_id, req.code)
        await _adopt(session, username, password)
        return _status()


def asc_logout() -> ConnectorStatus:
    """Forget the session and delete the Keychain entries."""
    credentials.clear()
    sessions = forget()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no event loop: nothing can be awaited, the sessions just get collected
        return _status()
    for session in sessions:
        task = loop.create_task(session.aclose())
        _background.add(task)
        task.add_done_callback(_background.discard)
    return _status()
