"""ASC connector (read-only; internal portal, IITB SSO login). CONTRACT §11.

Modules: `pages` (all page-specific constants), `client` (one session, GET-only after login),
`login` (SSO form, OTP, CAPTCHA), `parsers` (HTML -> models), `tools` (the tools and Settings
actions), `credentials` (Keychain), `demo` (fixtures).
"""

from __future__ import annotations

from campuspilot.asc.tools import (
    asc_login,
    asc_logout,
    asc_status,
    asc_submit_otp,
    get_my_grades,
    get_my_registered_courses,
    get_my_timetable,
)
from campuspilot.connectors.errors import ConnectorError

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
