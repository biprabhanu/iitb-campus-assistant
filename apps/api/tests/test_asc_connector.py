"""ASC connector tests: fake ASC server (httpx.MockTransport), no network."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from campuspilot import asc as asc_pkg
from campuspilot.asc import client, credentials, pages, tools
from campuspilot.asc.demo import DemoPortal, fixture
from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.schemas.connectors import (
    AscCourseDetailsInput,
    AscCourseHistoryInput,
    AscCurrentCoursesInput,
    AscFeeStatusInput,
    AscMyTimetableInput,
    AscOfferedCoursesInput,
    AscProfileInput,
    AscRegistrationStatusInput,
    ConnectorLoginRequest,
    ConnectorOtpRequest,
)

USER, PASSWORD = "fakeuser", "fake-password-123"
PERSONAL_BITS = (
    "TOKEN_",
    "00X000000",
    "Test Student",
    "Example Advisor",
    "22222",
    "11111",
    PASSWORD,
    "8.76",
    "8.91",
)


@pytest.fixture(autouse=True)
def clean_state():
    asc_pkg.reset_state()
    client.TRANSPORT = None
    yield
    asc_pkg.reset_state()
    client.TRANSPORT = None


@pytest.fixture
def portal() -> DemoPortal:
    fake = DemoPortal(expect=(USER, PASSWORD))
    client.TRANSPORT = fake.transport()
    return fake


def saved_login() -> None:
    credentials.save(USER, PASSWORD)


# ---------- login ----------


async def test_login_stores_keychain_only_after_success(portal) -> None:
    with pytest.raises(ConnectorError) as err:
        await asc_pkg.asc_login(ConnectorLoginRequest(username=USER, password="wrong"))
    assert err.value.code == "auth_failed"
    assert err.value.message == "ASC rejected the LDAP id or password."
    assert credentials.load() is None
    status = await asc_pkg.asc_login(
        ConnectorLoginRequest(username=f"  {USER}@iitb.ac.in ", password=PASSWORD)
    )
    assert status.state == "connected" and status.account == USER
    assert status.refreshed_at is not None
    assert credentials.load() == (USER, PASSWORD)
    # POST went to the login form with the right field names, and nowhere else.
    assert portal.posted == [
        {"UserName": USER, "UserPassword": "wrong"},
        {"UserName": USER, "UserPassword": PASSWORD},
    ]


async def test_otp_is_invalid_and_logout_clears(portal) -> None:
    with pytest.raises(ConnectorError) as err:
        await asc_pkg.asc_submit_otp(ConnectorOtpRequest(challenge_id="x", code="123456"))
    assert err.value.code == "otp_invalid"
    await asc_pkg.asc_login(ConnectorLoginRequest(username=USER, password=PASSWORD))
    status = asc_pkg.asc_logout()
    assert status.state == "not_connected" and credentials.load() is None
    for _ in range(5):
        await __import__("asyncio").sleep(0)
    assert portal.count("index.jsp") == 1 and not portal.logged_in


async def test_unreachable_message() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-host-detail")

    client.TRANSPORT = httpx.MockTransport(boom)
    with pytest.raises(ConnectorError) as err:
        await asc_pkg.asc_login(ConnectorLoginRequest(username=USER, password=PASSWORD))
    assert err.value.code == "unreachable"
    assert err.value.message == "ASC needs the campus network or IITB VPN."
    assert "asc.iitb" not in repr(err.value) and "secret-host" not in repr(err.value)


async def test_not_connected_without_login(portal) -> None:
    with pytest.raises(ConnectorError) as err:
        await asc_pkg.asc_my_timetable(AscMyTimetableInput())
    assert err.value.code == "not_connected"


# ---------- personal tools over the snapshot ----------


async def test_snapshot_tools(portal) -> None:
    saved_login()
    tt = await asc_pkg.asc_my_timetable(AscMyTimetableInput(day="Mon"))
    assert [s.course_code for s in tt.slots] == ["IE 624", "IE 603"]
    courses = await asc_pkg.asc_my_current_courses(AscCurrentCoursesInput())
    assert [c.code for c in courses.courses] == ["IE 624", "IE 603", "HS 101"]
    assert courses.semester == "2026-27 Autumn"
    profile = await asc_pkg.asc_profile(AscProfileInput())
    assert profile.profile.program == "M.Tech."
    fees = await asc_pkg.asc_fee_status(AscFeeStatusInput())
    assert [f.status for f in fees.items] == ["Paid", "Due"]
    reg = await asc_pkg.asc_registration_status(AscRegistrationStatusInput())
    assert reg.window_open is False and reg.note.startswith("The registration window is not open")
    assert [c.code for c in reg.courses] == ["IE 624", "IE 603", "HS 101"]
    # One snapshot: the record page was read once, however many tools ran.
    assert portal.count("AcademicRecord.jsp") == 2  # record + the registration redirect target
    assert portal.count("VenueOccupancy.jsp") == 1


async def test_registration_window_open(portal) -> None:
    portal.registration_open = True
    saved_login()
    reg = await asc_pkg.asc_registration_status(AscRegistrationStatusInput())
    assert reg.window_open is True and reg.note == ""
    assert [c.status for c in reg.courses] == ["registered", "approved", "pending"]
    assert portal.count("AcademicRecord.jsp") == 1


async def test_today_and_tomorrow_set_dates(portal) -> None:
    saved_login()
    out = await asc_pkg.asc_my_timetable(AscMyTimetableInput(day="tomorrow"))
    assert len(out.for_dates) == 1


async def test_snapshot_ttl_and_refresh(portal) -> None:
    saved_login()
    await asc_pkg.asc_my_timetable(AscMyTimetableInput())
    await asc_pkg.asc_my_current_courses(AscCurrentCoursesInput())
    assert portal.count("VenueOccupancy.jsp") == 1
    status = await asc_pkg.asc_refresh()
    assert portal.count("VenueOccupancy.jsp") == 2 and status.refreshed_at is not None
    tools._state.snapshot.fetched_at = datetime.now(UTC) - timedelta(
        seconds=get_settings().asc_snapshot_ttl_s + 5
    )
    await asc_pkg.asc_my_timetable(AscMyTimetableInput())
    assert portal.count("VenueOccupancy.jsp") == 3


async def test_one_page_failing_keeps_the_others(portal) -> None:
    portal.overrides["FeeStatus.jsp"] = httpx.Response(500, text="boom")
    saved_login()
    assert (await asc_pkg.asc_my_timetable(AscMyTimetableInput())).slots
    with pytest.raises(ConnectorError) as err:
        await asc_pkg.asc_fee_status(AscFeeStatusInput())
    assert err.value.code == "parse_failed"


# ---------- session expiry ----------


async def test_expiry_relogin_once_then_works(portal) -> None:
    saved_login()
    await asc_pkg.asc_my_timetable(AscMyTimetableInput())
    portal.expire()
    await asc_pkg.asc_refresh()
    assert len(portal.posted) == 2  # initial login + one re-login
    assert (await asc_pkg.asc_my_timetable(AscMyTimetableInput())).slots


async def test_expiry_twice_is_session_expired(portal) -> None:
    saved_login()
    await asc_pkg.asc_my_timetable(AscMyTimetableInput())
    portal.expire()
    # Logging in "works" but every data page still comes back as the login form.
    portal.overrides["VenueOccupancy.jsp"] = httpx.Response(
        200, text=fixture("login.html"), headers={"content-type": "text/html"}
    )
    with pytest.raises(ConnectorError) as err:
        await asc_pkg.asc_refresh()
    assert err.value.code == "session_expired"
    assert len(portal.posted) == 2  # logged in again exactly once


async def test_401_counts_as_expiry(portal) -> None:
    saved_login()
    await asc_pkg.asc_my_timetable(AscMyTimetableInput())
    portal.overrides["VenueOccupancy.jsp"] = httpx.Response(401)
    with pytest.raises(ConnectorError) as err:
        await asc_pkg.asc_refresh()
    assert err.value.code == "session_expired"


# ---------- allowlist ----------


async def _session(portal) -> client.AscSession:
    session = client.AscSession()
    await session.sign_in(USER, PASSWORD)
    return session


@pytest.mark.parametrize(
    "path",
    [
        "/academic/CourseRegistration/Student/CRFForm.jsp?TOKEN_REGADJ_1",
        "/academic/CourseRegistration/Student/WithdrawForm.jsp?TOKEN_WD_1",
        "/academic/fees/BankLetter.jsp?TOKEN_BANK_1",
        "/academic/fees/ConvoPay.jsp?TOKEN_CONVO_1",
        "/academic/feedback/Feedback.jsp?TOKEN_FB_1",
        "/academic/utility/Other.jsp",
    ],
)
async def test_forbidden_pages_are_refused(portal, path) -> None:
    session = await _session(portal)
    before = len(portal.calls)
    with pytest.raises(ConnectorError) as err:
        await session.get(path)
    assert err.value.code == "blocked" and len(portal.calls) == before


async def test_post_to_data_page_refused(portal) -> None:
    session = await _session(portal)
    for path in ("/academic/utility/AcademicRecord.jsp", "/academic/timetable/VenueOccupancy.jsp"):
        with pytest.raises(ConnectorError):
            await session.post(path, {"a": "b"})
    # the GO forms are allowed
    await session.post(pages.ALL_DEPT_PATH, {"year": "2026", "semester": "1"})


async def test_offsite_and_http_redirects_refused(portal) -> None:
    session = await _session(portal)
    for target in ("https://evil.example.com/x", "http://asc.iitb.ac.in/academic/Prereq"):
        portal.overrides["TTcheck.jsp"] = httpx.Response(302, headers={"location": target})
        with pytest.raises(ConnectorError) as err:
            await session.get("/academic/timetable/TTcheck.jsp")
        assert err.value.code == "blocked"
    # a redirect into a forbidden ASC page is refused as well
    portal.overrides["TTcheck.jsp"] = httpx.Response(
        302, headers={"location": "/academic/CourseRegistration/Student/CRFForm.jsp"}
    )
    with pytest.raises(ConnectorError):
        await session.get("/academic/timetable/TTcheck.jsp")


def test_menu_selection_ignores_forbidden_leaves() -> None:
    session = client.AscSession()
    session.set_menu(fixture("menu_signed_in.html"))
    assert set(session._links) == {
        "timetable", "record", "registration", "running", "syllabus", "prereq", "fees"
    }  # fmt: skip
    assert session.fee_pages == frozenset({"FeeStatus.jsp"})
    assert "TOKEN" not in repr(session)
    assert pages.label_forbidden("Pay Convo Fees") and pages.label_forbidden("Course Withdraw")
    assert not pages.label_forbidden("My Timetable")
    assert not pages.path_allowed("GET", "/academic/fees/FeeStatus.jsp")  # not without the menu


def test_fee_page_with_forbidden_word_is_not_mapped() -> None:
    session = client.AscSession()
    leaf = '{label:"Fees Status/Scholarship",href:"/academic/fees/PayFees.jsp?T"}'
    html = f"<script>var m=[{leaf}];</script>"
    session.set_menu(html)
    assert "fees" not in session._links


# ---------- never logged / no personal data on disk ----------


async def test_nothing_sensitive_is_logged(portal, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    saved_login()
    await asc_pkg.asc_login(ConnectorLoginRequest(username=USER, password=PASSWORD))
    await asc_pkg.asc_my_timetable(AscMyTimetableInput())
    await asc_pkg.asc_profile(AscProfileInput())
    await asc_pkg.asc_fee_status(AscFeeStatusInput())
    await asc_pkg.asc_offered_courses(
        AscOfferedCoursesInput(dept="IE", year=2026, semester="autumn")
    )
    text = "\n".join(r.getMessage() for r in caplog.records)
    for bit in PERSONAL_BITS:
        assert bit not in text, bit
    assert "asc.iitb.ac.in" not in text  # httpx URL records are dropped


async def test_no_personal_data_on_disk(portal, tmp_path) -> None:
    saved_login()
    await asc_pkg.asc_my_timetable(AscMyTimetableInput())
    await asc_pkg.asc_offered_courses(
        AscOfferedCoursesInput(dept="IE", year=2026, semester="autumn")
    )
    blob = ""
    for root, _, files in os.walk(tmp_path):
        for name in files:
            if name == "test.db":
                continue
            blob += Path(root, name).read_text(errors="ignore")
    for bit in PERSONAL_BITS:
        assert bit not in blob, bit
    assert "Fake Operations Research" in blob  # the public list is cached


async def test_no_grade_fields_in_tool_outputs(portal) -> None:
    saved_login()
    outs = [
        await asc_pkg.asc_profile(AscProfileInput()),
        await asc_pkg.asc_my_timetable(AscMyTimetableInput()),
        await asc_pkg.asc_my_current_courses(AscCurrentCoursesInput()),
        await asc_pkg.asc_registration_status(AscRegistrationStatusInput()),
        await asc_pkg.asc_fee_status(AscFeeStatusInput()),
    ]
    dump = json.dumps([o.model_dump(mode="json") for o in outs]).lower()
    for bad in ("grade", "spi", "cpi", "8.76", "8.91", '"ab"', '"bc"', "00x000000", "test student"):
        assert bad not in dump, bad


# ---------- public tools ----------


async def test_offered_courses_and_disk_cache(portal) -> None:
    saved_login()
    args = AscOfferedCoursesInput(dept="IE", year=2026, semester="autumn")
    out = await asc_pkg.asc_offered_courses(args)
    assert [c.code for c in out.courses] == ["IE 303", "IE 603", "IE 624"]
    assert out.courses[0].semester == "Autumn 2026"
    n = portal.count("RunningCourses.jsp")
    assert "deptcd=IE,IES" in "".join(portal.queries) and "semester=1" in "".join(portal.queries)
    await asc_pkg.asc_offered_courses(args)
    assert portal.count("RunningCourses.jsp") == n  # served from the 24 h disk cache
    cache = get_settings().asc_public_cache_dir.expanduser() / "asc" / "IE_2026_autumn.json"
    data = json.loads(cache.read_text())
    data["saved_at"] -= get_settings().asc_public_cache_ttl_s + 10
    cache.write_text(json.dumps(data))
    await asc_pkg.asc_offered_courses(args)
    assert portal.count("RunningCourses.jsp") == n + 1  # expired entry is refreshed


async def test_offering_history(portal) -> None:
    saved_login()
    out = await asc_pkg.asc_course_offering_history(AscCourseHistoryInput(course_code="ie303"))
    assert out.course_code == "IE 303" and out.title == "Fake Operations Research"
    assert len(out.offerings) == 6
    autumn = [o.year for o in out.offerings if o.semester == "autumn" and o.offered]
    spring = [o for o in out.offerings if o.semester == "spring" and o.offered]
    assert len(autumn) >= 2 and not spring
    year = tools.current_academic_year()
    if year >= 2027:  # the demo server publishes nothing after Autumn 2026
        assert "Not published yet" in out.note


async def test_course_details(portal) -> None:
    saved_login()
    out = await asc_pkg.asc_course_details(AscCourseDetailsInput(course_code="IE 303"))
    assert out.detail and out.detail.title == "Fake Operations Research"
    assert out.detail.prerequisites == ["MA 105", "IE 201"]
    assert "linear programming" in out.detail.syllabus
    missing = await asc_pkg.asc_course_details(AscCourseDetailsInput(course_code="ZZ 999"))
    assert missing.detail is not None or missing.note  # syllabus page may still answer


# ---------- demo mode and status ----------


async def test_demo_mode(monkeypatch) -> None:
    monkeypatch.setenv("CONNECTORS_DEMO", "true")
    get_settings.cache_clear()
    assert credentials.load() is None
    status = await asc_pkg.asc_status()
    assert status.demo and status.state == "connected"
    tt = await asc_pkg.asc_my_timetable(AscMyTimetableInput())
    assert tt.demo and tt.slots
    assert (await asc_pkg.asc_my_current_courses(AscCurrentCoursesInput())).demo
    assert (await asc_pkg.asc_fee_status(AscFeeStatusInput())).demo
    offered = await asc_pkg.asc_offered_courses(
        AscOfferedCoursesInput(dept="IE", year=2026, semester="autumn")
    )
    assert offered.demo and offered.courses
    assert credentials.load() is None  # demo never touches the Keychain


async def test_status_states(portal) -> None:
    assert (await asc_pkg.asc_status()).state == "not_connected"
    saved_login()
    assert (await asc_pkg.asc_status()).state == "connected"
    portal.expire()
    portal.overrides["menu.jsp"] = httpx.Response(200, text=fixture("menu_signed_out.html"))
    with pytest.raises(ConnectorError):
        await asc_pkg.asc_refresh()
    assert (await asc_pkg.asc_status()).state == "error"
