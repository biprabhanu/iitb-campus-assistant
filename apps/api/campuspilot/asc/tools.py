"""ASC tools, session state, snapshot lifecycle and the 24 h public-data cache (CONTRACT §11.8).

Personal tools read the in-memory snapshot (never on disk). Public tools (running courses,
offering history, course details) read ASC per request and cache department x year x semester
lists on disk for 24 h: public course data only, never personal data.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

from campuspilot.asc import credentials, demo, pages, parsers
from campuspilot.asc.client import MSG_EXPIRED, AscSession, SessionExpired, normalise_username
from campuspilot.asc.snapshot import NOTE_WINDOW_CLOSED, Snapshot, build_snapshot
from campuspilot.config import Settings, get_settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.schemas.connectors import (
    AscCourse,
    AscCourseDetail,
    AscCourseDetailsInput,
    AscCourseDetailsOutput,
    AscCourseHistoryInput,
    AscCourseHistoryOutput,
    AscCoursesOutput,
    AscCurrentCoursesInput,
    AscFeeStatusInput,
    AscFeeStatusOutput,
    AscMyTimetableInput,
    AscOfferedCoursesInput,
    AscOfferedCoursesOutput,
    AscOffering,
    AscProfileInput,
    AscProfileOutput,
    AscRegistrationOutput,
    AscRegistrationStatusInput,
    AscTimetableOutput,
    ConnectorLoginRequest,
    ConnectorOtpRequest,
    ConnectorStatus,
)

IST = ZoneInfo("Asia/Kolkata")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SEMESTERS = ("autumn", "spring")
HISTORY_YEARS = 3


class _State:
    def __init__(self) -> None:
        self.session: AscSession | None = None
        self.snapshot: Snapshot | None = None
        self.lock = asyncio.Lock()  # session creation / re-login
        self.snap_lock = asyncio.Lock()
        self.last_error: str | None = None
        self.dept_map: dict[str, str] | None = None
        self.detail_links: dict[str, str] = {}  # course code -> crsedetail link (has a token)
        self.pending: set[asyncio.Task] = set()


_state = _State()


def reset_state() -> None:
    """Forget the session, snapshot and in-memory maps (tests call this between tests)."""
    global _state
    _state = _State()


def _record(exc: ConnectorError | None) -> None:
    keep = exc is not None and exc.code != "not_connected"
    _state.last_error = exc.message if keep and exc else None


# ---------------------------------------------------------------- session


def _new_session(settings: Settings) -> AscSession:
    if settings.connectors_demo:
        return AscSession(settings, transport=demo.demo_transport())
    return AscSession(settings)


async def _sign_in_new(settings: Settings, username: str, password: str) -> AscSession:
    session = _new_session(settings)
    try:
        await session.sign_in(username, password)
    except BaseException:
        await session.aclose()
        raise
    return session


def _creds(settings: Settings) -> tuple[str, str]:
    if settings.connectors_demo:
        return "demo", "demo"
    creds = credentials.load()
    if creds is None:
        raise ConnectorError("not_connected", "Connect ASC in Settings first.")
    return creds


async def _get_session() -> AscSession:
    settings = get_settings()
    async with _state.lock:
        if _state.session is not None and _state.session.signed_in:
            return _state.session
        user, password = _creds(settings)
        _state.session = await _sign_in_new(settings, user, password)
        return _state.session


async def _relogin() -> AscSession:
    """The session ran out: log in once more with the saved login (new session, new tokens)."""
    settings = get_settings()
    async with _state.lock:
        old, _state.session = _state.session, None
        if old is not None:
            await old.aclose()
        user, password = _creds(settings)
        _state.session = await _sign_in_new(settings, user, password)
        return _state.session


async def _run(fn):
    """Run `fn(session)`; on a signed-out session log in again once, then `session_expired`."""
    try:
        session = await _get_session()
        try:
            return await fn(session)
        except SessionExpired:
            session = await _relogin()
            try:
                return await fn(session)
            except SessionExpired:
                _state.session = None
                raise ConnectorError("session_expired", MSG_EXPIRED) from None
    except ConnectorError as exc:
        _record(exc)
        raise


# ---------------------------------------------------------------- snapshot


async def ensure_snapshot(force: bool = False) -> Snapshot:
    settings = get_settings()
    async with _state.snap_lock:
        snap = _state.snapshot
        fresh = snap is not None and (
            datetime.now(UTC) - snap.fetched_at < timedelta(seconds=settings.asc_snapshot_ttl_s)
        )
        if snap is not None and fresh and not force:
            return snap
        _state.snapshot = await _run(build_snapshot)
        _record(None)
        return _state.snapshot


async def _section(name: str) -> Snapshot:
    snap = await ensure_snapshot()
    if name in snap.errors:
        code, message = snap.errors[name]
        raise ConnectorError(code, message)  # type: ignore[arg-type]
    return snap


# ---------------------------------------------------------------- personal tools


def _demo() -> bool:
    return get_settings().connectors_demo


async def asc_profile(args: AscProfileInput) -> AscProfileOutput:
    snap = await _section("profile")
    assert snap.profile is not None
    return AscProfileOutput(profile=snap.profile, demo=_demo(), fetched_at=snap.fetched_at)


def _day_filter(day: str | None) -> tuple[set[str] | None, list[date]]:
    if day is None:
        return None, []
    today = datetime.now(IST).date()
    if day in ("today", "tomorrow"):
        d = today + timedelta(days=1 if day == "tomorrow" else 0)
        return {DAYS[d.weekday()]}, [d]
    return {day}, []


async def asc_my_timetable(args: AscMyTimetableInput) -> AscTimetableOutput:
    snap = await _section("timetable")
    wanted, dates = _day_filter(args.day)
    slots = [s for s in snap.timetable or [] if wanted is None or s.day in wanted]
    slots.sort(key=lambda s: (DAYS.index(s.day), s.start, s.end))
    note = "" if slots else "No classes found in your ASC timetable for that day."
    return AscTimetableOutput(
        slots=slots, for_dates=dates, note=note, demo=_demo(), fetched_at=snap.fetched_at
    )


async def asc_my_current_courses(args: AscCurrentCoursesInput) -> AscCoursesOutput:
    snap = await _section("courses")
    courses = snap.courses or []
    note = "" if courses else "ASC shows no current-semester courses in your record yet."
    return AscCoursesOutput(
        courses=courses, semester=snap.semester, note=note, demo=_demo(), fetched_at=snap.fetched_at
    )


async def asc_registration_status(args: AscRegistrationStatusInput) -> AscRegistrationOutput:
    snap = await _section("registration")
    open_ = bool(snap.window_open)
    return AscRegistrationOutput(
        window_open=open_,
        courses=snap.registration_courses or [],
        semester=snap.semester,
        note="" if open_ else NOTE_WINDOW_CLOSED,
        demo=_demo(),
        fetched_at=snap.fetched_at,
    )


async def asc_fee_status(args: AscFeeStatusInput) -> AscFeeStatusOutput:
    snap = await _section("fees")
    items = snap.fees or []
    note = (
        ""
        if items
        else (
            "ASC's Fees Status/Scholarship page only offers a month picker for scholarship "
            "payments, so there is no fee status to show. Check fee dues on the ASC site."
        )
    )
    return AscFeeStatusOutput(items=items, note=note, demo=_demo(), fetched_at=snap.fetched_at)


# ---------------------------------------------------------------- public data + disk cache


def _cache_dir(settings: Settings) -> Path:
    return settings.asc_public_cache_dir.expanduser() / "asc"


def _cache_file(settings: Settings, dept: str, year: int, semester: str) -> Path:
    return _cache_dir(settings) / f"{dept.upper()}_{year}_{semester}.json"


def _cache_read(settings: Settings, dept: str, year: int, semester: str) -> list[AscCourse] | None:
    path = _cache_file(settings, dept, year, semester)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(data["saved_at"]) > settings.asc_public_cache_ttl_s:
            return None
        return [AscCourse.model_validate(c) for c in data["courses"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cache_write(
    settings: Settings, dept: str, year: int, semester: str, courses: list[AscCourse]
) -> None:
    if settings.connectors_demo:
        return
    path = _cache_file(settings, dept, year, semester)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"saved_at": time.time(), "courses": [c.model_dump() for c in courses]}
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # a cache that cannot be written is only slower


def semester_label(year: int, semester: str) -> str:
    """'autumn' of the 2026-27 year is Autumn 2026; 'spring' is Spring 2027."""
    return f"{semester.capitalize()} {year + 1 if semester == 'spring' else year}"


async def _deptcd(session: AscSession, dept: str) -> str:
    dept = dept.upper()
    if _state.dept_map is None:
        try:
            page = await session.get(session.link("running") or pages.ALL_DEPT_PATH)
            _state.dept_map = parsers.parse_all_dept(page.text)
        except SessionExpired:
            raise
        except ConnectorError as exc:
            if exc.code == "unreachable":
                raise
            _state.dept_map = {}
    return _state.dept_map.get(dept, dept)


async def _fetch_running(
    session: AscSession, dept: str, year: int, semester: str
) -> list[parsers.RunningRow]:
    deptcd = await _deptcd(session, dept)
    query = urlencode(
        {"deptcd": deptcd, "year": year, "semester": pages.SEMESTER_NUMBER[semester]}, safe=","
    )
    page = await session.get(f"{pages.RUNNING_COURSES_PATH}?{query}")
    rows = parsers.parse_running_courses(page.text, semester_label(year, semester))
    for row in rows:
        if row.detail_href:
            _state.detail_links[row.course.code] = urljoin(
                f"{session.base}{pages.RUNNING_COURSES_PATH}", row.detail_href
            )
    return rows


async def _running(
    dept: str, year: int, semester: str, *, live: bool = False
) -> tuple[list[AscCourse], datetime]:
    settings = get_settings()
    if not live and not settings.connectors_demo:
        cached = _cache_read(settings, dept, year, semester)
        if cached is not None:
            return cached, datetime.now(UTC)
    rows = await _run(lambda s: _fetch_running(s, dept, year, semester))
    courses = [r.course for r in rows]
    _cache_write(settings, dept, year, semester, courses)
    return courses, datetime.now(UTC)


async def asc_offered_courses(args: AscOfferedCoursesInput) -> AscOfferedCoursesOutput:
    courses, at = await _running(args.dept, args.year, args.semester)
    note = (
        ""
        if courses
        else "ASC has no running courses listed for that term (maybe not published yet)."
    )
    return AscOfferedCoursesOutput(
        dept=args.dept.upper(),
        year=args.year,
        semester=args.semester,
        courses=courses,
        note=note,
        demo=_demo(),
        fetched_at=at,
    )


def current_academic_year(today: date | None = None) -> int:
    """Start year of the current academic year (it begins in July)."""
    today = today or datetime.now(IST).date()
    return today.year if today.month >= 7 else today.year - 1


def _dept_of(code: str) -> str:
    return code.split()[0].upper()


async def asc_course_offering_history(args: AscCourseHistoryInput) -> AscCourseHistoryOutput:
    code = parsers.normalise_code(args.course_code)
    latest = current_academic_year()
    offerings: list[AscOffering] = []
    title = ""
    unpublished: list[str] = []
    at = datetime.now(UTC)
    for year in range(latest, latest - HISTORY_YEARS, -1):
        for semester in SEMESTERS:
            courses, at = await _running(_dept_of(code), year, semester)
            match = next((c for c in courses if c.code == code), None)
            if match and not title:
                title = match.title
            if not courses and year == latest:
                unpublished.append(semester_label(year, semester))
            offerings.append(AscOffering(year=year, semester=semester, offered=match is not None))
    note = ""
    if unpublished:
        note = "Not published yet on ASC: " + ", ".join(unpublished) + "."
    return AscCourseHistoryOutput(
        course_code=code,
        title=title,
        offerings=offerings,
        note=note,
        demo=_demo(),
        fetched_at=at,
    )


async def _optional_page(session: AscSession, key: str) -> str | None:
    url = session.link(key)
    if url is None:
        return None
    try:
        return (await session.get(url)).text
    except SessionExpired:
        raise
    except ConnectorError as exc:
        if exc.code == "unreachable":
            raise
        return None


async def _details(session: AscSession, code: str) -> AscCourseDetail | None:
    detail: AscCourseDetail | None = None
    latest = current_academic_year()
    # Find a recent term that lists the course, to get its crsedetail link.
    if code not in _state.detail_links:
        for year in range(latest, latest - HISTORY_YEARS, -1):
            for semester in ("autumn", "spring"):
                rows = await _fetch_running(session, _dept_of(code), year, semester)
                if any(r.course.code == code for r in rows):
                    break
            if code in _state.detail_links:
                break
    href = _state.detail_links.get(code)
    if href:
        try:
            page = await session.get(href)
            detail = parsers.parse_course_detail(page.text, code)
        except SessionExpired:
            raise
        except ConnectorError as exc:
            if exc.code == "unreachable":
                raise
    prereq_html = await _optional_page(session, "prereq")
    prereqs = parsers.parse_prerequisites(prereq_html, code) if prereq_html else []
    syllabus_html = await _optional_page(session, "syllabus")
    syllabus = parsers.parse_syllabus(syllabus_html, code) if syllabus_html else ""
    if detail is None and not prereqs and not syllabus:
        return None
    detail = detail or AscCourseDetail(code=code)
    detail.prerequisites = list(dict.fromkeys([*detail.prerequisites, *prereqs]))
    if syllabus and not detail.syllabus:
        detail.syllabus = syllabus
    return detail


async def asc_course_details(args: AscCourseDetailsInput) -> AscCourseDetailsOutput:
    code = parsers.normalise_code(args.course_code)
    detail = await _run(lambda s: _details(s, code))
    note = "" if detail else f"I could not find {code} on ASC's course pages."
    return AscCourseDetailsOutput(
        detail=detail, note=note, demo=_demo(), fetched_at=datetime.now(UTC)
    )


# ---------------------------------------------------------------- Settings


def _refreshed() -> datetime | None:
    return _state.snapshot.fetched_at if _state.snapshot else None


async def asc_status() -> ConnectorStatus:
    settings = get_settings()
    if settings.connectors_demo:
        return ConnectorStatus(
            name="asc", enabled=True, state="connected", account="demo", demo=True,
            message=demo.NOTE_DEMO, refreshed_at=_refreshed(),
        )  # fmt: skip
    account = credentials.username()
    if credentials.load() is None:
        return ConnectorStatus(name="asc", enabled=True, state="not_connected")
    if _state.last_error:
        return ConnectorStatus(
            name="asc", enabled=True, state="error", account=account,
            message=_state.last_error, refreshed_at=_refreshed(),
        )  # fmt: skip
    return ConnectorStatus(
        name="asc", enabled=True, state="connected", account=account, refreshed_at=_refreshed()
    )


async def asc_login(req: ConnectorLoginRequest) -> ConnectorStatus:
    """Real login first; the Keychain gets the login only after it worked."""
    settings = get_settings()
    if settings.connectors_demo:
        return await asc_status()
    username = normalise_username(req.username)
    try:
        session = await _sign_in_new(settings, username, req.password)
    except ConnectorError as exc:
        _record(None if exc.code == "auth_failed" else exc)  # a typo is not a broken connection
        raise
    async with _state.lock:
        old, _state.session = _state.session, session
        _state.snapshot = None
        _state.dept_map = None
    if old is not None:
        await old.aclose()
    credentials.save(username, req.password)
    _record(None)
    with contextlib.suppress(ConnectorError):  # logged in fine; asc_status shows the problem
        await ensure_snapshot(force=True)
    return await asc_status()


async def asc_submit_otp(req: ConnectorOtpRequest) -> ConnectorStatus:
    raise ConnectorError("otp_invalid", "ASC does not use a one-time code.")


async def asc_refresh() -> ConnectorStatus:
    """Re-read every personal ASC page into the snapshot now."""
    if not get_settings().connectors_demo and credentials.load() is None:
        raise ConnectorError("not_connected", "Connect ASC in Settings first.")
    await ensure_snapshot(force=True)
    return await asc_status()


def asc_logout() -> ConnectorStatus:
    """Forget the saved login and the session; tell ASC to end it (best effort)."""
    credentials.clear()
    session, _state.session = _state.session, None
    _state.snapshot = None
    _state.dept_map = None
    _state.detail_links = {}
    _state.last_error = None
    if session is not None:
        try:
            task = asyncio.get_running_loop().create_task(session.sign_out())
        except RuntimeError:
            task = None
        if task is not None:
            _state.pending.add(task)
            task.add_done_callback(_state.pending.discard)
    return ConnectorStatus(name="asc", enabled=True, state="not_connected")
