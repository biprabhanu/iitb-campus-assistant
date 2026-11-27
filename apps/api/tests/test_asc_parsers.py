"""ASC parser tests over the synthetic fixtures (no network)."""

from __future__ import annotations

import json

from campuspilot.asc import pages, parsers
from campuspilot.asc.demo import fixture

SENTINELS = ("8.76", "8.91", "AB", "BC", "AA", "BB")


def test_frameset_and_login_form() -> None:
    frames = parsers.parse_frameset(fixture("frameset.html"))
    assert frames["rightPage"] == "WebPages/Login.jsp" and frames["leftPage"] == "menu.jsp"
    form = parsers.parse_login_form(fixture("login.html"))
    assert form and form.action == "ldaplogin.jsp"
    assert (form.user_field, form.password_field) == ("UserName", "UserPassword")
    assert parsers.looks_like_login_page(fixture("login.html"))


def test_menu_tolerant_to_key_order_and_quotes() -> None:
    links = {m.label: m.href for m in parsers.parse_menu(fixture("menu_signed_in.html"))}
    assert links["Running Courses"].endswith("TOKEN_RUN_1")
    assert links["Bulletin Report"].endswith("TOKEN_BULL_1")  # href first, single quotes
    assert links["Course Syllabus"].endswith("TOKEN_SYL_1")  # quoted keys
    assert links["My Timetable"].endswith("TOKEN_TT_1")
    assert "TOKEN" not in repr(parsers.parse_menu(fixture("menu_signed_in.html")))
    assert parsers.menu_signed_in(fixture("menu_signed_in.html"))
    assert not parsers.menu_signed_in(fixture("menu_signed_out.html"))
    plain = '<ul><li><a href="/academic/Prereq?T9">Course Prerequisites</a></li></ul>'
    assert parsers.parse_menu(plain)[0].label == "Course Prerequisites"


def test_timetable_grid() -> None:
    slots = parsers.parse_timetable(fixture("timetable.html"))
    mon = [s for s in slots if s.day == "Mon"]
    assert {(s.course_code, s.start, s.end) for s in mon} == {
        ("IE 624", "09:30", "10:55"),
        ("IE 603", "11:05", "12:30"),
    }
    assert mon[0].venue == "LC 001" and mon[0].instructor == "Prof. Alpha Example"
    tue_tut = [s for s in slots if s.day == "Tue" and s.start == "14:00"]
    assert {s.course_code for s in tue_tut} == {"IE 624", "IE 603"}  # two entries in one cell
    assert {s.kind for s in tue_tut} == {"tutorial"}
    assert [s for s in slots if s.course_code == "IE 699"][0].kind == "lab"
    assert not [s for s in slots if s.day == "Thu"]
    assert "00X000000" not in json.dumps([s.model_dump() for s in slots])


def test_academic_record_profile_and_current_semester() -> None:
    record = parsers.parse_academic_record(fixture("academic_record.html"))
    p = record.profile
    assert p.department.startswith("Industrial") and p.program == "M.Tech." and p.status
    assert p.validity == "2028-07-31" and p.advisors[0] == "Prof. Example Advisor"
    assert len(record.semesters) == 3
    current = record.current
    assert current and current.name == "2026-27 Autumn"
    assert [c.code for c in current.courses] == ["IE 624", "IE 603", "HS 101"]
    assert current.courses[2].status == "audit" and current.courses[0].credits == 6.0


def test_no_grades_in_any_parser_output() -> None:
    record = parsers.parse_academic_record(fixture("academic_record.html"))
    dump = json.dumps(
        {
            "profile": record.profile.model_dump(),
            "semesters": [
                [c.model_dump() for c in s.courses] + [s.name, s.all_grades_empty]
                for s in record.semesters
            ],
        }
    )
    for bad in (*SENTINELS, "00X000000", "Test Student"):
        assert bad not in dump, bad
    for model in (parsers.AscProfile, parsers.AscCourse):
        assert not [f for f in model.model_fields if f in ("grade", "spi", "cpi", "gpa")]
    assert "grade" not in dump.lower() and "spi" not in dump.lower() and "cpi" not in dump.lower()


def test_registration_status_table() -> None:
    courses = parsers.parse_registration_status(fixture("registration_status.html"))
    assert [(c.code, c.status) for c in courses] == [
        ("IE 624", "registered"),
        ("IE 603", "approved"),
        ("HS 101", "pending"),
    ]


def test_all_dept_and_running_courses() -> None:
    mapping = parsers.parse_all_dept(fixture("all_dept.html"))
    assert mapping["IE"] == "IE,IES" and mapping["IES"] == "IE,IES" and mapping["HS"] == "HS"
    rows = parsers.parse_running_courses(fixture("running_autumn.html"), "Autumn 2026")
    assert [r.course.code for r in rows] == ["IE 303", "IE 603", "IE 624"]
    first = rows[0]
    assert first.course.instructor == "Prof. Alpha Example" and first.course.slot == "1"
    assert (
        first.course.course_type == "Core"
        and first.detail_href
        and "crsedetail" in first.detail_href
    )
    assert parsers.parse_running_courses(fixture("running_empty.html")) == []


def test_course_detail_live_layout() -> None:
    detail = parsers.parse_course_detail(fixture("crsedetail.html"), "IE 303")
    assert detail.title == "Fake Operations Research" and detail.credits == 6.0
    assert detail.prerequisites == []  # the Prerequisite row is commented out in the live page
    assert "linear programming" in detail.syllabus and "network flows" in detail.syllabus
    assert "this line has a colon" in detail.syllabus
    assert (
        detail.extra.get("type") == "Theory"
        and "invented author" in detail.extra["text reference"].casefold()
    )
    assert "students will formulate and solve small problems" not in detail.extra  # no line noise


