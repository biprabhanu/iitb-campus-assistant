"""REST client: parsing, Moodle's HTTP-200 errors, allowlist, timeout, cache."""

from __future__ import annotations

import httpx
import pytest
import respx

from campuspilot.moodle import client as client_module
from campuspilot.moodle.client import ALLOWED_FUNCTIONS, MoodleClient
from campuspilot.moodle.errors import MoodleError
from tests.moodle_helpers import (
    COURSES,
    FAKE_TOKEN,
    REST_URL,
    SITE_INFO,
    assignments_payload,
    events_payload,
    form_of,
    mock_rest,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    client_module.clear_cache()
    yield
    client_module.clear_cache()


async def test_each_rest_function_is_parsed():
    payloads = {
        "core_webservice_get_site_info": SITE_INFO,
        "core_enrol_get_users_courses": COURSES,
        "mod_assign_get_assignments": assignments_payload([("A1", 1, 5)]),
        "core_calendar_get_action_events_by_timesort": events_payload([("E", 2, 5, "IE624", "u")]),
        "core_course_get_contents": [{"name": "Week 1", "modules": []}],
    }
    client = MoodleClient(FAKE_TOKEN)
    with respx.mock as router:
        route = mock_rest(router, payloads)
        assert (await client.site_info())["userid"] == 42
        assert len(await client.courses(42)) == 2
        assert (await client.assignments())["courses"][0]["shortname"] == "IE624"
        assert len((await client.action_events(0, 100))["events"]) == 1
        assert (await client.course_contents(11))[0]["name"] == "Week 1"
    first = form_of(route.calls[0].request)
    assert first["wstoken"] == FAKE_TOKEN
    assert first["moodlewsrestformat"] == "json"


@pytest.mark.parametrize(
    ("errorcode", "expected"),
    [
        ("invalidtoken", "invalid_token"),
        ("accessexception", "access_exception"),
        ("weird", "unavailable"),
    ],
)
async def test_http_200_exception_becomes_error(errorcode, expected):
    body = {"exception": "moodle_exception", "errorcode": errorcode, "message": "secret detail"}
    with respx.mock as router:
        router.post(REST_URL).mock(return_value=httpx.Response(200, json=body))
        with pytest.raises(MoodleError) as info:
            await MoodleClient(FAKE_TOKEN).site_info()
    assert info.value.code == expected
    assert "secret detail" not in info.value.message


async def test_unknown_function_is_refused_without_any_request():
    with respx.mock as router:
        route = router.post(REST_URL).mock(return_value=httpx.Response(200, json={}))
        for bad in ("mod_assign_submit_for_grading", "core_message_send_instant_messages"):
            with pytest.raises(MoodleError):
                await MoodleClient(FAKE_TOKEN).call(bad)
        assert not route.called


def test_allowlist_has_exactly_the_five_read_functions():
    assert len(ALLOWED_FUNCTIONS) == 5
    assert all(
        not name.startswith(("mod_assign_submit", "core_message")) for name in ALLOWED_FUNCTIONS
    )


async def test_timeout_becomes_timeout_error():
    with respx.mock as router:
        router.post(REST_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(MoodleError) as info:
            await MoodleClient(FAKE_TOKEN).site_info()
    assert info.value.code == "timeout"
    assert FAKE_TOKEN not in str(info.value)


async def test_second_identical_call_hits_the_cache():
    with respx.mock as router:
        route = mock_rest(router, {"core_webservice_get_site_info": SITE_INFO})
        client = MoodleClient(FAKE_TOKEN)
        await client.site_info()
        await client.site_info()
        assert route.call_count == 1
        await MoodleClient("othertoken987654321").site_info()  # different token: no sharing
        assert route.call_count == 2


def test_cache_keys_never_contain_the_raw_token():
    client_module._CACHE[(client_module.fingerprint(FAKE_TOKEN), "f", ())] = (0, None)
    assert FAKE_TOKEN not in repr(client_module._CACHE)
