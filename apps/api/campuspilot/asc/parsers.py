"""Pure HTML parsers for ASC Internal pages (BeautifulSoup). No network, no logging.

Privacy by construction (CONTRACT §11.8): these functions never return grades, SPI/CPI, the
performance summary, roll number, name or bank details. The Grade column of a semester table is
only checked for emptiness (to find the current semester); its value is never stored. The SPI/CPI
and performance tables are recognised by their header and skipped without reading their cells.

Layouts recorded live (27 Nov 2026) and parsed exactly: frameset, login form, menu, timetable
grid, academic record, allDept, RunningCourses.

needs_human_review: crsedetail.jsp, newallCourse.jsp, Prereq, the registration status page (only
shown during the window) and the fee status page. Their layouts were never seen, so these parsers
are tolerant (label: value pairs and tables) and must be checked against the real pages.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup, Tag

from campuspilot.asc import pages
from campuspilot.schemas.connectors import (
    AscCourse,
    AscCourseDetail,
    AscFeeItem,
    AscProfile,
    AscTimetableSlot,
)

_CODE = r"[A-Za-z]{2,4}\s?\d{3,4}[A-Za-z]?"
CODE_RE = re.compile(rf"\b({_CODE})\b")
_CODE_FULL = re.compile(rf"^{_CODE}$")
# ASC prints "09:30 10:25" (two lines, no dash) and drops ":00" ("14 15:25", "17:05 18").
_TIME_RE = re.compile(r"^\s*(?=[^:]*:)(\d{1,2})(?::(\d{2}))?\s*(?:-\s*)?(\d{1,2})(?::(\d{2}))?\s*$")
_DAY_RE = re.compile(r"^\s*\d*\s*\.?\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)", re.I)
_TERM_RE = re.compile(r"autumn|spring|summer|winter", re.I)
_YEARS_RE = re.compile(r"(\d{4})\s*[-/]\s*(\d{2,4})")
_BAD_SECTION = re.compile(r"bank|account|ifsc|apply|canara|neft|swift", re.I)


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_variant(raw: str) -> str:
    """'IE 603 (S1)' -> 'IE 603': ASC adds a section/division tag in brackets after some codes."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", raw or "").strip()


def normalise_code(raw: str) -> str:
    """'ie624' / 'IE  624' -> 'IE 624'."""
    m = re.match(r"^\s*([A-Za-z]{2,4})\s*(\d{3,4}[A-Za-z]?)\s*$", raw or "")
    return f"{m[1].upper()} {m[2].upper()}" if m else squash(raw)


def _rows(table: Tag) -> list[Tag]:
    """Rows that belong to this table, not to a table nested inside it."""
    return [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]


def _cells(row: Tag) -> list[Tag]:
    return [c for c in row.find_all(["td", "th"]) if c.find_parent("tr") is row]


def _span(cell: Tag) -> int:
    try:
        return max(1, int(cell.get("colspan", 1)))
    except (TypeError, ValueError):
        return 1


def _text(cell: Tag) -> str:
    return squash(cell.get_text(" "))


def _lines(cell: Tag) -> list[str]:
    return [squash(p) for p in cell.get_text("\n").split("\n") if squash(p)]


def _floatish(text: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m[0]) if m else None


# ---------------------------------------------------------------- frameset, login, menu


def parse_frameset(html: str) -> dict[str, str]:
    """frame name -> src (leftPage, rightPage1, rightPage)."""
    frames: dict[str, str] = {}
    for frame in soup(html).find_all(["frame", "iframe"]):
        name, src = frame.get("name"), frame.get("src")
        if name and src:
            frames[str(name)] = html_lib.unescape(str(src))
    return frames


@dataclass
class LoginForm:
    action: str
    user_field: str
    password_field: str
    hidden: dict[str, str] = field(default_factory=dict)