def test_prerequisites_live_table() -> None:
    html = fixture("prereq.html")
    assert parsers.parse_prerequisites(html, "IE 303") == ["MA 105 OR IE 201"]
    # one rule per program group: both rows are kept, equivalent-type rows are not prerequisites
    assert parsers.parse_prerequisites(html, "ie603") == ["IE 303", "IE 303 OR IE 304"]
    assert parsers.parse_prerequisites(html, "IE 624") == []
    assert parsers.parse_prerequisites(html, "IE 650") == []
    assert parsers.parse_prerequisites(html, "ZZ 999") == []


def test_syllabus_page_is_only_a_department_picker() -> None:
    html = fixture("newall_course.html")
    assert "openIt(" in html and "allCourse.jsp" in html  # no syllabus text, a POST form
    assert not pages.path_allowed("POST", "/academic/CourseRegistration/Common/allCourse.jsp")
    assert not pages.path_allowed("GET", "/academic/CourseRegistration/Common/allCourse.jsp")


def test_academic_standing_in_a_mis_nested_cell() -> None:
    assert (
        parsers.parse_academic_record(fixture("academic_record.html")).profile.academic_standing
        == "1"
    )
    # the value is not paired with its label: the first non-empty cell after the label is used
    odd = "<table><tr><th>Academic Standing (<a>rules</a>)</th><td></td><td> 2 </td></tr></table>"
    assert parsers.parse_academic_record(odd).profile.academic_standing == "2"
    assert parsers.parse_academic_record("<table></table>").profile.academic_standing == ""


def test_fee_status_skips_bank_details() -> None:
    items = parsers.parse_fee_status(fixture("fee_status.html"))
    assert [(i.label, i.status) for i in items] == [
        ("Tuition fee 2026-27 Autumn", "Paid"),
        ("Hostel fee 2026-27 Autumn", "Due"),
    ]
    assert items[1].amount == "Rs. 22222" and items[1].due_date == "2026-08-10"
    dump = json.dumps([i.model_dump() for i in items])
    for bad in ("9999000011112222", "FAKE0000001", "Test Student"):
        assert bad not in dump


def test_menu_reads_anchors_inside_js_strings() -> None:
    """The live menu (27 Nov 2026) builds leaves as <a> tags inside buildChild("...") strings."""
    from campuspilot.asc.parsers import parse_menu

    html = (
        "<script>var N1 = buildChild(N0,\"<a id='1_2_3' href='/academic/timetable/"
        "VenueOccupancy.jsp?FAKETOKEN1' title='Timetable view'"
        " onclick='javascript:loadframe(1,2,3);'"
        ' target=rightPage >My Timetable</a>",false);'
        "var N2 = buildChild(N0,\"<a id='1_2_4' href='/academic/utility/allDept.jsp?FAKETOKEN2'"
        ' target=rightPage >Running Courses</a>",false);</script>'
        '<a href="index.jsp?logout=yes">Sign out</a>'
    )
    links = {link.label: link.href for link in parse_menu(html)}
    assert links["My Timetable"].endswith("VenueOccupancy.jsp?FAKETOKEN1")
    assert links["Running Courses"].endswith("allDept.jsp?FAKETOKEN2")


def test_real_layout_details() -> None:
    """Quirks seen on the live pages (27 Nov 2026): times without ':00', section tags in codes,
    4-digit codes, and an 'Instructor Status' column before 'Instructor(s)'."""
    slots = parsers.parse_timetable(fixture("timetable.html"))
    tue = [s for s in slots if s.day == "Tue" and s.course_code == "IE 624"]
    assert (tue[0].start, tue[0].end) == ("14:00", "15:25")
    assert [s for s in slots if s.course_code == "IE 699"][0].end == "16:55"
    record = parsers.parse_academic_record(fixture("academic_record.html"))
    assert record.current is not None
    assert [c.code for c in record.current.courses] == ["IE 624", "IE 603", "HS 101"]
    assert any(c.code == "DE 5001" for s in record.semesters for c in s.courses)
    assert any(c.code == "IE 511" for s in record.semesters for c in s.courses)
    p = record.profile  # identity block and advisor row are different tables
    assert p.department and p.program == "M.Tech." and p.status == "Active" and p.advisors
    assert parsers.strip_variant("IE 603 (S1)") == "IE 603"


def test_fee_month_picker_gives_no_rows_and_only_two_misec_pages_are_allowed() -> None:
    from campuspilot.asc import pages

    picker = (
        "<table><tr><td>Scholarship Paid Details</td></tr><tr><td>Select Month/Year:</td>"
        "<td><select name='m'><option>Status</option></select></td></tr></table>"
    )
    assert parsers.parse_fee_status(picker) == []
    host = "asc.iitb.ac.in"
    for path in ("/misec/scholarship/Intermediate.jsp", "/misec/scholarship/scholpaid.jsp"):
        assert pages.request_allowed("GET", f"https://{host}{path}?x=1", host)
        assert not pages.request_allowed("POST", f"https://{host}{path}", host)
    assert not pages.request_allowed("GET", f"https://{host}/misec/scholarship/apply.jsp", host)
    assert not pages.request_allowed("GET", f"https://{host}/misec/other.jsp", host)


def test_live_slot_cell_gives_slot_and_room() -> None:
    assert parsers._slot_name("4 Mon-4A-11:35:00-12:30:00- Thu-4C-09:30:00-10:25:00-") == "4"
    cell = "1 Mon-1A-08:30:00-09:25:00-Class Room : LT 001 Thu-1C-Class Room : LT 001"
    assert parsers._slot_venue(cell) == "LT 001"
    assert parsers._slot_venue("FullSemester") is None
