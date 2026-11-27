"""The three read-only Moodle tools plus status and credential helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from campuspilot.config import get_settings
from campuspilot.moodle import credentials, demo
from campuspilot.moodle.client import MoodleClient
from campuspilot.moodle.errors import MoodleError
from campuspilot.moodle.ical import fetch_ics, parse_ics, validate_ical_url
from campuspilot.schemas.chat import MoodleTokenRequest, MoodleTokenResponse
from campuspilot.schemas.tools import (
    Course,
    CourseResource,
    CourseSection,
    Deadline,
    GetCourseContentsInput,
    GetCourseContentsOutput,
    GetMyDeadlinesInput,
    GetMyDeadlinesOutput,
    ListMyCoursesInput,
    ListMyCoursesOutput,
)

__all__ = [
    "MoodleError",
    "check_credentials",
    "delete_credentials",
    "get_course_contents",
    "get_my_deadlines",
    "list_my_courses",
    "moodle_status",
    "save_credentials",
]

ICAL_NOTE = "Courses and course contents are not available in calendar-export mode."


# ---------- which data source to use ----------


@dataclass(frozen=True)
class Source:
    mode: Literal["rest", "ical", "demo"]
    secret: str = ""  # the token or iCal URL; never logged

    def __repr__(self) -> str:
        return f"Source(mode={self.mode!r})"


def resolve_source() -> Source:
    """Local: Keychain iCal, env iCal, Keychain token, env token, demo, else not_configured.

    The calendar link comes first: IITB Moodle has no "mobile web service" key for students
    (owner, 27 Nov 2026), so iCal is the normal IITB route and a token is a fallback for other
    Moodle sites.

    Hosted: this request's credentials only (never Keychain or env), else demo, else not_configured.
    """
    settings = get_settings()
    if settings.hosted:
        creds = credentials.get_request_credentials()
        if creds and creds.token:
            return Source("rest", creds.token)
        if creds and creds.ical_url:
            return Source("ical", creds.ical_url)
        if settings.moodle_demo_when_unconfigured:
            return Source("demo")
        raise MoodleError(
            "not_configured",
            "Moodle is not connected. Paste your Moodle calendar link in Settings "
            "(Moodle → Calendar → Export calendar → All events, Recent and next 60 days → "
            "Get calendar URL).",
        )
    ical = credentials.get_keyring_ical_url() or settings.moodle_ical_url.get_secret_value()
    if ical:
        return Source("ical", ical)
    token = credentials.get_keyring_token() or settings.moodle_token.get_secret_value()
    if token:
        return Source("rest", token)
    if settings.moodle_demo_when_unconfigured:
        return Source("demo")
    raise MoodleError(
        "not_configured",
        "Moodle is not connected. Paste your Moodle calendar link in Settings "
        "(Moodle → Calendar → Export calendar → All events, Recent and next 60 days → "
        "Get calendar URL).",
    )


# ---------- small helpers ----------


def _course_url(course_id: int) -> str:
    return f"{get_settings().moodle_base_url.rstrip('/')}/course/view.php?id={course_id}"


def _to_course(row: dict[str, Any]) -> Course:
    return Course(
        id=row["id"],
        short_name=row.get("shortname", ""),
        full_name=row.get("fullname", ""),
        url=_course_url(row["id"]),
    )


def _from_unix(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


async def _rest_courses(client: MoodleClient) -> list[Course]:
    user_id = (await client.site_info())["userid"]
    return [_to_course(row) for row in await client.courses(user_id)]


def _find_course(courses: list[Course], code: str) -> Course | None:
    wanted = code.strip().casefold()
    return next((c for c in courses if c.short_name.casefold() == wanted), None)


def _assignment_deadlines(data: dict[str, Any]) -> list[Deadline]:
    base = get_settings().moodle_base_url.rstrip("/")
    result = []
    for course in data.get("courses", []):
        for item in course.get("assignments", []):
            if not item.get("duedate"):
                continue  # no due date set
            result.append(
                Deadline(
                    id=f"assign-{item['id']}",
                    title=item.get("name", "Assignment"),
                    course=course.get("shortname", ""),
                    due_at=_from_unix(item["duedate"]),
                    activity_url=f"{base}/mod/assign/view.php?id={item['cmid']}"
                    if "cmid" in item
                    else None,
                    kind="assignment",
                )
            )
    return result


def _event_deadlines(data: dict[str, Any]) -> list[Deadline]:
    result = []
    for event in data.get("events", []):
        if not event.get("timesort"):
            continue
        result.append(
            Deadline(
                id=f"event-{event['id']}",
                title=event.get("name", "Event"),
                course=(event.get("course") or {}).get("shortname", ""),
                due_at=_from_unix(event["timesort"]),
                activity_url=event.get("url"),
                kind="event",
            )
        )
    return result


def _merge_and_filter(
    items: list[Deadline], now: datetime, days: int, course_code: str | None
) -> list[Deadline]:
    """Keep items in [now, now+days], drop duplicates (first one wins), filter, sort."""
    end = now + timedelta(days=days)
    seen: set[Any] = set()
    kept = []
    for item in items:
        if not (now <= item.due_at <= end):
            continue
        if course_code and item.course.casefold() != course_code.strip().casefold():
            continue
        key = item.activity_url or (item.course, item.title.casefold(), item.due_at)
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return sorted(kept, key=lambda d: d.due_at)


# ---------- the tools ----------


async def list_my_courses(args: ListMyCoursesInput) -> ListMyCoursesOutput:
    source = resolve_source()
    if source.mode == "demo":
        return ListMyCoursesOutput(courses=demo.demo_courses(), mode="demo", demo=True)
    if source.mode == "ical":
        return ListMyCoursesOutput(mode="ical", note=ICAL_NOTE)
    courses = await _rest_courses(MoodleClient(source.secret))
    return ListMyCoursesOutput(courses=courses, mode="rest")


async def get_my_deadlines(args: GetMyDeadlinesInput) -> GetMyDeadlinesOutput:
    source = resolve_source()
    now = datetime.now(UTC)
    if source.mode == "demo":
        items = demo.demo_deadlines(now)
    elif source.mode == "ical":
        items = parse_ics(await fetch_ics(source.secret))
    else:
        items = await _rest_deadlines(MoodleClient(source.secret), now, args.days_ahead)
    deadlines = _merge_and_filter(items, now, args.days_ahead, args.course_code)
    return GetMyDeadlinesOutput(
        deadlines=deadlines,
        mode=source.mode,
        demo=source.mode == "demo",
        note="Deadlines come from a calendar export, so some may be missing."
        if source.mode == "ical"
        else "",
    )


async def _rest_deadlines(client: MoodleClient, now: datetime, days: int) -> list[Deadline]:
    # Round the start down to 5 minutes so repeated calls can hit the cache.
    time_from = int(now.timestamp()) // 300 * 300
    time_to = time_from + days * 86400
    assignments = _assignment_deadlines(await client.assignments())
    events = _event_deadlines(await client.action_events(time_from, time_to))
    return assignments + events  # assignments first: they win when de-duplicating


async def get_course_contents(args: GetCourseContentsInput) -> GetCourseContentsOutput:
    source = resolve_source()
    if source.mode == "ical":
        return GetCourseContentsOutput(mode="ical", note=ICAL_NOTE)
    if source.mode == "demo":
        course = _find_course(demo.demo_courses(), args.course_code)
        sections = demo.demo_contents(course.short_name) if course else []
        return _contents_output(course, sections, "demo", args.course_code)
    client = MoodleClient(source.secret)
    course = _find_course(await _rest_courses(client), args.course_code)
    sections = _to_sections(await client.course_contents(course.id)) if course else []
    return _contents_output(course, sections, "rest", args.course_code)


def _to_sections(rows: list[dict[str, Any]]) -> list[CourseSection]:
    return [
        CourseSection(
            name=row.get("name", ""),
            resources=[
                CourseResource(name=m.get("name", ""), type=m.get("modname", ""), url=m.get("url"))
                for m in row.get("modules", [])
            ],
        )
        for row in rows
    ]


def _contents_output(
    course: Course | None, sections: list[CourseSection], mode: Literal["rest", "demo"], code: str
) -> GetCourseContentsOutput:
    note = "" if course else f"No enrolled course with short name '{code}' was found."
    return GetCourseContentsOutput(
        course=course, sections=sections, mode=mode, demo=mode == "demo", note=note
    )


# ---------- status and credentials ----------


async def moodle_status() -> tuple[
    Literal["connected", "not_configured", "error"], Literal["rest", "ical", "demo", "none"]
]:
    try:
        source = resolve_source()
    except MoodleError:
        return "not_configured", "none"
    if source.mode == "demo":
        return "not_configured", "demo"  # demo data only, nothing real is connected
    try:
        if source.mode == "rest":
            await MoodleClient(source.secret).site_info()
        else:
            parse_ics(await fetch_ics(source.secret))
    except MoodleError:
        return "error", source.mode
    return "connected", source.mode


async def save_credentials(req: MoodleTokenRequest) -> MoodleTokenResponse:
    """Verify first; store in the Keychain only if it works. Never echoes the secret."""
    if (req.token is None) == (req.ical_url is None):
        return MoodleTokenResponse(
            ok=False, mode="none", message="Paste your Moodle calendar link."
        )
    try:
        if req.token is not None:
            return await _verify_and_store_token(req.token)
        return await _verify_and_store_ical(req.ical_url or "")
    except MoodleError as err:
        return MoodleTokenResponse(ok=False, mode="none", message=err.message)


async def _verify_and_store_token(token: str) -> MoodleTokenResponse:
    info = await MoodleClient(token).site_info()
    credentials.store_token(token)
    return MoodleTokenResponse(
        ok=True,
        mode="rest",
        site_name=info.get("sitename"),
        user_fullname=info.get("fullname"),
        message="Moodle token verified and saved in your Keychain.",
    )


async def _verify_and_store_ical(url: str) -> MoodleTokenResponse:
    validate_ical_url(url)
    events = parse_ics(await fetch_ics(url))
    credentials.store_ical_url(url)
    return MoodleTokenResponse(
        ok=True,
        mode="ical",
        message=f"Calendar link verified ({len(events)} events) and saved in your Keychain.",
    )


def delete_credentials() -> MoodleTokenResponse:
    credentials.delete_all()
    return MoodleTokenResponse(
        ok=True, mode="none", message="Moodle credentials removed from your Keychain."
    )


_HOSTED_UNREACHABLE = "Moodle isn't reachable from the hosted version. Use the local app."


async def check_credentials() -> MoodleTokenResponse:
    """Verify this request's credentials against Moodle. Stores nothing."""
    creds = credentials.get_request_credentials()
    if creds is None or not (creds.token or creds.ical_url):
        raise MoodleError("not_configured", "No Moodle credentials were sent with this request.")
    try:
        if creds.token:
            info = await MoodleClient(creds.token).site_info()
            return MoodleTokenResponse(
                ok=True,
                mode="rest",
                site_name=info.get("sitename"),
                user_fullname=info.get("fullname"),
                message="Moodle token works.",
            )
        events = parse_ics(await fetch_ics(creds.ical_url or ""))
        return MoodleTokenResponse(
            ok=True, mode="ical", message=f"Calendar link works ({len(events)} events)."
        )
    except MoodleError as err:
        if get_settings().hosted and err.code in ("unavailable", "timeout"):
            raise MoodleError("unavailable", _HOSTED_UNREACHABLE) from None
        raise