def parse_login_form(html: str) -> LoginForm | None:
    s = soup(html)
    for form in s.find_all("form"):
        pw = form.find("input", attrs={"type": re.compile("^password$", re.I)})
        if pw is None:
            continue
        user_field = pages.LOGIN_USER_FIELD
        for inp in form.find_all("input"):
            kind = str(inp.get("type", "text")).lower()
            if kind == "text" and inp.get("name"):
                user_field = str(inp["name"])
                break
        hidden = {
            str(i["name"]): str(i.get("value", ""))
            for i in form.find_all("input", attrs={"type": re.compile("^hidden$", re.I)})
            if i.get("name")
        }
        return LoginForm(
            action=html_lib.unescape(str(form.get("action") or pages.LOGIN_POST_PATH)),
            user_field=user_field,
            password_field=str(pw.get("name") or pages.LOGIN_PASSWORD_FIELD),
            hidden=hidden,
        )
    return None


def looks_like_login_page(html: str) -> bool:
    low = (html or "").lower()
    return ("loginform" in low or "userpassword" in low) and "password" in low


def menu_signed_in(html: str) -> bool:
    low = (html or "").lower()
    return "logout=yes" in low or "sign out" in low or "signout" in low


@dataclass(frozen=True)
class MenuLink:
    label: str
    href: str = field(repr=False)  # carries a session token: never log it

    def __repr__(self) -> str:
        return f"MenuLink({self.label!r})"


_JS_OBJECT = re.compile(r"\{[^{}]*\}", re.S)
_JS_KEY = r"""["']?{key}["']?\s*:\s*(?P<q>["'])(?P<val>(?:\\.|(?!(?P=q)).)*)(?P=q)"""
_LABEL_RE = re.compile(_JS_KEY.format(key="label"), re.S)
_HREF_RE = re.compile(_JS_KEY.format(key="href"), re.S)


def _js_unescape(value: str) -> str:
    value = re.sub(r"\\(.)", r"\1", value)
    return html_lib.unescape(value)


