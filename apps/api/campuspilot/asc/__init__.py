"""ASC Internal connector (read-only; LDAP login form; campus network or IITB VPN). CONTRACT §11.8.

Phase 0 stubs: Worker A replaces this package (pages, client, login, parsers, snapshot, tools,
credentials, demo) following ASC_CONNECTOR_PROMPT.md. The signatures below are the contract.
"""

from __future__ import annotations

from campuspilot.connectors.errors import ConnectorError
from campuspilot.schemas.connectors import (
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
    AscProfileInput,
    AscProfileOutput,
    AscRegistrationOutput,
    AscRegistrationStatusInput,
    AscTimetableOutput,
    ConnectorLoginRequest,
    ConnectorOtpRequest,
    ConnectorStatus,
)

_TODO = "ASC is being rebuilt (v2 ASC Phase 1)."


def _stub() -> ConnectorError:
    return ConnectorError("not_implemented", _TODO)


# --- personal tools (snapshot; offered only with the local model) ---
async def asc_profile(args: AscProfileInput) -> AscProfileOutput:
    raise _stub()


async def asc_my_timetable(args: AscMyTimetableInput) -> AscTimetableOutput:
    raise _stub()


async def asc_my_current_courses(args: AscCurrentCoursesInput) -> AscCoursesOutput:
    raise _stub()


async def asc_registration_status(args: AscRegistrationStatusInput) -> AscRegistrationOutput:
    raise _stub()


async def asc_fee_status(args: AscFeeStatusInput) -> AscFeeStatusOutput:
    raise _stub()


# --- public tools (course data; offered with any model) ---
async def asc_offered_courses(args: AscOfferedCoursesInput) -> AscOfferedCoursesOutput:
    raise _stub()


async def asc_course_offering_history(args: AscCourseHistoryInput) -> AscCourseHistoryOutput:
    raise _stub()


async def asc_course_details(args: AscCourseDetailsInput) -> AscCourseDetailsOutput:
    raise _stub()


# --- Settings ---
async def asc_status() -> ConnectorStatus:
    return ConnectorStatus(name="asc", enabled=True, state="not_connected", message=_TODO)


async def asc_login(req: ConnectorLoginRequest) -> ConnectorStatus:
    raise _stub()


async def asc_submit_otp(req: ConnectorOtpRequest) -> ConnectorStatus:
    raise _stub()


async def asc_refresh() -> ConnectorStatus:
    """Re-read every personal ASC page into the snapshot now (Settings "Refresh ASC data")."""
    raise _stub()


def asc_logout() -> ConnectorStatus:
    return ConnectorStatus(name="asc", enabled=True, state="not_connected")


__all__ = [
    "ConnectorError",
    "asc_course_details",
    "asc_course_offering_history",
    "asc_fee_status",
    "asc_login",
    "asc_logout",
    "asc_my_current_courses",
    "asc_my_timetable",
    "asc_offered_courses",
    "asc_profile",
    "asc_refresh",
    "asc_registration_status",
    "asc_status",
    "asc_submit_otp",
]
