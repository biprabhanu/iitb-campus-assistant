"""ASC page parsers on synthetic fixtures: column order, statuses, times, broken pages."""

from __future__ import annotations

import pytest

from campuspilot.asc import parsers
from campuspilot.connectors.errors import ConnectorError
from tests.asc_helpers import fixture


def test_courses_basic() -> None:
    courses, semester, note = parsers.parse_courses(fixture("courses.html"))
    assert [c.code for c in courses] == ["XX 101", "XX 202", "XX 303"]
    assert [c.status for c in courses] == ["registered", "pending", "dropped"]
    first = courses[0]
    assert (first.title, first.credits, first.slot) == ("Fake Systems", 6.0, "1")
    assert first.instructor == "Prof. A. Example"
    assert semester == "2026-27 Autumn" == first.semester
    assert "open until 4 Dec" in note


def test_courses_column_order_and_extra_columns() -> None:
    courses, semester, note = parsers.parse_courses(fixture("courses_reordered.html"))
    assert [(c.code, c.title, c.credits, c.status) for c in courses] == [
        ("XX 101", "Fake Systems", 6.0, "approved"),
        ("XX 202", "Imaginary Methods", None, "audit"),
    ]
    assert (semester, note) == ("", "")  # nothing on the page says, so nothing is invented


def test_courses_broken_page_is_parse_failed() -> None:
    with pytest.raises(ConnectorError) as err:
        parsers.parse_courses(fixture("broken.html"))
    assert err.value.code == "parse_failed"
    assert "Maintenance" not in err.value.message  # page text never goes into errors


def test_courses_empty_page_is_empty_not_error() -> None:
    courses, _, _ = parsers.parse_courses("<html><body><p>No courses found.</p></body></html>")
    assert courses == []


def test_timetable_rows() -> None:
    slots, note = parsers.parse_timetable(fixture("timetable.html"))
    assert note == ""
    by_code_day = {(s.course_code, s.day): s for s in slots}
    wed = by_code_day[("XX 202", "Wed")]
    assert (wed.start, wed.end, wed.venue, wed.slot, wed.kind) == (
        "11:30",
        "12:25",
        "LT 101",
        "3",
        "lecture",
    )
    lab = by_code_day[("XX 303", "Mon")]
    assert (lab.start, lab.end, lab.kind) == ("14:00", "17:00", "lab")  # 2:00 PM -> 14:00
    assert by_code_day[("XX 101", "Thu")].kind == "tutorial"


def test_timetable_slot_codes_only_gives_note_and_no_invented_times() -> None:
    slots, note = parsers.parse_timetable(fixture("timetable_slots_only.html"))
    assert slots == []
    assert "slot codes" in note


def test_timetable_ambiguous_time_is_skipped() -> None:
    html = (
        "<table><tr><th>Day</th><th>Time</th><th>Course Code</th></tr>"
        "<tr><td>Mon</td><td>2:00 - 5:00 PM</td><td>XX 1</td></tr>"
        "<tr><td>Tue</td><td>09:00 - 10:00</td><td>XX 2</td></tr></table>"
    )
    slots, _ = parsers.parse_timetable(html)
    assert [s.course_code for s in slots] == ["XX 2"]


def test_timetable_broken_page() -> None:
    with pytest.raises(ConnectorError) as err:
        parsers.parse_timetable(fixture("broken.html"))
    assert err.value.code == "parse_failed"


def test_grades_with_spi_cpi_as_shown() -> None:
    grades, spi, cpi = parsers.parse_grades(fixture("grades.html"))
    assert [(g.course_code, g.grade, g.credits) for g in grades] == [
        ("XX 099", "AA", 6.0),
        ("XX 098", "BB", 3.0),
    ]
    assert grades[0].semester == "2025-26 Spring"
    assert (spi, cpi) == ("9.00", "8.75")  # strings, trailing zero kept


def test_grades_several_spis_are_not_guessed() -> None:
    html = fixture("grades.html") + "<p>SPI: 7.50</p>"
    _, spi, cpi = parsers.parse_grades(html)
    assert spi is None
    assert cpi == "8.75"


def test_grades_broken_page() -> None:
    with pytest.raises(ConnectorError) as err:
        parsers.parse_grades(fixture("broken.html"))
    assert err.value.code == "parse_failed"
