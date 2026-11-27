"""ASC Internal connector (read-only; LDAP login form; campus network or IITB VPN). CONTRACT §11.8.

Page map: ASC_CONNECTOR_PROMPT.md. Modules: pages (allowlist), client (session), parsers,
snapshot (personal data, memory only), tools (tools + state + public cache), demo (fixtures).
"""

from __future__ import annotations

from campuspilot.asc.tools import (
    ConnectorError,
    asc_course_details,
    asc_course_offering_history,
    asc_fee_status,
    asc_login,
    asc_logout,
    asc_my_current_courses,
    asc_my_timetable,
    asc_offered_courses,
    asc_profile,
    asc_refresh,
    asc_registration_status,
    asc_status,
    asc_submit_otp,
    reset_state,
)

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
    "reset_state",
]
