"""The IMAP layer against a fake server: read-only guarantees, search, errors."""

from __future__ import annotations

import socket
from datetime import UTC, date, datetime, timedelta

import pytest

from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.mail import imap_client
from campuspilot.mail.imap_client import ReadOnlyMailbox, imap_date, scan_mail
from tests.mail_helpers import FakeImap, install_fake_imap, make_eml


def _server(count: int = 3) -> FakeImap:
    base = datetime.now(UTC)
    return FakeImap(
        {
            uid: make_eml(
                f"Mail number {uid}", f"body {uid} hackathon" if uid % 2 else f"body {uid}",
                date=base - timedelta(hours=count - uid),
                message_id=f"<m{uid}@example.org>",
            )
            for uid in range(1, count + 1)
        }
    )  # fmt: skip


async def test_scan_is_read_only_and_peeks(monkeypatch) -> None:
    server = _server()
    install_fake_imap(monkeypatch, server)
    result = await scan_mail(get_settings(), "user", "secret-pw", days=14)
    assert [m.message.uid for m in result.mails] == ["3", "2", "1"]  # newest first
    assert result.scanned == 3
    server.assert_read_only()
    assert server.logged_out
    assert ("SELECT", "INBOX", True) in server.commands


def test_the_wrapper_exposes_no_write_commands() -> None:
    allowed = {"login", "select_readonly", "search_uids", "fetch_peek", "logout"}
    public = {n for n in dir(ReadOnlyMailbox) if not n.startswith("_")}
    assert public == allowed
    for forbidden in ("store", "copy", "move", "expunge", "append", "send", "delete", "create"):
        assert forbidden not in public


def test_the_fake_server_really_fails_on_forbidden_commands() -> None:
    server = FakeImap({1: make_eml("s", "b")})
    for call in (
        lambda: server.store("1", "+FLAGS", "\\Seen"),
        lambda: server.expunge(),
        lambda: server.append("INBOX", None, None, b"x"),
        lambda: server.uid("STORE", "1", "+FLAGS", "\\Seen"),
        lambda: server.uid("FETCH", "1", "(BODY[])"),  # not PEEK: would set \Seen
    ):
        with pytest.raises(AssertionError):
            call()


async def test_connection_settings_and_timeout_are_used(monkeypatch) -> None:
    monkeypatch.setenv("IMAP_HOST", "imap.example.invalid")
    monkeypatch.setenv("IMAP_PORT", "1993")
    monkeypatch.setenv("IMAP_TIMEOUT_S", "7")
    get_settings.cache_clear()
    calls = install_fake_imap(monkeypatch, _server())
    await scan_mail(get_settings(), "user", "secret-pw", days=3)
    assert [{k: v for k, v in c.items() if k != "ssl_context"} for c in calls] == [
        {"host": "imap.example.invalid", "port": 1993, "timeout": 7.0}
    ]


async def test_scans_only_the_newest_max_scan_mails(monkeypatch) -> None:
    monkeypatch.setenv("MAIL_MAX_SCAN", "5")
    get_settings.cache_clear()
    server = _server(30)
    install_fake_imap(monkeypatch, server)
    result = await scan_mail(get_settings(), "user", "secret-pw", days=14)
    assert sorted(server.fetched) == [26, 27, 28, 29, 30]
    assert result.scanned == 5 and len(result.mails) == 5


async def test_search_since_uses_english_month_names(monkeypatch) -> None:
    server = _server()
    install_fake_imap(monkeypatch, server)
    await scan_mail(get_settings(), "user", "secret-pw", days=14)
    assert server.searches[0][0] == "SINCE"
    assert server.searches[0][1] == imap_date((datetime.now(UTC) - timedelta(days=14)).date())
    assert imap_date(date(2026, 3, 4)) == "04-Mar-2026"


async def test_query_is_matched_client_side_never_by_server_text_search(monkeypatch) -> None:
    # IITB's server takes 20+ s for a TEXT search on a new word, so we only search by date.
    server = _server(4)
    install_fake_imap(monkeypatch, server)
    result = await scan_mail(get_settings(), "user", "secret-pw", days=14, query="hackathon")
    assert all(args[0] == "SINCE" and "TEXT" not in args for args in server.searches)
    assert {m.message.uid for m in result.mails} == {"1", "3"}
    assert result.scanned == 4
    server.assert_read_only()


async def test_query_words_may_sit_apart(monkeypatch) -> None:
    server = _server(4)
    install_fake_imap(monkeypatch, server)
    result = await scan_mail(get_settings(), "user", "secret-pw", days=14, query="body hackathon")
    # "body hackathon" is not a phrase in any mail, but both words are in mails 1 and 3
    assert {m.message.uid for m in result.mails} == {"1", "3"}


async def test_non_ascii_query_needs_no_server_charset(monkeypatch) -> None:
    server = _server(2)
    install_fake_imap(monkeypatch, server)
    await scan_mail(get_settings(), "user", "secret-pw", days=14, query="café")
    assert all("CHARSET" not in args for args in server.searches)


@pytest.mark.parametrize(
    ("error", "code", "words"),
    [
        (socket.gaierror("dns"), "unreachable", ("VPN",)),
        (ConnectionRefusedError("no"), "unreachable", ("campus", "VPN")),
        (TimeoutError("slow"), "timeout", ("VPN",)),
    ],
)
async def test_network_failures_become_friendly_errors(monkeypatch, error, code, words) -> None:
    def boom(*_a, **_k):
        raise error

    monkeypatch.setattr(imap_client, "IMAP4_SSL", boom)
    with pytest.raises(ConnectorError) as info:
        await scan_mail(get_settings(), "user", "secret-pw", days=3)
    assert info.value.code == code
    assert all(w in info.value.message for w in words)
    assert "secret-pw" not in repr(info.value) and info.value.__cause__ is None


async def test_wrong_password_is_auth_failed_without_leaking_it(monkeypatch) -> None:
    server = _server()
    install_fake_imap(monkeypatch, server)
    with pytest.raises(ConnectorError) as info:
        await scan_mail(get_settings(), "user", "WRONG-pw", days=3)
    assert info.value.code == "auth_failed"
    assert "WRONG-pw" not in info.value.message and "WRONG-pw" not in repr(info.value)
    assert server.logged_out  # we still close the connection


async def test_check_login_logs_in_then_out(monkeypatch) -> None:
    server = _server()
    install_fake_imap(monkeypatch, server)
    await imap_client.check_login(get_settings(), "user", "secret-pw")
    assert [c[0] for c in server.commands] == ["LOGIN", "LOGOUT"]


def test_parse_fetch_response_handles_uid_after_the_literals() -> None:
    data = [
        (b"1 (BODY[HEADER] {20}", b"Subject: hi\r\n\r\n"),
        (b" BODY[TEXT]<0> {4}", b"body"),
        b" UID 9)",
    ]
    (raw,) = imap_client.parse_fetch_response(data)
    assert (raw.uid, raw.text) == ("9", b"body")
