"""ASC connector (read-only; internal portal, IITB SSO login). CONTRACT §11.

PHASE 0 STUB: these are the exact signatures the registry and API call. Worker B replaces the
bodies (and may add modules in this package), keeping the signatures.
"""

from __future__ import annotations

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

__all__ = [
    "ConnectorError",
    "asc_login",
    "asc_logout",
    "asc_status",
    "asc_submit_otp",
    "get_my_grades",
    "get_my_registered_courses",
    "get_my_timetable",
]

_TODO = "ASC is not built yet."


async def get_my_timetable(args: GetMyTimetableInput) -> AscTimetableOutput:
    raise ConnectorError("not_implemented", _TODO)


async def get_my_registered_courses(args: GetMyRegisteredCoursesInput) -> AscCoursesOutput:
    raise ConnectorError("not_implemented", _TODO)


async def get_my_grades(args: GetMyGradesInput) -> AscGradesOutput:
    raise ConnectorError("not_implemented", _TODO)


async def asc_status() -> ConnectorStatus:
    return ConnectorStatus(name="asc", enabled=True, state="error", message=_TODO)


async def asc_login(req: ConnectorLoginRequest) -> ConnectorStatus:
    raise ConnectorError("not_implemented", _TODO)


async def asc_submit_otp(req: ConnectorOtpRequest) -> ConnectorStatus:
    raise ConnectorError("not_implemented", _TODO)


def asc_logout() -> ConnectorStatus:
    raise ConnectorError("not_implemented", _TODO)
