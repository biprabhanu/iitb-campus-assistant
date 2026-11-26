"""Turn ASC pages into the CONTRACT models. Pure functions, no network.

Tables are found by their header text, so a different column order or an extra column does not
matter. If the expected table is not there we raise `parse_failed`; we never guess values.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from bs4 import BeautifulSoup, Tag

from campuspilot.asc import pages
from campuspilot.connectors.errors import ConnectorError
from campuspilot.schemas.connectors import AscCourse, AscGrade, AscTimetableSlot

_DAYS = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}
_TIME_RE = re.compile(r"(\d{1,2})\s*[:.]\s*(\d{2})\s*(am|pm)?", re.IGNORECASE)


def _fail(what: str) -> ConnectorError:
    # Never include page text here: it may hold personal data.
    return ConnectorError(
        "parse_failed",
        f"The ASC {what} page looks different than expected, so CampusPilot didn't guess. "
        "Check ASC in your browser.",
    )


def _clean(text: str) -> str:
    return " ".join(text.split())


# ---------- tables ----------


def _map_columns(headers: list[str], wanted: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """field -> column index. Each column is used at most once; earlier keywords win."""
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for field_name, keywords in wanted.items():
        for keyword in keywords:
            hit = next((i for i, h in enumerate(headers) if i not in used and keyword in h), None)
            if hit is not None:
                mapping[field_name] = hit
                used.add(hit)
                break
    return mapping


def _tables(
    soup: BeautifulSoup, wanted: dict[str, tuple[str, ...]], required: tuple[str, ...]
) -> Iterator[tuple[Tag, dict[str, int], list[list[str]]]]:
    """Yield (table, column map, data rows) for tables that have all the required columns."""
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [_clean(c.get_text(" ")).lower() for c in rows[0].find_all(["th", "td"])]
        mapping = _map_columns(headers, wanted)
        if not all(name in mapping for name in required):
            continue
        data = []
        for row in rows[1:]:
            cells = [_clean(c.get_text(" ")) for c in row.find_all(["td", "th"])]
            if len(cells) >= len(headers):  # skips spacer and summary rows
                data.append(cells)
        yield table, mapping, data


def _cell(row: list[str], mapping: dict[str, int], name: str) -> str:
    idx = mapping.get(name)
    return row[idx] if idx is not None and idx < len(row) else ""


def _semester_of(table: Tag) -> str:
    """The semester a table belongs to: its caption or the nearest heading before it."""
    caption = table.find("caption")
    candidates = [caption] if caption else []
    candidates.append(table.find_previous(["h1", "h2", "h3", "h4", "h5"]))
    for node in candidates:
        if node is not None:
            text = _clean(node.get_text(" "))
            if re.search(pages.SEMESTER_RE, text, re.IGNORECASE):
                return text
    return ""


def _credits(text: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def _is_empty_page(soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ").lower()
    return any(hint in text for hint in pages.EMPTY_PAGE_HINTS)


# ---------- courses ----------


def _status(text: str) -> str:
    t = text.lower()
    if "dropped" in t or "withdr" in t:
        return "dropped"
    if "audit" in t:
        return "audit"
    if "not registered" in t or "unregistered" in t:
        return "other"
    if "pending" in t or "await" in t:
        return "pending"
    if "approved" in t:
        return "approved"
    if "registered" in t:
        return "registered"
    return "other"


def parse_courses(html: str) -> tuple[list[AscCourse], str, str]:
    """-> (courses, semester, registration_note)."""
    soup = BeautifulSoup(html, "html.parser")
    courses: list[AscCourse] = []
    matched = False
    for table, mapping, rows in _tables(soup, pages.COURSE_HEADERS, ("code",)):
        matched = True
        page_semester = _semester_of(table)
        for row in rows:
            code = _cell(row, mapping, "code")
            if not code:
                continue
            courses.append(
                AscCourse(
                    code=code,
                    title=_cell(row, mapping, "title"),
                    credits=_credits(_cell(row, mapping, "credits")),
                    slot=_cell(row, mapping, "slot") or None,
                    instructor=_cell(row, mapping, "instructor") or None,
                    status=_status(_cell(row, mapping, "status")),  # type: ignore[arg-type]
                    semester=_cell(row, mapping, "semester") or page_semester,
                )
            )
        break  # the first matching table is the registration table
    if not matched and not _is_empty_page(soup):
        raise _fail("courses")
    semesters = {c.semester for c in courses if c.semester}
    semester = semesters.pop() if len(semesters) == 1 else ""
    note = soup.select_one(pages.REGISTRATION_NOTE_SELECTOR)
    return courses, semester, _clean(note.get_text(" "))[:300] if note else ""


# ---------- timetable ----------


def _day(text: str) -> str | None:
    return _DAYS.get(text.strip()[:3].lower())


def _clock(match: re.Match[str]) -> str | None:
    hour, minute, ampm = int(match.group(1)), int(match.group(2)), (match.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _times(text: str) -> tuple[str, str] | None:
    matches = list(_TIME_RE.finditer(text))
    if len(matches) != 2:
        return None
    # "2:00 - 5:00 PM" is ambiguous (is 2:00 am or pm?): am/pm on both or neither, else skip.
    if bool(matches[0].group(3)) != bool(matches[1].group(3)):
        return None
    start, end = _clock(matches[0]), _clock(matches[1])
    return (start, end) if start and end else None


def _kind(text: str) -> str:
    t = text.lower()
    if "tut" in t:
        return "tutorial"
    if "lab" in t or "practical" in t:
        return "lab"
    if "lec" in t:
        return "lecture"
    return "other"


NO_TIMES_NOTE = (
    "ASC shows slot codes but no class times, and CampusPilot doesn't guess the times. "
    "Check the slot timings in ASC."
)


def parse_timetable(html: str) -> tuple[list[AscTimetableSlot], str]:
    """-> (slots, note). Slots are weekly; filtering by date happens in the tool."""
    soup = BeautifulSoup(html, "html.parser")
    for _table, mapping, rows in _tables(soup, pages.TIMETABLE_HEADERS, ("code", "day", "time")):
        slots = []
        for row in rows:
            day, times = _day(_cell(row, mapping, "day")), _times(_cell(row, mapping, "time"))
            code = _cell(row, mapping, "code")
            if not (code and day and times):
                continue  # a row we can't read fully is skipped, never filled in
            slots.append(
                AscTimetableSlot(
                    course_code=code,
                    course_title=_cell(row, mapping, "title"),
                    day=day,  # type: ignore[arg-type]
                    start=times[0],
                    end=times[1],
                    venue=_cell(row, mapping, "venue") or None,
                    slot=_cell(row, mapping, "slot") or None,
                    kind=_kind(_cell(row, mapping, "kind")),  # type: ignore[arg-type]
                )
            )
        if slots or not rows:
            return slots, ""
        raise _fail("timetable")  # rows exist but none could be read
    # No timetable table. If the page at least lists courses with slot codes, say what is known.
    if list(_tables(soup, pages.COURSE_HEADERS, ("code", "slot"))):
        return [], NO_TIMES_NOTE
    if _is_empty_page(soup):
        return [], ""
    raise _fail("timetable")


# ---------- grades ----------

_SPI_RE = re.compile(r"\b(?:SPI|SGPA)\b\s*[:=\-]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_CPI_RE = re.compile(r"\b(?:CPI|CGPA)\b\s*[:=\-]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def _only(values: list[str]) -> str | None:
    """A single distinct value, else None: with several semesters we don't pick one."""
    distinct = list(dict.fromkeys(values))
    return distinct[0] if len(distinct) == 1 else None


def parse_grades(html: str) -> tuple[list[AscGrade], str | None, str | None]:
    """-> (grades, spi, cpi). SPI/CPI are returned exactly as the page shows them."""
    soup = BeautifulSoup(html, "html.parser")
    grades: list[AscGrade] = []
    matched = False
    for table, mapping, rows in _tables(soup, pages.GRADE_HEADERS, ("code", "grade")):
        matched = True
        page_semester = _semester_of(table)
        for row in rows:
            code, grade = _cell(row, mapping, "code"), _cell(row, mapping, "grade")
            if not (code and grade):
                continue
            grades.append(
                AscGrade(
                    course_code=code,
                    course_title=_cell(row, mapping, "title"),
                    credits=_credits(_cell(row, mapping, "credits")),
                    grade=grade,
                    semester=_cell(row, mapping, "semester") or page_semester,
                )
            )
    if not matched and not _is_empty_page(soup):
        raise _fail("grades")
    text = soup.get_text(" ")
    return grades, _only(_SPI_RE.findall(text)), _only(_CPI_RE.findall(text))
