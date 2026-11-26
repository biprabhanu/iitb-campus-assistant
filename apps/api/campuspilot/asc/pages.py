"""Everything page-specific about ASC and the SSO login, in one place.

The real URLs and page layout are NOT known yet (they are checked live in Phase 2 with the
owner). Until then these are best guesses, so adjusting ASC support later should only mean
editing this file. Nothing here is a secret.
"""

from __future__ import annotations

# --- Pages, relative to settings.asc_base_url. PLACEHOLDERS: verify in Phase 2. ---
PAGE_COURSES = "/courses"
PAGE_TIMETABLE = "/timetable"
PAGE_GRADES = "/grades"

# Redirects are followed by hand and every hop must be https on a host ending with this.
ALLOWED_HOST_SUFFIX = ".iitb.ac.in"
MAX_REDIRECTS = 5

# How long a half-finished login (waiting for the OTP) stays in memory.
PENDING_TTL_S = 300
MAX_OTP_TRIES = 3

# --- Login page detection (CSS selectors and lower-case substrings) ---
CAPTCHA_SELECTORS = (
    "img[src*=captcha i]",
    "img[id*=captcha i]",
    "img[class*=captcha i]",
    "img[alt*=captcha i]",
    ".g-recaptcha",
    ".h-captcha",
    "iframe[src*=recaptcha i]",
    "iframe[src*=hcaptcha i]",
    "script[src*=recaptcha i]",
    "script[src*=hcaptcha i]",
    "input[name*=captcha i]",
)
# An input whose name/id contains one of these is the one-time-code field.
OTP_FIELD_HINTS = ("otp", "totp", "token", "verification", "passcode", "authcode")
# Text that says "type your one-time code".
OTP_TEXT_HINTS = ("one-time", "one time", "otp", "verification code", "two-factor", "2-step")
# Username field names, tried when the form has several text inputs.
USERNAME_NAME_HINTS = ("user", "login", "uid", "ldap", "email")
# After login, ASC pages carry a logout link; it is the "we are inside" marker.
HOME_LINK_SELECTOR = "a[href*=logout i]"

# --- Parsing: header words (lower case) that identify each column. Tolerant to order. ---
# More specific words come first ("course code" before "code").
COURSE_HEADERS = {
    "code": ("course code", "code"),
    "title": ("course title", "course name", "title", "name"),
    "credits": ("credit",),
    "slot": ("slot",),
    "instructor": ("instructor", "faculty", "professor"),
    "status": ("status",),
    "semester": ("semester", "term"),
}
TIMETABLE_HEADERS = {
    "code": ("course code", "code"),
    "title": ("course title", "course name", "title", "name"),
    "day": ("day",),
    "time": ("time", "timing", "timings"),
    "venue": ("venue", "room", "location", "hall"),
    "slot": ("slot",),
    "kind": ("type", "kind", "mode"),
}
GRADE_HEADERS = {
    "code": ("course code", "code"),
    "title": ("course title", "course name", "title", "name"),
    "credits": ("credit",),
    "grade": ("grade",),
    "semester": ("semester", "term"),
}
# A heading like "2026-27 Autumn" names the semester of the table after it.
SEMESTER_RE = r"\d{4}\D{0,3}\d{0,4}\s*(autumn|spring|summer|monsoon)|(autumn|spring|summer)\s*\d{4}"
# Where a registration deadline/status message might sit. A guess: check in Phase 2.
REGISTRATION_NOTE_SELECTOR = "[class*=alert], [class*=notice], [id*=registration]"
# Pages that legitimately have no table because there is nothing to show.
EMPTY_PAGE_HINTS = ("no courses", "no records", "no data", "not registered for any")
