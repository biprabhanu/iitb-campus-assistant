"""ASC tools: reading pages, session expiry, cache, one-at-a-time, demo mode, not connected."""

# ruff: noqa: F401, F811 (fixtures imported from asc_helpers are used as test arguments)

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import keyring
import pytest

from campuspilot import asc, config
from campuspilot.asc import credentials, tools
from campuspilot.schemas.connectors import (
    ConnectorLoginRequest,
    GetMyGradesInput,
    GetMyRegisteredCoursesInput,
    GetMyTimetableInput,
)
from tests.asc_helpers import PASSWORD, USER, FakePortal, clean_asc_state, fixture, portal

MONDAY = date(2026, 11, 23)  # a Monday; the fixture has XX 101 08:30 and XX 303 14:00 that day


@pytest.fixture
def today_monday(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "_today", lambda: MONDAY)


async def login() -> None:
    await asc.asc_login(ConnectorLoginRequest(username=USER, password=PASSWORD))


def set_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()


async def test_not_connected_raises_friendly_error() -> None:
    for call, args in (
        (asc.get_my_timetable, GetMyTimetableInput()),
        (asc.get_my_registered_courses, GetMyRegisteredCoursesInput()),
        (asc.get_my_grades, GetMyGradesInput()),
    ):
        with pytest.raises(asc.ConnectorError) as err:
            await call(args)
        assert (err.value.code, err.value.message) == (
            "not_connected",
            "Connect ASC in Settings first.",
        )
    assert (await asc.asc_status()).state == "not_connected"


async def test_timetable_today_and_tomorrow(portal: FakePortal, today_monday) -> None:
    await login()
    today = await asc.get_my_timetable(GetMyTimetableInput())
    assert today.for_dates == [MONDAY] and today.demo is False
    assert [(s.start, s.course_code) for s in today.slots] == [
        ("08:30", "XX 101"),
        ("14:00", "XX 303"),
    ]
    tomorrow = await asc.get_my_timetable(GetMyTimetableInput(when="tomorrow"))
    assert tomorrow.slots == [] and "No classes" in tomorrow.note
    wed = await asc.get_my_timetable(GetMyTimetableInput(on_date=date(2026, 11, 25)))
    assert [s.course_code for s in wed.slots] == ["XX 202"]


async def test_timetable_this_week_sorted_by_day_then_start(
    portal: FakePortal, today_monday
) -> None:
    await login()
    week = await asc.get_my_timetable(GetMyTimetableInput(when="this_week"))
    assert len(week.for_dates) == 7 and week.for_dates[0] == MONDAY
    assert [(s.day, s.start) for s in week.slots] == [
        ("Mon", "08:30"),
        ("Mon", "14:00"),
        ("Wed", "11:30"),
        ("Thu", "08:30"),
    ]


async def test_timetable_without_times_returns_note_not_invented_times(
    portal: FakePortal, today_monday
) -> None:
    portal.pages["/timetable"] = fixture("timetable_slots_only.html")
    await login()
    out = await asc.get_my_timetable(GetMyTimetableInput())
    assert out.slots == [] and "slot codes" in out.note


async def test_courses_and_grades(portal: FakePortal) -> None:
    await login()
    courses = await asc.get_my_registered_courses(GetMyRegisteredCoursesInput())
    assert [c.code for c in courses.courses] == ["XX 101", "XX 202", "XX 303"]
    assert courses.semester == "2026-27 Autumn" and "open until 4 Dec" in courses.registration_note
    none = await asc.get_my_registered_courses(GetMyRegisteredCoursesInput(semester="2020"))
    assert none.courses == [] and none.note
    grades = await asc.get_my_grades(GetMyGradesInput())
    assert (grades.spi, grades.cpi, len(grades.grades)) == ("9.00", "8.75", 2)