_JS_ANCHOR = re.compile(
    r"""<a\s[^>]*?href\s*=\s*(?:\\?['"])(?P<href>[^'"\\]*)(?:\\?['"])[^>]*>(?P<label>.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)


def parse_menu(html: str) -> list[MenuLink]:
    """Leaf links of the YUI TreeView: JS object literals `{label: "..", href: ".."}` (either
    key order, single or double quotes) and plain `<a href>` links."""
    links: list[MenuLink] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, href: str) -> None:
        label, href = squash(label), href.strip()
        if label and href and (label, href) not in seen:
            seen.add((label, href))
            links.append(MenuLink(label, href))

    s = soup(html)
    script_text = "\n".join(t.get_text() for t in s.find_all("script")) or html or ""
    for chunk in _JS_OBJECT.findall(script_text):
        label, href = _LABEL_RE.search(chunk), _HREF_RE.search(chunk)
        if label and href:
            add(_js_unescape(label["val"]), _js_unescape(href["val"]))
    # The live menu (27 Nov 2026) builds each leaf as an anchor inside a JS string:
    #   buildChild(Node,"<a href='/academic/...?<token>' ...>My Timetable</a>",false)
    # BeautifulSoup doesn't parse markup inside <script>, so read those anchors with a regex.
    for m in _JS_ANCHOR.finditer(script_text):
        href = _js_unescape(m["href"])
        if not href.lower().startswith("javascript"):
            add(
                html_lib.unescape(re.sub(r"<[^>]+>", " ", _js_unescape(m["label"]))),
                html_lib.unescape(href),
            )
    for a in s.find_all("a", href=True):
        href = str(a["href"])
        if not href.lower().startswith("javascript"):
            add(a.get_text(" "), html_lib.unescape(href))
    return links


# ---------------------------------------------------------------- timetable


def _hhmm(h: str, m: str | None) -> str:
    return f"{int(h):02d}:{m or '00'}"


_BRACKET = re.compile(r"^(?P<first>.*?)\s*-\s*(?P<vtype>[^:]*?)\s*:\s*(?P<venue>.*)$")


def _kind(first: str) -> str:
    token = (first.split() or [""])[0].upper()
    if token in {"LC", "L", "LEC", "LECTURE"}:
        return "lecture"
    if token in {"TU", "TUT", "T", "TUTORIAL"}:
        return "tutorial"
    if token in {"LAB", "P", "PR", "LB"}:
        return "lab"
    return "lecture" if not token else "other"


def _cell_entries(text: str) -> list[tuple[str, str | None, str | None, str]]:
    """'IE 303 [LC 001 - Class Room : LC 001 ] : Instructor' (one or more) ->
    [(code, venue, instructor, kind)]."""
    text = squash(text)
    starts = [m for m in re.finditer(rf"({_CODE})\s*\[", text)]
    out = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        seg = text[m.start() : end]
        close = seg.find("]")
        if close < 0:
            continue
        bracket = seg[seg.find("[") + 1 : close]
        instructor = squash(seg[close + 1 :]).lstrip(":").strip() or None
        venue, kind = None, "lecture"
        b = _BRACKET.match(bracket)
        if b:
            venue = squash(b["venue"]) or None
            kind = _kind(squash(b["first"]))
        else:
            venue = squash(bracket) or None
        out.append((normalise_code(m[1]), venue, instructor, kind))
    return out


def parse_timetable(html: str) -> list[AscTimetableSlot]:
    """The "Venue Occupancy Timetable" grid. Never reads the 'for <ROLL>' line."""
    s = soup(html)
    best: tuple[int, Tag] | None = None
    for table in s.find_all("table"):
        n = sum(len(_TIME_RE.findall(_text(c))) for r in _rows(table)[:3] for c in _cells(r))
        if n and (best is None or n > best[0]):
            best = (n, table)
    if best is None:
        return []
    table = best[1]
    rows = _rows(table)
    header_row = next(r for r in rows if any(_TIME_RE.search(_text(c)) for c in _cells(r)))
    columns: list[tuple[str, str] | None] = []
    for cell in _cells(header_row):
        m = _TIME_RE.search(_text(cell))
        slot = (_hhmm(m[1], m[2]), _hhmm(m[3], m[4])) if m else None
        columns.extend([slot] * _span(cell))
    if columns and columns[0] is not None:
        columns.insert(0, None)  # header without a corner cell: rows still start with the day
    slots: list[AscTimetableSlot] = []
    seen: set[tuple] = set()
    for row in rows[rows.index(header_row) + 1 :]:
        cells = _cells(row)
        if not cells:
            continue
        day_match = _DAY_RE.match(_text(cells[0]))
        if not day_match:
            continue
        day = day_match[1].capitalize()
        idx = _span(cells[0])
        for cell in cells[1:]:
            span = _span(cell)
            covered = [c for c in columns[idx : idx + span] if c]
            idx += span
            if not covered:
                continue
            start, end = covered[0][0], covered[-1][1]
            for code, venue, instructor, kind in _cell_entries(cell.get_text(" ")):
                key = (day, start, end, code, venue)
                if key in seen:
                    continue
                seen.add(key)
                slots.append(
                    AscTimetableSlot(
                        course_code=code,
                        day=day,  # type: ignore[arg-type]
                        start=start,
                        end=end,
                        venue=venue,
                        instructor=instructor,
                        kind=kind,  # type: ignore[arg-type]
                    )
                )
    return slots


# ---------------------------------------------------------------- academic record


@dataclass
class Semester:
    name: str
    courses: list[AscCourse]
    all_grades_empty: bool
    order: tuple[int, int] = (0, 0)


@dataclass
class AcademicRecord:
    profile: AscProfile
    semesters: list[Semester]

    @property
    def current(self) -> Semester | None:
        """The semester whose Grade cells are all empty (the latest one if there are several)."""
        empty = [s for s in self.semesters if s.all_grades_empty and s.courses]
        if not empty:
            return None
        return max(enumerate(empty), key=lambda p: (p[1].order, p[0]))[1]


_TERM_ORDER = {"winter": 0, "spring": 1, "summer": 2, "autumn": 3}


def _semester_name(table: Tag, header_row: Tag) -> tuple[str, tuple[int, int]]:
    parts: list[str] = []
    cap = table.find("caption")
    if cap:
        parts.append(_text(cap))
    rows = _rows(table)
    for row in rows[: rows.index(header_row)]:
        parts.append(_text(row))
    for sib in table.previous_siblings:
        if isinstance(sib, Tag):
            if sib.name == "table":
                break
            parts.append(_text(sib))
        elif str(sib).strip():
            parts.append(squash(str(sib)))
        if len(parts) > 6:
            break
    for text in parts:
        term, years = _TERM_RE.search(text), _YEARS_RE.search(text)
        if term and years:
            start = int(years[1])
            end = years[2][-2:]
            name = f"{start}-{end} {term[0].capitalize()}"
            return name, (start, _TERM_ORDER[term[0].lower()])
        if term:
            return term[0].capitalize(), (0, _TERM_ORDER[term[0].lower()])
    return "", (0, 0)


def _header_index(cells: list[str]) -> dict[str, int]:
    names = [squash(c).casefold() for c in cells]
    wanted = {
        "code": "course code",
        "name": "course name",
        "tag": "tag",
        "credits": "credits",
        "grade": "grade",
        "audit": "credit/audit",
    }
    return {k: names.index(v) for k, v in wanted.items() if v in names}


_PROFILE_KEYS = (
    ("validity", "validity"),
    ("standing", "academic standing"),
    ("advisors", "advisor"),
    ("department", "department"),
    ("program", "program"),
    ("status", "status"),
)


def _profile_from(table: Tag) -> AscProfile | None:
    """Only the wanted labels are looked at; roll number and name are never read."""
    found: dict[str, str] = {}
    for row in _rows(table):
        cells = _cells(row)
        for i in range(0, len(cells) - 1, 2):
            label = squash(cells[i].get_text(" ")).rstrip(":").strip().casefold()
            for key, needle in _PROFILE_KEYS:
                if needle in label:
                    if key in found and key != "advisors":
                        break  # "Program validity date" comes before "Semester validity date"
                    if key == "advisors":
                        found[key] = "\n".join(_lines(cells[i + 1]))
                    else:
                        found[key] = _text(cells[i + 1])
                    break
    if not found:
        return None
    advisors = [a.strip() for a in re.split(r"[\n;]+", found.get("advisors", "")) if a.strip()]
    return AscProfile(
        department=found.get("department", ""),
        program=found.get("program", ""),
        status=found.get("status", ""),
        validity=found.get("validity", ""),
        academic_standing=found.get("standing", ""),
        advisors=advisors,
    )


def _merge_profile(a: AscProfile | None, b: AscProfile) -> AscProfile:
    if a is None:
        return b
    merged = {k: getattr(a, k) or getattr(b, k) for k in AscProfile.model_fields}
    return AscProfile(**merged)


def parse_academic_record(html: str) -> AcademicRecord:
    """Profile (table 1, no roll/name) and one entry per semester table. Grades are dropped."""
    profile: AscProfile | None = None
    semesters: list[Semester] = []
    for table in soup(html).find_all("table"):
        rows = _rows(table)
        header_row = next(
            (r for r in rows if "course code" in [_text(c).casefold() for c in _cells(r)]), None
        )
        if header_row is None:
            # SPI/CPI and performance tables have no "Course Code" header: only the wanted
            # profile labels are read from them, so no grade is ever looked at. The profile is
            # spread over two tables (identity block, advisor row): merge, first value wins.
            found = _profile_from(table)
            if found is not None:
                profile = _merge_profile(profile, found)
            continue
        idx = _header_index([_text(c) for c in _cells(header_row)])
        if "code" not in idx:
            continue
        courses: list[AscCourse] = []
        grade_cells_empty = True
        sem_name, sem_order = _semester_name(table, header_row)
        for row in rows[rows.index(header_row) + 1 :]:
            cells = _cells(row)
            texts = [_text(c) for c in cells]

            def at(key: str, texts: list[str] = texts, idx: dict[str, int] = idx) -> str:
                i = idx.get(key)
                return texts[i] if i is not None and i < len(texts) else ""

            code_text = strip_variant(at("code"))
            if not _CODE_FULL.match(code_text):
                continue
            if at("grade"):  # emptiness only; the value itself is dropped here
                grade_cells_empty = False
            courses.append(
                AscCourse(
                    code=normalise_code(code_text),
                    title=at("name"),
                    credits=_floatish(at("credits")),
                    tag=at("tag") or None,
                    credit_audit=at("audit") or None,
                    status="audit" if at("audit").casefold() == "audit" else "registered",
                    semester=sem_name,
                )
            )
        if courses:
            semesters.append(Semester(sem_name, courses, grade_cells_empty, sem_order))
    return AcademicRecord(profile or AscProfile(), semesters)


# ---------------------------------------------------------------- registration status
# needs_human_review: the real status page (open registration window) was never seen.

_STATUS_WORDS = (
    ("dropped", "dropped"),
    ("drop", "dropped"),
    ("approved", "approved"),
    ("pending", "pending"),
    ("audit", "audit"),
    ("registered", "registered"),
)


def parse_registration_status(html: str) -> list[AscCourse]:
    out: list[AscCourse] = []
    for table in soup(html).find_all("table"):
        rows = _rows(table)
        for i, row in enumerate(rows):
            heads = [_text(c).casefold() for c in _cells(row)]
            code_i = next((k for k, h in enumerate(heads) if h in ("course code", "code")), None)
            if code_i is None:
                continue
            name_i = next((k for k, h in enumerate(heads) if "name" in h or "title" in h), None)
            cred_i = next(
                (k for k, h in enumerate(heads) if "credit" in h and "audit" not in h), None
            )
            stat_i = next((k for k, h in enumerate(heads) if "status" in h), None)
            for body in rows[i + 1 :]:
                cells = [_text(c) for c in _cells(body)]
                if code_i >= len(cells) or not _CODE_FULL.match(cells[code_i]):
                    continue
                status_text = (
                    cells[stat_i].casefold() if stat_i is not None and stat_i < len(cells) else ""
                )
                status = next((v for k, v in _STATUS_WORDS if k in status_text), "other")
                out.append(
                    AscCourse(
                        code=normalise_code(cells[code_i]),
                        title=cells[name_i] if name_i is not None and name_i < len(cells) else "",
                        credits=_floatish(cells[cred_i])
                        if cred_i is not None and cred_i < len(cells)
                        else None,
                        status=status,  # type: ignore[arg-type]
                    )
                )
            break
    return out


# ---------------------------------------------------------------- public course pages


def parse_all_dept(html: str) -> dict[str, str]:
    """Department prefix -> the `deptcd` value of its RunningCourses link ('IE' -> 'IE,IES')."""
    mapping: dict[str, str] = {}
    for a in soup(html).find_all("a", href=True):
        href = html_lib.unescape(str(a["href"]))
        if "RunningCourses" not in href:
            continue
        query = parse_qs(urlsplit(href).query)
        for dept in query.get("deptcd", []):
            dept = unquote(dept).strip()
            for prefix in dept.split(","):
                if prefix.strip():
                    mapping.setdefault(prefix.strip().upper(), dept)
    return mapping


@dataclass
class RunningRow:
    course: AscCourse
    detail_href: str | None = field(default=None, repr=False)


def parse_running_courses(html: str, semester: str = "") -> list[RunningRow]:
    best: tuple[int, list[RunningRow]] | None = None
    for table in soup(html).find_all("table"):
        rows = _rows(table)
        header_i = next(
            (
                i
                for i, r in enumerate(rows)
                if "course code" in [_text(c).casefold() for c in _cells(r)]
            ),
            None,
        )
        if header_i is None:
            continue
        heads = [_text(c).casefold() for c in _cells(rows[header_i])]

        def col(*needles: str, heads: list[str] = heads) -> int | None:
            for k, h in enumerate(heads):
                if any(h.startswith(n) for n in needles):
                    return k
            return None

        c_code, c_name = heads.index("course code"), col("course name")
        c_inst = col("instructor(s)")  # not the "Instructor Status" column before it
        if c_inst is None:
            c_inst = col("instructor")
        c_type, c_venue = col("course type"), col("venue")
        c_slot, c_div, c_cred = col("slot"), col("division"), col("credit")
        found: list[RunningRow] = []
        for row in rows[header_i + 1 :]:
            cells = _cells(row)
            texts = [_text(c) for c in cells]

            def at(i: int | None, texts: list[str] = texts) -> str:
                return texts[i] if i is not None and i < len(texts) else ""

            if not _CODE_FULL.match(strip_variant(at(c_code))):
                continue
            link = cells[c_code].find("a", href=True) or row.find(
                "a", href=re.compile("crsedetail")
            )
            found.append(
                RunningRow(
                    AscCourse(
                        code=normalise_code(strip_variant(at(c_code))),
                        title=at(c_name),
                        credits=_floatish(at(c_cred)) if c_cred is not None else None,
                        slot=at(c_slot) or None,
                        instructor=at(c_inst) or None,
                        venue=at(c_venue) or None,
                        course_type=at(c_type) or None,
                        division=at(c_div) or None,
                        status="other",
                        semester=semester,
                    ),
                    html_lib.unescape(str(link["href"])) if link else None,
                )
            )
        if found and (best is None or len(found) > best[0]):
            best = (len(found), found)
    return best[1] if best else []


# --- crsedetail.jsp / newallCourse.jsp / Prereq: needs_human_review (layouts not mapped) ---


def parse_label_values(html: str) -> dict[str, str]:
    """Tolerant 'Label: value' extraction: 2- and 4-cell table rows, and 'Label: value' lines."""
    out: dict[str, str] = {}
    s = soup(html)
    for tag in s(["script", "style"]):
        tag.decompose()
    for table in s.find_all("table"):
        for row in _rows(table):
            cells = _cells(row)
            if len(cells) in (2, 4):
                for i in range(0, len(cells), 2):
                    label = _text(cells[i]).rstrip(":").strip()
                    value = _text(cells[i + 1])
                    if label and value and len(label) <= 60 and not _CODE_FULL.match(label):
                        out.setdefault(label.casefold(), value)
    for line in s.get_text("\n").split("\n"):
        m = re.match(r"^\s*([A-Za-z][A-Za-z /()\-]{2,50}?)\s*:\s*(\S.*)$", line)
        if m:
            out.setdefault(m[1].strip().casefold(), squash(m[2]))
    return out


def _pick(values: dict[str, str], *needles: str) -> str:
    for label, value in values.items():
        if any(n in label for n in needles):
            return value
    return ""


def parse_course_detail(html: str, code: str) -> AscCourseDetail:
    values = parse_label_values(html)
    used: set[str] = set()

    def take(*needles: str) -> str:
        for label, value in values.items():
            if any(n in label for n in needles):
                used.add(label)
                return value
        return ""

    title = take("course name", "course title", "title")
    credits = _floatish(take("credit"))
    department = take("department")
    prereq_text = take("prereq")
    syllabus = take("syllabus", "course content", "contents")
    extra = {
        k: v[:300]
        for k, v in values.items()
        if k not in used and not re.search(r"roll|name of student|cpi|spi|grade", k)
    }
    return AscCourseDetail(
        code=normalise_code(code),
        title=title,
        credits=credits,
        department=department,
        prerequisites=[normalise_code(c) for c in CODE_RE.findall(prereq_text)],
        syllabus=syllabus[:3000],
        extra=dict(list(extra.items())[:15]),
    )


def parse_prerequisites(html: str, code: str) -> list[str]:
    """Prerequisite codes for `code` from a Prereq page: a table row starting with the code, or
    a 'prerequisite' label: value pair."""
    target = normalise_code(code)
    for table in soup(html).find_all("table"):
        for row in _rows(table):
            texts = [_text(c) for c in _cells(row)]
            if texts and normalise_code(texts[0]) == target:
                codes = [normalise_code(c) for t in texts[1:] for c in CODE_RE.findall(t)]
                return [c for c in dict.fromkeys(codes) if c != target]
    values = parse_label_values(html)
    return [normalise_code(c) for c in CODE_RE.findall(_pick(values, "prereq"))]


def parse_syllabus(html: str, code: str) -> str:
    """The syllabus text of `code` as far as a tolerant reading finds it (trimmed)."""
    values = parse_label_values(html)
    text = _pick(values, "syllabus", "course content", "contents")
    if not text:
        s = soup(html)
        for tag in s(["script", "style"]):
            tag.decompose()
        body = squash(s.get_text(" "))
        text = body if normalise_code(code) in normalise_code_text(body) else ""
    return text[:3000]


def normalise_code_text(text: str) -> str:
    return CODE_RE.sub(lambda m: normalise_code(m[1]), text)


# ---------------------------------------------------------------- fee status
# needs_human_review: the fee page was never seen. Only status / amount-due rows are read; any
# table or section that mentions bank, account, IFSC or a scholarship application is skipped.


def _section_text(table: Tag) -> str:
    parts = [table.get_text(" ")]
    for sib in table.previous_siblings:
        if isinstance(sib, Tag):
            if sib.name == "table":
                break
            parts.append(sib.get_text(" "))
        else:
            parts.append(str(sib))
        if len(parts) > 4:
            break
    return squash(" ".join(parts))


def parse_fee_status(html: str) -> list[AscFeeItem]:
    items: list[AscFeeItem] = []
    for table in soup(html).find_all("table"):
        if table.find("table") is not None:
            continue  # a layout wrapper; its inner tables are visited on their own
        if _BAD_SECTION.search(_section_text(table)):
            continue
        rows = _rows(table)
        header_i = next(
            (
                i
                for i, r in enumerate(rows)
                if any(
                    re.search(r"amount|due|status|payable|balance", _text(c), re.I)
                    for c in _cells(r)
                )
                and not any(
                    _floatish(_text(c)) is not None and re.search(r"\d{2,}", _text(c))
                    for c in _cells(r)
                )
            ),
            None,
        )
        if header_i is not None:
            heads = [_text(c).casefold() for c in _cells(rows[header_i])]

            def find(*needles: str, heads: list[str] = heads) -> int | None:
                return next((k for k, h in enumerate(heads) if any(n in h for n in needles)), None)

            c_amt = find("amount", "payable", "balance", "due amount")
            c_date = find("due date", "last date", "date")
            c_stat = find("status")
            c_label = next((k for k in range(len(heads)) if k not in (c_amt, c_date, c_stat)), None)
            for row in rows[header_i + 1 :]:
                t = [_text(c) for c in _cells(row)]

                def at(i: int | None, t: list[str] = t) -> str:
                    return t[i] if i is not None and i < len(t) else ""

                label = at(c_label)
                if not label or _BAD_SECTION.search(label):
                    continue
                items.append(
                    AscFeeItem(
                        label=label,
                        amount=at(c_amt) or None,
                        due_date=at(c_date) or None,
                        status=at(c_stat) or None,
                    )
                )
        else:
            for row in rows:  # no header: 'label | value' rows
                t = [_text(c) for c in _cells(row)]
                if len(t) == 2 and t[0] and t[1] and not _BAD_SECTION.search(t[0]):
                    is_amount = bool(re.search(r"\d", t[1]))
                    items.append(
                        AscFeeItem(
                            label=t[0].rstrip(":"),
                            amount=t[1] if is_amount else None,
                            status=None if is_amount else t[1],
                        )
                    )
    return items
