"""Tools, source resolution, demo mode, iCal mode and credential handling."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import keyring
import pytest
import respx

from campuspilot.config import REPO_ROOT, get_settings
from campuspilot.moodle import client as client_module
from campuspilot.moodle import ical as ical_module
from campuspilot.moodle.ical import parse_ics
from campuspilot.moodle.tools import (
    MoodleError,
    delete_credentials,
    get_course_contents,
    get_my_deadlines,
    list_my_courses,
    moodle_status,
    resolve_source,
    save_credentials,
)
from campuspilot.schemas.chat import MoodleTokenRequest
from campuspilot.schemas.tools import (
    GetCourseContentsInput,
    GetMyDeadlinesInput,
    ListMyCoursesInput,
)
from tests.moodle_helpers import (
    BASE,
    COURSES,
    FAKE_ICAL_URL,
    FAKE_TOKEN,
    REST_URL,
    SITE_INFO,
    assignments_payload,
    events_payload,
    ics_text,
    mock_rest,
)

ACTIVE_URL = f"{BASE}/mod/assign/view.php?id=901"


@pytest.fixture(autouse=True)
def _fresh_caches():
    client_module.clear_cache()
    ical_module.clear_cache()
    yield
    client_module.clear_cache()
    ical_module.clear_cache()


def _use_env(monkeypatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


REST_PAYLOADS = {
    "core_webservice_get_site_info": SITE_INFO,
    "core_enrol_get_users_courses": COURSES,
    "mod_assign_get_assignments": assignments_payload(
        [("Report", 1, 20), ("Later work", 2, 24 * 10)]
    ),
    "core_calendar_get_action_events_by_timesort": events_payload(
        [
            ("Report is due", 7, 20, "IE624", ACTIVE_URL),  # duplicate of the assignment
            ("Quiz 1 closes", 8, 48, "HS101", f"{BASE}/mod/quiz/view.php?id=5"),
        ]
    ),
    "core_course_get_contents": [
        {
            "name": "Week 1",
            "modules": [{"name": "Slides", "modname": "resource", "url": f"{BASE}/x"}],
        }
    ],
}


# ---------- demo mode ----------


async def test_demo_mode_when_unconfigured():
    out = await get_my_deadlines(GetMyDeadlinesInput(days_ahead=14))
    assert out.mode == "demo" and out.demo
    dues = [d.due_at for d in out.deadlines]
    assert dues == sorted(dues)
    assert all(d.tzinfo is not None for d in dues)
    assert dues[0] < datetime.now(UTC) + timedelta(hours=24)  # one due within a day
    assert (await list_my_courses(ListMyCoursesInput())).demo
    assert await moodle_status() == ("not_configured", "demo")


async def test_not_configured_when_demo_disabled(monkeypatch):
    _use_env(monkeypatch, MOODLE_DEMO_WHEN_UNCONFIGURED="false")
    with pytest.raises(MoodleError) as info:
        await list_my_courses(ListMyCoursesInput())
    assert info.value.code == "not_configured"
    assert await moodle_status() == ("not_configured", "none")


def test_demo_fixtures_use_only_fake_moodle_style_urls():
    text = (REPO_ROOT / "data/fixtures/moodle/contents.json").read_text()
    assert "https://moodle.iitb.ac.in/mod/" in text


async def test_demo_course_contents_by_short_name_case_insensitive():
    out = await get_course_contents(GetCourseContentsInput(course_code="ie624"))
    assert out.course and out.course.short_name == "IE624"
    assert out.sections and out.demo
    missing = await get_course_contents(GetCourseContentsInput(course_code="ZZ999"))
    assert missing.course is None and "ZZ999" in missing.note


# ---------- resolution order ----------


def test_resolution_order(monkeypatch, memory_keyring):
    """iCal first (the IITB route), then a token for other Moodle sites."""
    _use_env(monkeypatch, MOODLE_TOKEN="envtoken12345678", MOODLE_ICAL_URL=FAKE_ICAL_URL)
    keyring.set_password("campuspilot", "moodle_ical_url", FAKE_ICAL_URL + "&k=1")
    assert resolve_source().secret.endswith("&k=1")  # keychain iCal first
    keyring.delete_password("campuspilot", "moodle_ical_url")
    assert resolve_source().secret == FAKE_ICAL_URL  # then env iCal, even with a token set
    assert resolve_source().mode == "ical"
    monkeypatch.delenv("MOODLE_ICAL_URL")
    get_settings.cache_clear()
    keyring.set_password("campuspilot", "moodle_token", "keychaintoken123")
    assert resolve_source().secret == "keychaintoken123"  # token only without a link
    keyring.delete_password("campuspilot", "moodle_token")
    assert resolve_source().secret == "envtoken12345678"


async def test_ical_errors_show_only_the_host_and_nothing_is_logged(monkeypatch, caplog):
    import logging

    import httpx
    import respx

    from campuspilot.moodle.errors import MoodleError
    from campuspilot.moodle.ical import fetch_ics

    secret = "authtoken=SECRETabc123"
    url = f"https://moodle.iitb.ac.in/calendar/export_execute.php?userid=7&{secret}"
    caplog.set_level(logging.DEBUG)
    for response in (httpx.Response(403), httpx.ConnectError("boom")):
        with respx.mock as router:
            route = router.get(url)
            if isinstance(response, Exception):
                route.mock(side_effect=response)
            else:
                route.mock(return_value=response)
            with pytest.raises(MoodleError) as err:
                await fetch_ics(url)
        assert "moodle.iitb.ac.in" in err.value.message
        assert "SECRET" not in err.value.message and "export_execute" not in err.value.message
        assert "SECRET" not in str(err.value) and err.value.__cause__ is None
    assert "SECRET" not in caplog.text


def test_source_repr_hides_secret():
    assert FAKE_TOKEN not in repr(resolve_source.__globals__["Source"]("rest", FAKE_TOKEN))


# ---------- REST tools ----------


async def test_rest_courses_and_contents(monkeypatch):
    _use_env(monkeypatch, MOODLE_TOKEN=FAKE_TOKEN)
    with respx.mock as router:
        mock_rest(router, REST_PAYLOADS)
        courses = await list_my_courses(ListMyCoursesInput())
        assert [c.short_name for c in courses.courses] == ["IE624", "HS101"]
        assert courses.mode == "rest" and not courses.demo
        contents = await get_course_contents(GetCourseContentsInput(course_code="hs101"))
        assert contents.course and contents.course.id == 12
        assert contents.sections[0].resources[0].type == "resource"


async def test_deadlines_merge_dedupe_sort_and_window(monkeypatch):
    _use_env(monkeypatch, MOODLE_TOKEN=FAKE_TOKEN)
    with respx.mock as router:
        mock_rest(router, REST_PAYLOADS)
        week = await get_my_deadlines(GetMyDeadlinesInput(days_ahead=7))
        titles = [d.title for d in week.deadlines]
        assert titles == ["Report", "Quiz 1 closes"]  # duplicate event dropped, 10-day one outside
        assert week.deadlines[0].kind == "assignment"
        assert all(d.due_at.tzinfo is not None for d in week.deadlines)
        two_days = await get_my_deadlines(GetMyDeadlinesInput(days_ahead=1))
        assert [d.title for d in two_days.deadlines] == ["Report"]
        wide = await get_my_deadlines(GetMyDeadlinesInput(days_ahead=14))
        assert len(wide.deadlines) == 3


async def test_course_code_filter_is_case_insensitive(monkeypatch):
    _use_env(monkeypatch, MOODLE_TOKEN=FAKE_TOKEN)
    with respx.mock as router:
        mock_rest(router, REST_PAYLOADS)
        out = await get_my_deadlines(GetMyDeadlinesInput(days_ahead=14, course_code="hs101"))
    assert [d.course for d in out.deadlines] == ["HS101"]


async def test_invalid_token_error_has_friendly_message(monkeypatch):
    _use_env(monkeypatch, MOODLE_TOKEN=FAKE_TOKEN)
    body = {"exception": "moodle_exception", "errorcode": "invalidtoken"}
    with respx.mock as router:
        router.post(REST_URL).mock(return_value=httpx.Response(200, json=body))
        with pytest.raises(MoodleError) as info:
            await list_my_courses(ListMyCoursesInput())
    assert info.value.code == "invalid_token"
    assert await moodle_status() == ("error", "rest")


# ---------- iCal ----------


def test_parse_fixture_ics():
    text = (REPO_ROOT / "data/fixtures/moodle/sample.ics").read_text()
    items = parse_ics(text)
    assert [d.title for d in items] == [
        "Quiz 2 closes (HS101)",
        "Assignment 3 is due",
        "Campus holiday",
    ]
    by_title = {d.title: d for d in items}
    assert by_title["Assignment 3 is due"].course == "IE624"  # from CATEGORIES
    assert by_title["Quiz 2 closes (HS101)"].course == "HS101"  # from the summary
    assert all(d.kind == "event" and d.due_at.tzinfo is not None for d in items)
    assert by_title["Assignment 3 is due"].activity_url.endswith("id=5101")


async def test_ical_mode_deadlines_and_empty_courses(monkeypatch):
    _use_env(monkeypatch, MOODLE_ICAL_URL=FAKE_ICAL_URL)
    ics = ics_text([("Soon (IE624)", 5, ""), ("Later", 24 * 20, "IE611")])
    with respx.mock as router:
        router.get(FAKE_ICAL_URL).mock(return_value=httpx.Response(200, text=ics))
        out = await get_my_deadlines(GetMyDeadlinesInput(days_ahead=7))
        assert [d.title for d in out.deadlines] == ["Soon (IE624)"] and out.mode == "ical"
        courses = await list_my_courses(ListMyCoursesInput())
        contents = await get_course_contents(GetCourseContentsInput(course_code="IE624"))
    assert courses.courses == [] and "calendar-export" in courses.note
    assert contents.sections == [] and contents.note


async def test_ical_url_must_be_https_on_moodle_host():
    for bad in ("http://moodle.iitb.ac.in/cal.ics", "https://evil.example.com/cal.ics"):
        out = await save_credentials(MoodleTokenRequest(ical_url=bad))
        assert not out.ok
    assert keyring.get_password("campuspilot", "moodle_ical_url") is None


# ---------- credentials ----------


async def test_save_token_verifies_then_stores_and_never_echoes(memory_keyring):
    with respx.mock as router:
        mock_rest(router, REST_PAYLOADS)
        out = await save_credentials(MoodleTokenRequest(token=FAKE_TOKEN))
    assert out.ok and out.mode == "rest" and out.user_fullname == "Test Student"
    assert FAKE_TOKEN not in out.model_dump_json()
    assert memory_keyring.get_password("campuspilot", "moodle_token") == FAKE_TOKEN


async def test_bad_token_is_not_stored(memory_keyring):
    body = {"exception": "moodle_exception", "errorcode": "invalidtoken"}
    with respx.mock as router:
        router.post(REST_URL).mock(return_value=httpx.Response(200, json=body))
        out = await save_credentials(MoodleTokenRequest(token=FAKE_TOKEN))
    assert not out.ok and FAKE_TOKEN not in out.model_dump_json()
    assert memory_keyring.store == {}


async def test_save_ical_verifies_then_stores(memory_keyring):
    with respx.mock as router:
        router.get(FAKE_ICAL_URL).mock(
            return_value=httpx.Response(200, text=ics_text([("X", 5, "")]))
        )
        out = await save_credentials(MoodleTokenRequest(ical_url=FAKE_ICAL_URL))
    assert out.ok and out.mode == "ical" and "fakeauth99" not in out.model_dump_json()
    assert memory_keyring.get_password("campuspilot", "moodle_ical_url") == FAKE_ICAL_URL


async def test_unparseable_ical_is_not_stored(memory_keyring):
    with respx.mock as router:
        router.get(FAKE_ICAL_URL).mock(return_value=httpx.Response(200, text="not a calendar"))
        out = await save_credentials(MoodleTokenRequest(ical_url=FAKE_ICAL_URL))
    assert not out.ok and memory_keyring.store == {}


async def test_delete_credentials_removes_both(memory_keyring):
    keyring.set_password("campuspilot", "moodle_token", FAKE_TOKEN)
    keyring.set_password("campuspilot", "moodle_ical_url", FAKE_ICAL_URL)
    assert delete_credentials().ok
    assert memory_keyring.store == {}


async def test_token_never_in_logs_or_exceptions(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    _use_env(monkeypatch, MOODLE_TOKEN=FAKE_TOKEN)
    errors: list[str] = []
    with respx.mock as router:
        router.post(REST_URL).mock(side_effect=httpx.ConnectError("boom"))
        try:
            await list_my_courses(ListMyCoursesInput())
        except MoodleError as err:
            errors += [str(err), repr(err), err.message]
    with respx.mock as router:
        router.post(REST_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        try:
            await save_credentials(MoodleTokenRequest(token=FAKE_TOKEN))
        except MoodleError as err:
            errors.append(str(err))
    assert errors
    assert FAKE_TOKEN not in caplog.text
    assert all(FAKE_TOKEN not in e for e in errors)
