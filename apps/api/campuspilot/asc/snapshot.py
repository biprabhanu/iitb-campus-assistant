"""The personal ASC snapshot: every personal page read once, held in memory only (CONTRACT §11.8).

Never written to disk, never logged. One page failing keeps the others: that section stores a
(code, friendly message) pair and its tool raises it. A signed-out session is NOT a section
error: `SessionExpired` propagates so the caller can log in again once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from campuspilot.asc import pages, parsers
from campuspilot.asc.client import AscSession, Page, SessionExpired
from campuspilot.connectors.errors import ConnectorError
from campuspilot.schemas.connectors import (
    AscCourse,
    AscFeeItem,
    AscProfile,
    AscTimetableSlot,
)

NOTE_WINDOW_CLOSED = (
    "The registration window is not open; here are your registered courses for this semester."
)
MSG_NOT_LISTED = "ASC did not list that page for your account."
MSG_LAYOUT = "ASC's page looked different than expected, so nothing was guessed."


@dataclass
class Snapshot:
    fetched_at: datetime
    profile: AscProfile | None = None
    timetable: list[AscTimetableSlot] | None = None
    courses: list[AscCourse] | None = None
    semester: str = ""
    window_open: bool | None = None
    registration_courses: list[AscCourse] | None = None
    fees: list[AscFeeItem] | None = None
    errors: dict[str, tuple[str, str]] = field(default_factory=dict)  # section -> (code, message)

    def __repr__(self) -> str:  # personal data: say nothing about the contents
        return f"Snapshot(errors={sorted(self.errors)})"


def _fail(snap: Snapshot, sections: tuple[str, ...], exc: ConnectorError) -> None:
    for name in sections:
        snap.errors[name] = (exc.code, exc.message)


async def _page(session: AscSession, key: str) -> Page:
    url = session.link(key)
    if url is None:
        raise ConnectorError("parse_failed", MSG_NOT_LISTED)
    return await session.get(url)


def _record_courses(snap: Snapshot, record: parsers.AcademicRecord) -> None:
    current = record.current
    snap.courses = list(current.courses) if current else []
    snap.semester = current.name if current else ""


async def build_snapshot(session: AscSession) -> Snapshot:
    snap = Snapshot(fetched_at=datetime.now(UTC))
    record: parsers.AcademicRecord | None = None

    # Academic record: profile + current courses (grades are dropped by the parser).
    try:
        page = await _page(session, "record")
        record = parsers.parse_academic_record(page.text)
        if not record.semesters and record.profile == AscProfile():
            raise ConnectorError("parse_failed", MSG_LAYOUT)
        snap.profile = record.profile
        _record_courses(snap, record)
    except SessionExpired:
        raise
    except ConnectorError as exc:
        if exc.code == "unreachable":
            raise
        _fail(snap, ("profile", "courses"), exc)

    # Timetable.
    try:
        page = await _page(session, "timetable")
        snap.timetable = parsers.parse_timetable(page.text)
    except SessionExpired:
        raise
    except ConnectorError as exc:
        if exc.code == "unreachable":
            raise
        _fail(snap, ("timetable",), exc)

    # Registration status. Outside the window ASC redirects to AcademicRecord.jsp.
    try:
        page = await _page(session, "registration")
        if page.redirected and pages.basename(page.path) == "AcademicRecord.jsp":
            snap.window_open = False
            if record is None:
                record = parsers.parse_academic_record(page.text)
            current = record.current
            snap.registration_courses = list(current.courses) if current else []
            if not snap.semester and current:
                snap.semester = current.name
        else:
            snap.window_open = True
            snap.registration_courses = parsers.parse_registration_status(page.text)
    except SessionExpired:
        raise
    except ConnectorError as exc:
        if exc.code == "unreachable":
            raise
        _fail(snap, ("registration",), exc)

    # Fee status (status / amount-due rows only).
    try:
        page = await _page(session, "fees")
        snap.fees = parsers.parse_fee_status(page.text)
    except SessionExpired:
        raise
    except ConnectorError as exc:
        if exc.code == "unreachable":
            raise
        _fail(snap, ("fees",), exc)
    return snap