async def test_broken_page_is_parse_failed(portal: FakePortal) -> None:
    portal.pages["/grades"] = fixture("broken.html")
    await login()
    with pytest.raises(asc.ConnectorError) as err:
        await asc.get_my_grades(GetMyGradesInput())
    assert err.value.code == "parse_failed"


async def test_session_expired_relogs_in_silently(portal: FakePortal) -> None:
    await login()
    assert portal.count("POST", "/login") == 1
    portal.expire()  # ASC forgets the session; next read is bounced to the SSO login page
    out = await asc.get_my_registered_courses(GetMyRegisteredCoursesInput())
    assert len(out.courses) == 3
    assert portal.count("POST", "/login") == 2  # one silent re-login with Keychain credentials


async def test_session_expired_and_credentials_no_longer_work(portal: FakePortal) -> None:
    await login()
    portal.expire()
    keyring.set_password("campuspilot", "asc_password", "changed-elsewhere")
    with pytest.raises(asc.ConnectorError) as err:
        await asc.get_my_registered_courses(GetMyRegisteredCoursesInput())
    assert err.value.code == "session_expired"
    assert "changed-elsewhere" not in err.value.message


async def test_session_expired_with_otp_needed(portal: FakePortal) -> None:
    await login()
    portal.expire()
    portal.mode = "otp"
    with pytest.raises(asc.ConnectorError) as err:
        await asc.get_my_grades(GetMyGradesInput())
    assert err.value.code == "session_expired"


async def test_no_session_in_memory_but_keychain_logs_in_on_first_read(portal: FakePortal) -> None:
    credentials.save(USER, PASSWORD)  # e.g. after an app restart
    out = await asc.get_my_grades(GetMyGradesInput())
    assert len(out.grades) == 2


async def test_pages_are_cached(portal: FakePortal) -> None:
    await login()
    for _ in range(3):
        await asc.get_my_registered_courses(GetMyRegisteredCoursesInput())
    assert portal.count("GET", "/courses") == 1


async def test_cache_can_be_turned_off(portal: FakePortal, monkeypatch) -> None:
    set_env(monkeypatch, ASC_CACHE_TTL_S="0")
    await login()
    for _ in range(2):
        await asc.get_my_registered_courses(GetMyRegisteredCoursesInput())
    assert portal.count("GET", "/courses") == 2


async def test_one_request_at_a_time(respx_mock, monkeypatch) -> None:
    set_env(monkeypatch, ASC_CACHE_TTL_S="0")
    fake = FakePortal()
    active = peak = 0

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return fake.handle(request)

    respx_mock.route().mock(side_effect=slow)
    await login()
    await asyncio.gather(
        *(asc.get_my_registered_courses(GetMyRegisteredCoursesInput()) for _ in range(4)),
        asc.get_my_grades(GetMyGradesInput()),
    )
    assert peak == 1


async def test_only_get_requests_while_reading(portal: FakePortal) -> None:
    await login()
    posts = portal.count("POST", "")
    await asc.get_my_timetable(GetMyTimetableInput())
    await asc.get_my_registered_courses(GetMyRegisteredCoursesInput())
    await asc.get_my_grades(GetMyGradesInput())
    assert portal.count("POST", "") == posts


async def test_demo_mode_uses_fixtures_without_network(
    respx_mock, monkeypatch, today_monday
) -> None:
    set_env(monkeypatch, CONNECTORS_DEMO="true")  # respx_mock has no routes: any request fails
    status = await asc.asc_status()
    assert (status.state, status.demo) == ("connected", True)
    assert (await asc.get_my_timetable(GetMyTimetableInput())).demo is True
    courses = await asc.get_my_registered_courses(GetMyRegisteredCoursesInput())
    assert courses.demo and len(courses.courses) == 3
    grades = await asc.get_my_grades(GetMyGradesInput())
    assert grades.demo and grades.cpi == "8.75"
    assert (await asc.asc_login(ConnectorLoginRequest(username="x", password="y"))).demo is True
    assert credentials.load() is None  # demo never touches the Keychain
