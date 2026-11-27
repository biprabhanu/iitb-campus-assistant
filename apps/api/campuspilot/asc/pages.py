"""ASC Internal page map, menu targets and the read-only allowlist (CONTRACT §11.8).

Source of truth for paths and labels: ASC_CONNECTOR_PROMPT.md (recorded live, 27 Nov 2026).
Page links carry per-session tokens, so they are read from `menu.jsp` by label after each login
and never hard-coded, logged or stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# --- login (plain LDAP form, no SSO redirect) ---
ACADMENU_PATH = "/acadmenu/"  # a frameset: leftPage = menu.jsp, rightPage = WebPages/Login.jsp
LOGIN_PAGE_PATH = "/acadmenu/WebPages/Login.jsp"
LOGIN_POST_PATH = "/acadmenu/WebPages/ldaplogin.jsp"
MENU_PATH = "/acadmenu/menu.jsp"
LOGOUT_PATH = "/acadmenu/index.jsp?logout=yes"
LOGIN_FORM_NAME = "loginForm"
LOGIN_USER_FIELD = "UserName"
LOGIN_PASSWORD_FIELD = "UserPassword"  # noqa: S105 (a form field name, not a secret)

# --- public pages with plain parameters (no token) ---
ALL_DEPT_PATH = "/academic/utility/allDept.jsp"
RUNNING_COURSES_PATH = "/academic/utility/RunningCourses.jsp"
SEMESTER_NUMBER = {"autumn": 1, "spring": 2, "summer": 3, "winter": 4}


@dataclass(frozen=True)
class MenuTarget:
    key: str  # how the code refers to the page
    label: str  # the menu leaf label
    page: str | None  # basename the link must point to; None = mapped from the menu at login


MENU_LINKS: tuple[MenuTarget, ...] = (
    MenuTarget("timetable", "My Timetable", "VenueOccupancy.jsp"),
    MenuTarget("record", "View", "AcademicRecord.jsp"),
    MenuTarget("registration", "Status", "CRFFormInput.jsp"),
    MenuTarget("running", "Running Courses", "allDept.jsp"),
    MenuTarget("syllabus", "Course Syllabus", "newallCourse.jsp"),
    MenuTarget("prereq", "Course Prerequisites", "Prereq"),
    # Not mapped live yet: the page name is taken from the menu leaf at login (see
    # `fee_page_allowed`) and allowed for that session only. Pin it here after live mapping.
    MenuTarget("fees", "Fees Status/Scholarship", None),
)
FEE_PAGE: str | None = None

# Menu leaves that are write flows or money/forms: never opened, whatever their URL.
FORBIDDEN_LABELS = frozenset(
    label.casefold()
    for label in (
        "Registration/Adjustment",
        "Course Withdraw",
        "Canara Bank Authorisation Letter",
        "Pay Convo Fees",
        "Course Feedback",
        "Update/Apply for scholarship",
    )
)
FORBIDDEN_KEYWORDS = (
    "bank",
    "canara",
    "pay",
    "apply",
    "update",
    "feedback",
    "alumni",
    "convo",
    "withdraw",
    "adjustment",
)

# Allowed last path segments (exact, case-sensitive). Everything else is refused.
STATIC_PAGES = frozenset(
    {
        "",  # /acadmenu/ frameset
        "Login.jsp",
        "ldaplogin.jsp",
        "menu.jsp",
        "index.jsp",  # only with ?logout=yes (see request_allowed)
        "VenueOccupancy.jsp",
        "AcademicRecord.jsp",
        "CRFFormInput.jsp",  # GET only
        "allDept.jsp",
        "RunningCourses.jsp",
        "crsedetail.jsp",
        "newallCourse.jsp",
        "Prereq",
        "TTcheck.jsp",
    }
)
POST_PAGES = frozenset({"ldaplogin.jsp", "allDept.jsp", "RunningCourses.jsp"})
ALLOWED_PREFIXES = ("/acadmenu/", "/academic/")


def norm_label(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def has_forbidden_keyword(text: str) -> bool:
    low = text.casefold()
    return any(word in low for word in FORBIDDEN_KEYWORDS)


def label_forbidden(label: str) -> bool:
    return norm_label(label) in FORBIDDEN_LABELS or has_forbidden_keyword(label)


def path_allowed(method: str, path: str, extra_pages: frozenset[str] = frozenset()) -> bool:
    """May the connector send `method` to this URL path? `path` has no query string.

    `extra_pages` is the session's fee page (taken from the menu at login)."""
    if not path.startswith(ALLOWED_PREFIXES) or has_forbidden_keyword(path):
        return False
    name = basename(path)
    if method == "POST":
        return name in POST_PAGES
    return (
        name in STATIC_PAGES or name in extra_pages or (FEE_PAGE is not None and name == FEE_PAGE)
    )


def request_allowed(
    method: str, url: str, base_host: str, extra_pages: frozenset[str] = frozenset()
) -> bool:
    """Full check used for the first request and for every redirect hop."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() != base_host.lower():
        return False
    if basename(parts.path) == "index.jsp" and "logout=yes" not in parts.query:
        return False
    return path_allowed(method, parts.path, extra_pages)


def fee_page_allowed(label: str, path: str) -> bool:
    """A menu leaf may become the session's fee page only if nothing about it is forbidden."""
    return (
        norm_label(label) == norm_label("Fees Status/Scholarship")
        and not has_forbidden_keyword(path)
        and path.startswith(ALLOWED_PREFIXES)
        and bool(basename(path))
    )
