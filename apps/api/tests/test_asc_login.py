"""ASC login against a fake portal: success, wrong password, OTP, CAPTCHA, off-host redirects,
read-only enforcement, logout, and "nothing secret leaks"."""

# ruff: noqa: F401, F811 (fixtures imported from asc_helpers are used as test arguments)

from __future__ import annotations

import logging

import httpx
import pytest

from campuspilot import asc
from campuspilot.asc import credentials
from campuspilot.asc.login import STATE
from campuspilot.schemas.connectors import ConnectorLoginRequest, ConnectorOtpRequest
from tests.asc_helpers import OTP, PASSWORD, USER, FakePortal, clean_asc_state, portal


def req(password: str = PASSWORD) -> ConnectorLoginRequest:
    return ConnectorLoginRequest(username=USER, password=password)


async def test_full_login_saves_keychain_after_success(portal: FakePortal, memory_keyring) -> None:
    status = await asc.asc_login(req())
    assert (status.name, status.state, status.account, status.demo) == (
        "asc",
        "connected",
        USER,
        False,
    )
    assert credentials.load() == (USER, PASSWORD)
    # Exactly one POST: the SSO form, with its hidden fields and the right field names.
    assert portal.posted == [
        {
            "lt": "LT-FAKE-123",
            "execution": "e1s1",
            "submit": "Login",
            "uname": USER,
            "pwd": PASSWORD,
        }
    ]
    assert (await asc.asc_status()).state == "connected"


async def test_wrong_password_is_auth_failed_and_nothing_saved(
    portal: FakePortal, memory_keyring
) -> None:
    with pytest.raises(asc.ConnectorError) as err:
        await asc.asc_login(req("wrong-pass-999"))
    assert err.value.code == "auth_failed"
    assert "wrong-pass-999" not in err.value.message
    assert memory_keyring.store == {}
    assert (await asc.asc_status()).state == "not_connected"


async def test_otp_flow(portal: FakePortal, memory_keyring) -> None:
    portal.mode = "otp"
    status = await asc.asc_login(req())
    assert status.state == "needs_otp" and status.challenge_id
    assert memory_keyring.store == {}  # nothing saved until the code works
    assert (await asc.asc_status()).challenge_id == status.challenge_id

    with pytest.raises(asc.ConnectorError) as err:
        await asc.asc_submit_otp(
            ConnectorOtpRequest(challenge_id=status.challenge_id, code="000000")
        )
    assert err.value.code == "otp_invalid"
    assert (await asc.asc_status()).state == "needs_otp"  # still waiting, can retry

    done = await asc.asc_submit_otp(ConnectorOtpRequest(challenge_id=status.challenge_id, code=OTP))
    assert (done.state, done.account) == ("connected", USER)
    assert credentials.load() == (USER, PASSWORD)
    assert portal.posted[-1] == {"execution": "e1s2", "otp_code": OTP}


async def test_otp_unknown_challenge_and_too_many_tries(portal: FakePortal) -> None:
    with pytest.raises(asc.ConnectorError) as err:
        await asc.asc_submit_otp(ConnectorOtpRequest(challenge_id="nope", code="123456"))
    assert err.value.code == "otp_invalid"

    portal.mode = "otp"
    cid = (await asc.asc_login(req())).challenge_id
    assert cid
    for _ in range(3):
        with pytest.raises(asc.ConnectorError):
            await asc.asc_submit_otp(ConnectorOtpRequest(challenge_id=cid, code="000000"))
    assert STATE.pending == {}  # the login was dropped after the third wrong code
    assert (await asc.asc_status()).state == "not_connected"


async def test_captcha_is_blocked_never_bypassed(portal: FakePortal, memory_keyring) -> None:
    portal.mode = "captcha"
    with pytest.raises(asc.ConnectorError) as err:
        await asc.asc_login(req())
    assert err.value.code == "blocked"
    assert "CAPTCHA" in err.value.message and "browser" in err.value.message
    assert portal.posted == []  # credentials were never sent
    assert memory_keyring.store == {}


async def test_offsite_redirect_is_blocked(portal: FakePortal) -> None:
    portal.mode = "offsite_redirect"
    with pytest.raises(asc.ConnectorError) as err:
        await asc.asc_login(req())
    assert err.value.code == "blocked"
    assert all("evil.example.com" not in c[1] for c in portal.calls)  # never even requested


async def test_http_redirect_is_blocked(portal: FakePortal) -> None:
    portal.mode = "http_redirect"
    with pytest.raises(asc.ConnectorError) as err:
        await asc.asc_login(req())
    assert err.value.code == "blocked"


async def test_unreachable_mentions_campus_network_or_vpn(respx_mock) -> None:
    respx_mock.route().mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(asc.ConnectorError) as err:
        await asc.asc_login(req())
    assert err.value.code == "unreachable"
    assert "campus network" in err.value.message and "VPN" in err.value.message


async def test_timeout(respx_mock) -> None:
    respx_mock.route().mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(asc.ConnectorError) as err:
        await asc.asc_login(req())
    assert err.value.code == "timeout"


async def test_only_get_after_login(portal: FakePortal) -> None:
    await asc.asc_login(req())
    session = STATE.session
    assert session is not None and session.logged_in
    posts_before = portal.count("POST", "")
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        with pytest.raises(asc.ConnectorError) as err:
            await session.request(method, "https://asc.iitb.ac.in/courses", data={"x": "1"})
        assert err.value.code == "blocked"
    assert portal.count("POST", "") == posts_before  # nothing went on the wire


async def test_logout_clears_session_and_keychain(portal: FakePortal, memory_keyring) -> None:
    await asc.asc_login(req())
    status = asc.asc_logout()
    assert status.state == "not_connected"
    assert memory_keyring.store == {}
    assert STATE.session is None


async def test_nothing_secret_in_errors_or_logs(
    portal: FakePortal, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    secret = "s3cret-pass-XYZ"
    with pytest.raises(asc.ConnectorError) as err:
        await asc.asc_login(req(secret))
    await asc.asc_login(req())
    text = "\n".join([repr(err.value), str(err.value), caplog.text])
    for needle in (secret, PASSWORD, USER, "ST-FAKE", "LT-FAKE-123"):
        assert needle not in text
