"""Hosted-mode Moodle: per-request credentials, host lock, no cache, no secret leaks."""

from __future__ import annotations

import contextlib

import httpx
import pytest
import respx

from campuspilot.config import get_settings
from campuspilot.moodle import client as client_module
from campuspilot.moodle import credentials, ical
from campuspilot.moodle.credentials import (
    RequestCredentials,
    get_request_credentials,
    parse_request_credentials,
    reset_request_credentials,
    set_request_credentials,
)
from campuspilot.moodle.tools import MoodleError, check_credentials, resolve_source
from tests.moodle_helpers import (
    BASE,
    FAKE_ICAL_URL,
    FAKE_TOKEN,
    REST_URL,
    SITE_INFO,
    ics_text,
    mock_rest,
)


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "hosted")
    get_settings.cache_clear()
    client_module.clear_cache()
    ical.clear_cache()
    yield
    get_settings.cache_clear()


@contextlib.contextmanager
def as_request(c):
    token = set_request_credentials(c)
    try:
        yield
    finally:
        reset_request_credentials(token)


# ---------- parsing ----------


@pytest.mark.parametrize("bad", ["short", "has space 12345678", "bad!chars1234", "x" * 129])
def test_bad_token_rejected_without_echo(bad):
    with pytest.raises(MoodleError) as exc:
        parse_request_credentials(bad, None)
    assert bad.strip() not in str(exc.value) and bad not in repr(exc.value.args)


def test_good_token_and_empty():
    c = parse_request_credentials(FAKE_TOKEN, None)
    assert c and c.token == FAKE_TOKEN and c.ical_url is None
    assert parse_request_credentials(None, None) is None
    assert parse_request_credentials("", " ") is None


def test_both_set_is_error():
    with pytest.raises(MoodleError):
        parse_request_credentials(FAKE_TOKEN, FAKE_ICAL_URL)


@pytest.mark.parametrize(
    "url",
    [
        "https://moodle.iitb.ac.in.evil.com/calendar/x?authtoken=sekrit",
        "http://moodle.iitb.ac.in/calendar/x?authtoken=sekrit",
        "https://x@evil.com/calendar?authtoken=sekrit",
        "https://moodle.iitb.ac.in@evil.com/c?authtoken=sekrit",
        "https://user:pw@moodle.iitb.ac.in/c?authtoken=sekrit",
        "https://moodle.iitb.ac.in:8443/c?authtoken=sekrit",
        "https://moodle.iitb.ac.in/c?authtoken=sekrit" + "a" * 1000,
        "https://moodle.iitb.ac.in:abc/c?authtoken=sekrit",
    ],
)
def test_ical_url_host_lock(url):
    with pytest.raises(MoodleError) as exc:
        parse_request_credentials(None, url)
    assert "sekrit" not in str(exc.value) and "evil" not in exc.value.message


def test_good_ical_url():
    c = parse_request_credentials(None, FAKE_ICAL_URL)
    assert c and c.ical_url == FAKE_ICAL_URL


def test_repr_hides_values():
    c = RequestCredentials(token=FAKE_TOKEN, ical_url=FAKE_ICAL_URL)
    assert FAKE_TOKEN not in repr(c) and "fakeauth99" not in repr(c) and FAKE_TOKEN not in str(c)


def test_contextvar_roundtrip():
    c = RequestCredentials(token=FAKE_TOKEN)
    t = set_request_credentials(c)
    assert get_request_credentials() is c
    reset_request_credentials(t)
    assert get_request_credentials() is None


# ---------- resolution ----------


def test_hosted_ignores_keychain_and_env(hosted, monkeypatch, memory_keyring):
    credentials.store_token("keychaintoken1234")
    monkeypatch.setenv("MOODLE_TOKEN", "envtoken12345678")
    monkeypatch.setenv("MOODLE_ICAL_URL", FAKE_ICAL_URL)
    get_settings.cache_clear()
    assert resolve_source().mode == "demo"
    with as_request(RequestCredentials(token=FAKE_TOKEN)):
        s = resolve_source()
    assert (s.mode, s.secret) == ("rest", FAKE_TOKEN)


def test_hosted_not_configured_without_demo(hosted, monkeypatch):
    monkeypatch.setenv("MOODLE_DEMO_WHEN_UNCONFIGURED", "false")
    get_settings.cache_clear()
    with pytest.raises(MoodleError) as exc:
        resolve_source()
    assert exc.value.code == "not_configured"


def test_local_ignores_request_credentials(memory_keyring):
    with as_request(RequestCredentials(token=FAKE_TOKEN)):
        assert resolve_source().mode == "demo"


# ---------- cache ----------


@pytest.mark.asyncio
async def test_hosted_rest_not_cached(hosted):
    client_module.clear_cache()
    with respx.mock(assert_all_called=False) as router:
        route = mock_rest(router, {"core_webservice_get_site_info": SITE_INFO})
        c = client_module.MoodleClient(FAKE_TOKEN)
        await c.site_info()
        await c.site_info()
        assert route.call_count == 2
    assert not client_module._CACHE


@pytest.mark.asyncio
async def test_hosted_ical_not_cached(hosted):
    with respx.mock(assert_all_called=False) as router:
        route = router.get(FAKE_ICAL_URL).mock(return_value=httpx.Response(200, text="x"))
        await ical.fetch_ics(FAKE_ICAL_URL)
        await ical.fetch_ics(FAKE_ICAL_URL)
        assert route.call_count == 2
    assert not ical._CACHE


