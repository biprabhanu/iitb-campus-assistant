"""Parsing raw mail bytes into MailMessage cards."""

from __future__ import annotations

from datetime import UTC, datetime

from campuspilot.mail.parsing import parse_message
from tests.mail_helpers import make_eml


def test_basic_fields() -> None:
    raw = make_eml(
        "Hello   there",
        "Body line.",
        sender="Asha Demo <ASHA.Demo@Example.com>",
        message_id="<abc@example.org>",
        date=datetime(2026, 11, 27, 9, 0, tzinfo=UTC),
    )
    parsed = parse_message(raw, uid="42", folder="INBOX")
    m = parsed.message
    assert (m.uid, m.folder, m.message_id) == ("42", "INBOX", "<abc@example.org>")
    assert (m.sender_name, m.sender_email) == ("Asha Demo", "asha.demo@example.com")
    assert m.subject == "Hello there"  # whitespace collapsed
    assert m.date == datetime(2026, 11, 27, 9, 0, tzinfo=UTC) and m.date.tzinfo is not None
    assert m.open_url is None  # no reliable webmail link format is known yet


def test_encoded_headers_are_decoded() -> None:
    raw = (
        b"From: =?utf-8?B?QXNoYSBEw6ltbw==?= <asha@example.com>\r\n"
        b"Subject: =?utf-8?Q?Caf=C3=A9_talk?=\r\n"
        b"Message-ID: <x@example.com>\r\nDate: Fri, 27 Nov 2026 09:00:00 +0530\r\n\r\nhi"
    )
    m = parse_message(raw, uid="1").message
    assert m.sender_name == "Asha Démo" and m.subject == "Café talk"
    assert m.date.utcoffset().total_seconds() == 5.5 * 3600


def test_snippet_is_collapsed_and_capped() -> None:
    body = "word   " * 200 + "\n\n\n\nend"
    m = parse_message(make_eml("s", body), uid="1").message
    assert len(m.snippet) == 300 and "  " not in m.snippet and "\n" not in m.snippet


def test_html_is_converted_and_scripts_dropped() -> None:
    html = "<html><head><style>p{}</style></head><body><script>evil()</script><p>Hi <b>all</b></p></body></html>"
    parsed = parse_message(make_eml("s", html, html=True), uid="1")
    assert "Hi" in parsed.body and "evil" not in parsed.body and "p{}" not in parsed.body


def test_attachment_flag() -> None:
    assert parse_message(make_eml("s", "b", attachment=True), uid="1").message.has_attachments
    assert not parse_message(make_eml("s", "b"), uid="1").message.has_attachments


def test_missing_message_id_gets_a_stable_synthetic_one() -> None:
    raw = make_eml("s", "b", message_id=None, date=datetime(2026, 11, 27, tzinfo=UTC))
    first = parse_message(raw, uid="7").message.message_id
    assert first == parse_message(raw, uid="7").message.message_id
    assert first != parse_message(raw, uid="8").message.message_id
    assert first.startswith("<synthetic-")


def test_naive_or_missing_date_still_gives_an_aware_datetime() -> None:
    naive = parse_message(b"Subject: s\r\nDate: Fri, 27 Nov 2026 09:00:00\r\n\r\nb", uid="1")
    missing = parse_message(b"Subject: s\r\n\r\nb", uid="1")
    assert naive.message.date.tzinfo is not None and missing.message.date.tzinfo is not None


def test_truncated_or_odd_bodies_do_not_crash() -> None:
    raw = (
        b"Subject: s\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=XX\r\n\r\n"
        b"--XX\r\nContent-Type: text/plain; charset=nonsense-9\r\n\r\ncut off here"
    )
    assert parse_message(raw, uid="1").message.subject == "s"
