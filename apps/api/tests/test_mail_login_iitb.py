"""IITB-specific Webmail login details found live on 27 Nov 2026 (lead, Phase 2).

imap.iitb.ac.in:993 accepts only TLS 1.2 with RSA key-exchange AES-GCM ciphers, so the default
Python context fails the handshake. These tests pin the fix and the related error messages.
"""

from __future__ import annotations

import ssl

import pytest

from campuspilot.connectors.errors import ConnectorError
from campuspilot.mail.credentials import normalise_username
from campuspilot.mail.imap_client import (
    imap_ssl_context,
    scan_mail,
    translate_error,
    webmail_link,
)
from campuspilot.mail.tools import mail_login
from campuspilot.schemas.connectors import ConnectorLoginRequest
from tests.mail_helpers import FakeImap, install_fake_imap


def test_context_keeps_verification_and_allows_the_iitb_cipher() -> None:
    context = imap_ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    names = {c["name"] for c in context.get_ciphers()}
    assert "AES256-GCM-SHA384" in names  # the one cipher the IITB server offers
    assert "ECDHE-RSA-AES256-GCM-SHA384" in names  # modern ciphers still come first
    assert not any("NULL" in n or n.endswith("MD5") for n in names)


async def test_mailbox_passes_the_iitb_context(monkeypatch) -> None:
    calls = install_fake_imap(monkeypatch, FakeImap())
    await scan_mail(_s(), "user", "secret-pw", days=1)
    assert isinstance(calls[0]["ssl_context"], ssl.SSLContext)
    assert calls[0]["ssl_context"].minimum_version == ssl.TLSVersion.TLSv1_2


def _s():
    from campuspilot.config import get_settings

    return get_settings()


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (ssl.SSLError(1, "handshake failure"), ("secure connection", "did not send")),
        (ssl.SSLCertVerificationError(1, "bad cert"), ("certificate", "did not send")),
    ],
)
def test_tls_failures_do_not_blame_the_vpn(error, words) -> None:
    result = translate_error(error)
    assert isinstance(result, ConnectorError) and result.code == "unreachable"
    assert all(w in result.message for w in words)
    assert "handshake" not in result.message and "bad cert" not in result.message


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("  student01 ", "student01"),
        ("student01@iitb.ac.in", "student01"),
        ("Student01@IITB.AC.IN", "Student01"),
        ("someone@cse.iitb.ac.in", "someone@cse.iitb.ac.in"),
    ],
)
def test_username_is_the_ldap_id(typed, expected) -> None:
    assert normalise_username(typed) == expected


async def test_login_stores_the_ldap_id(monkeypatch, memory_keyring) -> None:
    server = FakeImap()
    server.valid = ("student01", "pw-123")  # the fake server only knows the bare LDAP id
    install_fake_imap(monkeypatch, server)
    status = await mail_login(
        ConnectorLoginRequest(username="student01@iitb.ac.in", password="pw-123")
    )
    assert status.state == "connected" and status.account == "student01"
    assert memory_keyring.store[("campuspilot", "webmail_username")] == "student01"


def test_roundcube_link() -> None:
    link = webmail_link("https://webmail.iitb.ac.in/", "INBOX", "4321")
    assert link == "https://webmail.iitb.ac.in/?_task=mail&_mbox=INBOX&_uid=4321&_action=show"
    assert webmail_link("https://webmail.iitb.ac.in", "Lists/Gym Khana", "7").endswith(
        "_mbox=Lists%2FGym%20Khana&_uid=7&_action=show"
    )
    assert webmail_link("", "INBOX", "1") is None