@pytest.mark.asyncio
async def test_local_cache_keyed_by_token():
    client_module.clear_cache()
    with respx.mock(assert_all_called=False) as router:
        route = mock_rest(router, {"core_webservice_get_site_info": SITE_INFO})
        await client_module.MoodleClient(FAKE_TOKEN).site_info()
        await client_module.MoodleClient(FAKE_TOKEN).site_info()
        await client_module.MoodleClient("othertoken12345678").site_info()
        assert route.call_count == 2
    assert all(FAKE_TOKEN not in str(k) for k in client_module._CACHE)


# ---------- redirects ----------


@pytest.mark.asyncio
async def test_ical_redirect_to_other_host_refused():
    with respx.mock(assert_all_called=False) as router:
        router.get(FAKE_ICAL_URL).mock(
            return_value=httpx.Response(302, headers={"location": "https://evil.com/steal"})
        )
        evil = router.get("https://evil.com/steal").mock(return_value=httpx.Response(200, text="x"))
        with pytest.raises(MoodleError) as exc:
            await ical.fetch_ics(FAKE_ICAL_URL)
        assert not evil.called
        assert "fakeauth99" not in str(exc.value)


@pytest.mark.asyncio
async def test_ical_redirect_same_host_followed_and_capped():
    with respx.mock(assert_all_called=False) as router:
        router.get(FAKE_ICAL_URL).mock(
            return_value=httpx.Response(302, headers={"location": f"{BASE}/final"})
        )
        router.get(f"{BASE}/final").mock(return_value=httpx.Response(200, text="ok"))
        assert await ical.fetch_ics(FAKE_ICAL_URL) == "ok"
    ical.clear_cache()
    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith=BASE).mock(
            return_value=httpx.Response(302, headers={"location": f"{BASE}/loop"})
        )
        with pytest.raises(MoodleError):
            await ical.fetch_ics(FAKE_ICAL_URL)


@pytest.mark.asyncio
async def test_rest_redirect_not_followed(hosted):
    with respx.mock(assert_all_called=False) as router:
        router.post(REST_URL).mock(
            return_value=httpx.Response(302, headers={"location": "https://evil.com/"})
        )
        evil = router.post("https://evil.com/").mock(return_value=httpx.Response(200, json={}))
        with pytest.raises(MoodleError):
            await client_module.MoodleClient(FAKE_TOKEN).site_info()
        assert not evil.called


# ---------- check_credentials ----------


@pytest.mark.asyncio
async def test_check_rest_ok(hosted):
    with as_request(RequestCredentials(token=FAKE_TOKEN)):
        with respx.mock(assert_all_called=False) as router:
            mock_rest(router, {"core_webservice_get_site_info": SITE_INFO})
            r = await check_credentials()
        assert (r.ok, r.mode, r.site_name, r.user_fullname) == (
            True,
            "rest",
            "Fake IITB Moodle",
            "Test Student",
        )
        assert FAKE_TOKEN not in r.model_dump_json()


@pytest.mark.asyncio
async def test_check_ical_ok(hosted):
    with as_request(RequestCredentials(ical_url=FAKE_ICAL_URL)):
        with respx.mock(assert_all_called=False) as router:
            router.get(FAKE_ICAL_URL).mock(
                return_value=httpx.Response(200, text=ics_text([("IE624 A1", 5, "IE624")]))
            )
            r = await check_credentials()
        assert r.ok and r.mode == "ical"
        assert "fakeauth99" not in r.model_dump_json()


@pytest.mark.asyncio
async def test_check_invalid_token(hosted):
    with as_request(RequestCredentials(token=FAKE_TOKEN)):
        with respx.mock(assert_all_called=False) as router:
            router.post(REST_URL).mock(
                return_value=httpx.Response(
                    200, json={"exception": "x", "errorcode": "invalidtoken"}
                )
            )
            with pytest.raises(MoodleError) as exc:
                await check_credentials()
        assert exc.value.code == "invalid_token"


@pytest.mark.asyncio
async def test_check_none_is_not_configured(hosted):
    with pytest.raises(MoodleError) as exc:
        await check_credentials()
    assert exc.value.code == "not_configured"


@pytest.mark.asyncio
async def test_check_unreachable_hosted_message(hosted):
    with as_request(RequestCredentials(token=FAKE_TOKEN)):
        with respx.mock(assert_all_called=False) as router:
            router.post(REST_URL).mock(side_effect=httpx.ConnectError("boom " + FAKE_TOKEN))
            with pytest.raises(MoodleError) as exc:
                await check_credentials()
        assert exc.value.code == "unavailable"
        assert (
            exc.value.message
            == "Moodle isn't reachable from the hosted version. Use the local app."
        )
        assert FAKE_TOKEN not in str(exc.value) and exc.value.__cause__ is None
        assert exc.value.__suppress_context__


@pytest.mark.asyncio
async def test_transport_error_does_not_leak_token(hosted):
    with respx.mock(assert_all_called=False) as router:
        router.post(REST_URL).mock(side_effect=httpx.ReadTimeout("t " + FAKE_TOKEN))
        with pytest.raises(MoodleError) as exc:
            await client_module.MoodleClient(FAKE_TOKEN).site_info()
    assert FAKE_TOKEN not in str(exc.value) and FAKE_TOKEN not in repr(exc.value.args)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
