"""Google Calendar connector: all Google endpoints are mocked with respx (fully offline)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from campuspilot import gcal
from campuspilot.config import get_settings
from campuspilot.connectors import keychain
from campuspilot.connectors.errors import ConnectorError
from campuspilot.gcal import auth
from campuspilot.main import create_app
from tests.gcal_helpers import (
    ACCESS,
    CLIENT_ID,
    EVENTS_URL,
    REFRESH,
    SECRETS,
    TOKEN_URI,
    make_request,
    store_refresh,
    write_client_file,
)


@pytest.fixture(autouse=True)
def gcal_env(tmp_path, monkeypatch):
    client_file = tmp_path / "google_client.json"
    write_client_file(client_file)
    monkeypatch.setenv("GCAL_CLIENT_FILE", str(client_file))
    monkeypatch.setenv("GCAL_ENABLED", "true")
    get_settings.cache_clear()
    auth.reset_memory()
    yield client_file
    auth.reset_memory()


def _token_reply(**over):
    return httpx.Response(
        200, json={"access_token": ACCESS, "expires_in": 3600, "refresh_token": REFRESH, **over}
    )


def _assert_no_secret(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


# ---------- client file ----------


async def test_missing_client_file_points_to_setup(gcal_env):
    gcal_env.unlink()
    with pytest.raises(ConnectorError) as err:
        await gcal.gcal_start_connect()
    assert err.value.code == "not_connected"
    assert "Desktop app" in err.value.message


async def test_invalid_client_file_hides_contents(gcal_env):
    gcal_env.write_text('{"installed": {"client_id": "x", "client_secret": "LEAKY"}} nope')
    with pytest.raises(ConnectorError) as err:
        await gcal.gcal_start_connect()
    assert err.value.code == "not_connected"
    assert "LEAKY" not in err.value.message


async def test_http_token_uri_refused(gcal_env):
    gcal_env.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "a",
                    "client_secret": "b",
                    "token_uri": "http://evil.example/token",
                }
            }
        )
    )
    with pytest.raises(ConnectorError):
        await gcal.gcal_start_connect()


# ---------- OAuth ----------


async def test_auth_url_contents():
    start = await gcal.gcal_start_connect()
    url = urlparse(start.auth_url)
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert q["response_type"] == "code"
    assert q["client_id"] == CLIENT_ID
    assert q["redirect_uri"] == "http://127.0.0.1:8000/v1/connectors/gcal/callback"
    assert q["scope"] == "https://www.googleapis.com/auth/calendar.events"
    assert q["access_type"] == "offline"
    assert q["prompt"] == "consent"
    assert q["code_challenge_method"] == "S256"
    assert len(q["state"]) >= 32
    assert "client_secret" not in q
    # The challenge is the S256 of the verifier we keep in memory.
    verifier = auth._pending[q["state"]][0]
    digest = hashlib.sha256(verifier.encode()).digest()
    assert q["code_challenge"] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def test_states_are_random():
    a = parse_qs(urlparse((await gcal.gcal_start_connect()).auth_url).query)["state"]
    b = parse_qs(urlparse((await gcal.gcal_start_connect()).auth_url).query)["state"]
    assert a != b


async def _start() -> tuple[str, str]:
    q = parse_qs(urlparse((await gcal.gcal_start_connect()).auth_url).query)
    state = q["state"][0]
    return state, auth._pending[state][0]


@respx.mock
async def test_finish_connect_exchanges_code_and_stores_refresh_token():
    state, verifier = await _start()
    route = respx.post(TOKEN_URI).mock(return_value=_token_reply())
    status = await gcal.gcal_finish_connect("the-code", state)
    sent = parse_qs(route.calls.last.request.content.decode())
    assert sent["grant_type"] == ["authorization_code"]
    assert sent["code"] == ["the-code"]
    assert sent["code_verifier"] == [verifier]
    assert sent["redirect_uri"] == ["http://127.0.0.1:8000/v1/connectors/gcal/callback"]
    assert keychain.get_secret("gcal_refresh_token") == REFRESH
    assert status.state == "connected" and status.account == "primary"
    assert gcal.is_connected()
    assert (await gcal.gcal_status()).state == "connected"


@respx.mock
async def test_unknown_state_rejected_without_network():
    route = respx.post(TOKEN_URI).mock(return_value=_token_reply())
    with pytest.raises(ConnectorError) as err:
        await gcal.gcal_finish_connect("code", "never-issued")
    assert err.value.code == "auth_failed"
    assert not route.called


@respx.mock
async def test_state_is_single_use():
    state, _ = await _start()
    respx.post(TOKEN_URI).mock(return_value=_token_reply())
    await gcal.gcal_finish_connect("code", state)
    with pytest.raises(ConnectorError) as err:
        await gcal.gcal_finish_connect("code", state)
    assert err.value.code == "auth_failed"


@respx.mock
async def test_state_expires(monkeypatch):
    state, _ = await _start()
    route = respx.post(TOKEN_URI).mock(return_value=_token_reply())
    real = auth._now()
    monkeypatch.setattr(auth, "_now", lambda: real + auth.STATE_TTL + 1)
    with pytest.raises(ConnectorError) as err:
        await gcal.gcal_finish_connect("code", state)
    assert err.value.code == "auth_failed"
    assert not route.called


@respx.mock
async def test_no_refresh_token_returned():
    state, _ = await _start()
    respx.post(TOKEN_URI).mock(
        return_value=httpx.Response(200, json={"access_token": ACCESS, "expires_in": 3600})
    )
    with pytest.raises(ConnectorError) as err:
        await gcal.gcal_finish_connect("code", state)
    assert err.value.code == "auth_failed"
    assert not gcal.is_connected()


@respx.mock
async def test_exchange_rejected_by_google():
    state, _ = await _start()
    respx.post(TOKEN_URI).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(ConnectorError) as err:
        await gcal.gcal_finish_connect("bad", state)
    assert err.value.code == "auth_failed"


# ---------- tokens ----------


@respx.mock
async def test_refresh_is_cached_until_expiry(monkeypatch):
    store_refresh()
    route = respx.post(TOKEN_URI).mock(return_value=_token_reply())
    assert await auth.access_token() == ACCESS
    assert await auth.access_token() == ACCESS
    assert route.call_count == 1
    sent = parse_qs(route.calls.last.request.content.decode())
    assert sent["grant_type"] == ["refresh_token"] and sent["refresh_token"] == [REFRESH]
    real = auth._now()
    monkeypatch.setattr(auth, "_now", lambda: real + 4000)
    await auth.access_token()
    assert route.call_count == 2


@respx.mock
async def test_invalid_grant_deletes_stored_token():
    store_refresh()
    keychain.set_secret("gcal_account", "primary")
    respx.post(TOKEN_URI).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(ConnectorError) as err:
        await auth.access_token()
    assert err.value.code == "auth_failed"
    assert err.value.message == "Google Calendar access was revoked. Connect it again in Settings."
    assert keychain.get_secret("gcal_refresh_token") is None
    assert keychain.get_secret("gcal_account") is None


async def test_not_connected_without_token():
    with pytest.raises(ConnectorError) as err:
        await auth.access_token()
    assert err.value.code == "not_connected"


async def test_status_states(gcal_env):
    assert (await gcal.gcal_status()).state == "not_connected"
    store_refresh()
    assert (await gcal.gcal_status()).state == "connected"
    gcal_env.unlink()
    status = await gcal.gcal_status()
    assert status.state == "error" and not gcal.is_connected()


# ---------- disconnect ----------


@respx.mock
async def test_disconnect_revokes_and_deletes():
    store_refresh()
    keychain.set_secret("gcal_account", "primary")
    route = respx.post(auth.REVOKE_URI).mock(return_value=httpx.Response(200))
    status = await gcal.gcal_disconnect()
    assert parse_qs(route.calls.last.request.content.decode())["token"] == [REFRESH]
    assert status.state == "not_connected" and status.message is None
    assert keychain.get_secret("gcal_refresh_token") is None
    assert keychain.get_secret("gcal_account") is None


@respx.mock
@pytest.mark.parametrize("failure", [httpx.Response(400), httpx.ConnectError("down")])
async def test_disconnect_deletes_even_if_revoke_fails(failure):
    store_refresh()
    respx.post(auth.REVOKE_URI).mock(
        side_effect=failure if isinstance(failure, Exception) else None,
        return_value=failure if not isinstance(failure, Exception) else None,
    )
    status = await gcal.gcal_disconnect()
    assert keychain.get_secret("gcal_refresh_token") is None
    assert status.state == "not_connected"
    assert "could not be told" in (status.message or "")


# ---------- create_event ----------


def _mock_ok(found: list | None = None):
    respx.post(TOKEN_URI).mock(return_value=_token_reply())
    lookup = respx.get(EVENTS_URL).mock(
        return_value=httpx.Response(200, json={"items": found or []})
    )
    insert = respx.post(EVENTS_URL).mock(
        return_value=httpx.Response(200, json={"id": "g1", "htmlLink": "https://cal/g1"})
    )
    return lookup, insert


@respx.mock
async def test_create_event_happy_path_exact_body():
    store_refresh()
    lookup, insert = _mock_ok()
    req = make_request()
    result = await gcal.create_event(req)
    assert (result.ok, result.status) == (True, "created")
    assert result.google_event_id == "g1" and result.html_link == "https://cal/g1"

    q = lookup.calls.last.request.url
    assert q.params["privateExtendedProperty"] == f"campuspilotKey={req.event_id}"
    assert "campuspilotKey%3D" in str(q)
    assert q.params["maxResults"] == "1"
    assert lookup.calls.last.request.headers["authorization"] == f"Bearer {ACCESS}"

    assert json.loads(insert.calls.last.request.content) == {
        "summary": "Guest talk on RL",
        "location": "LA 201",
        "start": {"dateTime": "2026-12-05T17:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2026-12-05T18:30:00+05:30", "timeZone": "Asia/Kolkata"},
        "description": "From your mail: Talk on RL this Friday\n\nAdded by CampusPilot",
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
        "extendedProperties": {"private": {"campuspilotKey": req.event_id}},
    }


@respx.mock
async def test_double_click_inserts_once():
    store_refresh()
    respx.post(TOKEN_URI).mock(return_value=_token_reply())
    stored: list[dict] = []

    def lookup(_request):
        return httpx.Response(200, json={"items": stored})

    def insert(request):
        stored.append({"id": "g1", "htmlLink": "https://cal/g1"})
        return httpx.Response(200, json=stored[0])

    respx.get(EVENTS_URL).mock(side_effect=lookup)
    ins = respx.post(EVENTS_URL).mock(side_effect=insert)
    first = await gcal.create_event(make_request())
    second = await gcal.create_event(make_request())
    assert first.status == "created"
    assert second.status == "already_exists" and second.google_event_id == "g1"
    assert second.html_link == "https://cal/g1"
    assert ins.call_count == 1


@respx.mock
async def test_event_id_mismatch_rejected_before_any_call():
    store_refresh()
    token = respx.post(TOKEN_URI).mock(return_value=_token_reply())
    with pytest.raises(ConnectorError) as err:
        await gcal.create_event(make_request(event_id="deadbeefdeadbeef"))
    assert err.value.code == "google_error"
    assert not token.called


@respx.mock
async def test_all_day_event():
    store_refresh()
    _, insert = _mock_ok()
    await gcal.create_event(make_request(all_day=True, end=None, venue=None))
    body = json.loads(insert.calls.last.request.content)
    assert body["start"] == {"date": "2026-12-05"}
    assert body["end"] == {"date": "2026-12-06"}  # exclusive
    assert "location" not in body


@respx.mock
async def test_default_end_is_one_hour():
    store_refresh()
    _, insert = _mock_ok()
    await gcal.create_event(make_request(end=None))
    body = json.loads(insert.calls.last.request.content)
    assert body["end"]["dateTime"] == "2026-12-05T18:00:00+05:30"


@respx.mock
async def test_utc_start_is_shown_in_kolkata_time():
    from datetime import datetime

    store_refresh()
    _, insert = _mock_ok()
    start = datetime.fromisoformat("2026-12-05T11:30:00+00:00")
    await gcal.create_event(make_request(start=start, end=None))
    body = json.loads(insert.calls.last.request.content)
    assert body["start"]["dateTime"] == "2026-12-05T17:00:00+05:30"


@respx.mock
async def test_401_refreshes_once_then_works():
    store_refresh()
    token = respx.post(TOKEN_URI).mock(return_value=_token_reply())
    respx.get(EVENTS_URL).mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"items": []})]
    )
    respx.post(EVENTS_URL).mock(return_value=httpx.Response(200, json={"id": "g1"}))
    assert (await gcal.create_event(make_request())).status == "created"
    assert token.call_count == 2


@respx.mock
async def test_repeated_401_is_auth_failed():
    store_refresh()
    respx.post(TOKEN_URI).mock(return_value=_token_reply())
    respx.get(EVENTS_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(ConnectorError) as err:
        await gcal.create_event(make_request())
    assert err.value.code == "auth_failed"


@respx.mock
@pytest.mark.parametrize("status", [403, 429, 500, 400])
async def test_http_errors_map_to_google_error(status):
    store_refresh()
    respx.post(TOKEN_URI).mock(return_value=_token_reply())
    respx.get(EVENTS_URL).mock(return_value=httpx.Response(status, json={"error": ACCESS}))
    with pytest.raises(ConnectorError) as err:
        await gcal.create_event(make_request())
    assert err.value.code == "google_error"
    _assert_no_secret(err.value.message)


@respx.mock
@pytest.mark.parametrize(
    ("exc", "code"),
    [(httpx.ConnectError("x"), "unreachable"), (httpx.ReadTimeout("x"), "timeout")],
)
async def test_network_errors(exc, code):
    store_refresh()
    respx.post(TOKEN_URI).mock(return_value=_token_reply())
    respx.get(EVENTS_URL).mock(side_effect=exc)
    with pytest.raises(ConnectorError) as err:
        await gcal.create_event(make_request())
    assert err.value.code == code


async def test_create_event_needs_connection():
    with pytest.raises(ConnectorError) as err:
        await gcal.create_event(make_request())
    assert err.value.code == "not_connected"


@respx.mock
async def test_calendar_id_is_url_encoded(monkeypatch):
    monkeypatch.setenv("GCAL_CALENDAR_ID", "abc@group.calendar.google.com")
    get_settings.cache_clear()
    store_refresh()
    respx.post(TOKEN_URI).mock(return_value=_token_reply())
    url = "https://www.googleapis.com/calendar/v3/calendars/abc%40group.calendar.google.com/events"
    respx.get(url).mock(return_value=httpx.Response(200, json={"items": []}))
    ins = respx.post(url).mock(return_value=httpx.Response(200, json={"id": "g1"}))
    await gcal.create_event(make_request())
    assert ins.called


# ---------- no secrets anywhere ----------


@respx.mock
async def test_no_secret_in_logs_or_errors(caplog):
    caplog.set_level(logging.DEBUG)
    state, _ = await _start()
    respx.post(TOKEN_URI).mock(return_value=_token_reply())
    status = await gcal.gcal_finish_connect("code", state)
    respx.get(EVENTS_URL).mock(return_value=httpx.Response(403, json={"error": ACCESS}))
    with pytest.raises(ConnectorError) as err:
        await gcal.create_event(make_request())
    _assert_no_secret(repr(err.value) + str(err.value) + status.model_dump_json())
    _assert_no_secret(caplog.text)


# ---------- API level ----------

CONFIRM = {"X-CampusPilot-Confirm": "yes"}


@respx.mock
def test_api_calendar_events_endpoint():
    store_refresh()
    _mock_ok()
    client = TestClient(create_app())
    body = json.loads(make_request().model_dump_json())
    assert client.post("/v1/calendar/events", json=body).status_code == 403  # no header
    res = client.post("/v1/calendar/events", json=body, headers=CONFIRM)
    assert res.status_code == 200
    assert res.json()["status"] == "created" and res.json()["html_link"] == "https://cal/g1"


def test_api_event_mismatch_is_calendar_error():
    store_refresh()
    client = TestClient(create_app())
    body = json.loads(make_request(event_id="deadbeefdeadbeef").model_dump_json())
    res = client.post("/v1/calendar/events", json=body, headers=CONFIRM)
    assert res.status_code == 502


@respx.mock
def test_api_connect_callback_disconnect_flow():
    client = TestClient(create_app())
    start = client.post("/v1/connectors/gcal/connect", headers=CONFIRM)
    assert start.status_code == 200
    state = parse_qs(urlparse(start.json()["auth_url"]).query)["state"][0]
    respx.post(TOKEN_URI).mock(return_value=_token_reply())
    page = client.get("/v1/connectors/gcal/callback", params={"code": "c", "state": state})
    assert "connected" in page.text
    assert client.get("/v1/connectors").json()["gcal"]["state"] == "connected"
    respx.post(auth.REVOKE_URI).mock(return_value=httpx.Response(200))
    res = client.delete("/v1/connectors/gcal", headers=CONFIRM)
    assert res.json()["state"] == "not_connected"
    assert not gcal.is_connected()
