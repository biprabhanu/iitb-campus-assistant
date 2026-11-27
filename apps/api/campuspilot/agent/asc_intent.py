"""Is this question about the student's own ASC data? (v2 ASC, local mode only; CONTRACT §11.8)

Used in three places:
- the orchestrator: a *personal* ASC question is answered only with the local model. With a cloud
  model it gets a fixed reply and no tool or model call; with the local model it uses the ASC
  tools only and never campus documents;
- `asc_tool_call`: the backend runs the right tool itself when the model calls none;
- the scripted MockLLM, so mock mode routes ASC questions like the real model should.

Plain keyword rules, kept simple on purpose. Grades, SPI and CPI are never read, so they match
nothing here.
"""

from __future__ import annotations

import re
from datetime import date

CLOUD_REPLY = (
    "That needs your ASC data, which CampusPilot only shares with the local model. "
    "Switch to Local Gemma in Settings."
)

_I = re.IGNORECASE
_TIMETABLE = re.compile(
    r"\b(my\s+(time\s?table|schedule|classes|lectures)|"
    r"time\s?table\s+(today|tomorrow|this\s+week)|"
    r"(do\s+i\s+have|are\s+there|what|which)\s+(any\s+)?(classes|lectures)|"
    r"classes\s+(today|tomorrow|this\s+week|on\s+\w+day))\b",
    _I,
)
_REGISTRATION = re.compile(
    r"\b(registration\s+(status|window|open|closed|deadline)|"
    r"(am\s+i|have\s+i)\s+(been\s+)?registered|"
    r"is\s+(course\s+)?registration\s+(open|closed))\b",
    _I,
)
_COURSES = re.compile(
    r"\b(my\s+(current\s+|registered\s+|enrolled\s+)?courses|"
    r"(current|registered|enrolled)\s+courses|"
    r"courses\s+i\s*(am|'m|have)?\s*(registered|taking|enrolled|in)|what\s+am\s+i\s+(taking|studying))\b",
    _I,
)
_FEES = re.compile(
    r"\b(my\s+fees?|fees?\s+status|amount\s+due|"
    r"do\s+i\s+(owe|have\s+(any\s+)?(dues|fees))|any\s+dues|dues\s+(pending|left))\b",
    _I,
)
_PROFILE = re.compile(
    r"\b(my\s+(profile|department|dept|program(me)?|advisors?|faculty\s+advisors?|"
    r"academic\s+standing|validity|status)|who\s+is\s+my\s+(faculty\s+)?advisor|"
    r"(academic\s+standing|program\s+validity)|asc\s+profile)\b",
    _I,
)

_CODE = re.compile(r"\b([A-Za-z]{2,4})\s?(\d{3}[A-Za-z]?)\b")
_NOT_DEPT = {"my", "the", "all", "any", "which", "what", "current", "registered", "of", "in"}
_SEMESTER = re.compile(r"\b(autumn|fall|spring|summer|winter|monsoon)\b", _I)
_YEAR_RANGE = re.compile(r"\b(20\d{2})\s*[-/]\s*(\d{2,4})\b")
_YEAR = re.compile(r"\b(20\d{2})\b")
_HISTORY = re.compile(
    r"\b(usually|typically|normally|generally|regularly|every\s+(year|semester)|past|previous|"
    r"last\s+(few\s+)?years?|offered\s+in|which\s+semesters?|history|"
    r"when\s+(is|was|does|do)\b.*\b(offered|run|ran|taught|held))\b",
    _I,
)
_DETAILS = re.compile(
    r"\b(prereq\w*|syllabus|credits?|details?|description|tell\s+me\s+about)\b", _I
)
_OFFERED = re.compile(r"\b(running|run|runs|offered|offering|available|list)\b", _I)
_DAY_WORD = re.compile(
    r"\b(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|nesday|rsday|urday)?\b", _I
)
_DAYS = {
    "mon": "Mon",
    "tue": "Tue",
    "tues": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "thur": "Thu",
    "thurs": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}
_ACADEMIC_START_MONTH = 7  # the Autumn semester starts in July/August


def _which(text: str) -> str | None:
    """The personal ASC tool for this question, or None."""
    if _REGISTRATION.search(text):
        return "asc_registration_status"
    if _FEES.search(text):
        return "asc_fee_status"
    if _TIMETABLE.search(text):
        return "asc_my_timetable"
    if _COURSES.search(text):
        return "asc_my_current_courses"
    if _PROFILE.search(text):
        return "asc_profile"
    return None


def is_asc_personal_question(text: str) -> bool:
    """A question about the student's own timetable, courses, registration, fees or profile."""
    return _which(text) is not None


def _course_code(text: str) -> str | None:
    for dept, number in _CODE.findall(text):
        if dept.lower() not in _NOT_DEPT:
            return f"{dept.upper()} {number.upper()}"
    return None


def _timetable_args(text: str) -> dict:
    low = text.lower()
    if "tomorrow" in low:
        return {"day": "tomorrow"}
    if "today" in low or "tonight" in low:
        return {"day": "today"}
    if "week" in low:
        return {}
    match = _DAY_WORD.search(text)
    if match:
        return {"day": _DAYS[match.group(1).lower()]}
    return {}


def _offered_args(text: str, today: date) -> dict:
    semester = "autumn"
    found = _SEMESTER.search(text)
    if found:
        word = found.group(1).lower()
        semester = {"fall": "autumn", "monsoon": "autumn"}.get(word, word)
    elif today.month < _ACADEMIC_START_MONTH:
        semester = "spring"
    year = today.year if today.month >= _ACADEMIC_START_MONTH else today.year - 1
    ranged = _YEAR_RANGE.search(text)
    single = _YEAR.search(text)
    if ranged:
        year = int(ranged.group(1))
    elif single:
        year = int(single.group(1))
        if semester in ("spring", "summer"):  # "spring 2027" belongs to the 2026-27 year
            year -= 1
    dept = "IE"
    match = re.search(r"\b([A-Za-z]{2,4})\s+(?:department\s+)?courses\b", text)
    if match and match.group(1).lower() not in _NOT_DEPT | {"offered", "running", "which"}:
        dept = match.group(1).upper()
    return {"dept": dept, "year": year, "semester": semester}


def asc_tool_call(text: str, today: date | None = None) -> tuple[str, dict] | None:
    """The read-only ASC tool (name, arguments) a question should use, or None.

    Personal questions pick one of the five snapshot tools; public course questions pick the
    running-courses, offering-history or course-details tool. Grades match nothing.
    """
    today = today or date.today()
    personal = _which(text)
    if personal == "asc_my_timetable":
        return personal, _timetable_args(text)
    if personal is not None:
        return personal, {}
    code = _course_code(text)
    if code and _HISTORY.search(text):
        return "asc_course_offering_history", {"course_code": code}
    if code and _DETAILS.search(text):
        return "asc_course_details", {"course_code": code}
    if (
        re.search(r"\bcourses\b", text, _I)
        and _OFFERED.search(text)
        and not re.search(r"\b(my|i)\b", text, _I)
    ):
        return "asc_offered_courses", _offered_args(text, today)
    return None
