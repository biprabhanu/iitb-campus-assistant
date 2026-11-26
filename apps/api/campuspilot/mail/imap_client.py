"""Read-only IMAP access to IITB Webmail.

The safety idea is simple: `ReadOnlyMailbox` is the *only* object that touches imaplib, and it
only has methods for login, select (read-only), UID SEARCH, UID FETCH with BODY.PEEK, and
logout. There is no method that could store flags, copy, move, delete, append or send, and
BODY.PEEK means a fetch never marks a mail as read. Tests check this against a fake server.

Errors become `ConnectorError` with fixed friendly messages; server text, addresses and
passwords are never put in an exception.
"""

from __future__ import annotations

import asyncio
import contextlib
import imaplib
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote, urlencode

from campuspilot.config import Settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.mail.parsing import ParsedMail, parse_message

IMAP4_SSL = imaplib.IMAP4_SSL  # indirection so tests can swap in a fake server
FETCH_BATCH = 25
HEADER_BYTES_CAP = 20_000
TEXT_BYTES_CAP = 40_000  # how much of the message text we ask the server for

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_UNREACHABLE = (
    "Could not reach IITB Webmail. Connect to the campus network or the IITB VPN and try again."
)
_TIMEOUT = "IITB Webmail took too long to answer. Check the campus network or the IITB VPN."
# IITB's IMAP server does not take the LDAP password: mail apps must log in with an SSO access
# token (sso.iitb.ac.in -> Manage account -> Access tokens -> Emails). Found in live testing on
# 27 Nov 2026 (the LDAP password was rejected) and in public IITB IMAP projects' setup notes.
TOKEN_HELP = "Create one at sso.iitb.ac.in → Manage account → Access tokens → Emails."  # noqa: S105 (help text)
_AUTH = (
    "IITB Webmail rejected the login. Use your LDAP id and an SSO access token for Emails, "
    f"not your LDAP password. {TOKEN_HELP}"
)
_SERVER = "IITB Webmail returned an unexpected answer. Try again in a moment."
_TLS = (
    "Could not open a secure connection to IITB Webmail. The server's security settings may "
    "have changed; CampusPilot did not send your password."
)
_CERT = (
    "IITB Webmail's certificate could not be verified, so CampusPilot did not send your "
    "password. Check that you are on the real campus network or IITB VPN."
)

# Checked live from the campus network on 27 Nov 2026 (no login): imap.iitb.ac.in:993 is a
# "perdition" IMAP proxy that speaks only TLS 1.2 and offers only RSA key-exchange AES-GCM
# ciphers (AES256-GCM-SHA384). Python 3.12's default cipher list leaves RSA key exchange out
# (it has no forward secrecy), so the default handshake fails. We keep every other default
# (certificate and hostname checks stay on) and add just those two ciphers after the modern
# ones, so a server upgrade to ECDHE or TLS 1.3 is picked up automatically.
IMAP_CIPHERS = (
    "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:AES256-GCM-SHA384:AES128-GCM-SHA256"
    ":!aNULL:!eNULL:!MD5:!SHA1"
)


def imap_ssl_context() -> ssl.SSLContext:
    """TLS settings for IITB's IMAP server (see the comment above IMAP_CIPHERS)."""
    context = ssl.create_default_context()  # verifies the certificate and the hostname
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(IMAP_CIPHERS)
    return context


def webmail_link(base_url: str, folder: str, uid: str) -> str | None:
    """A link that opens one mail in IITB's Roundcube webmail ("WM2 IITB").

    Roundcube's message URL is `?_task=mail&_mbox=<folder>&_uid=<uid>&_action=show`. It works
    when Roundcube reads the same IMAP store (same UIDs) as we do; confirm live in Phase 2.
    """
    if not base_url or not uid:
        return None
    query = urlencode(
        {"_task": "mail", "_mbox": folder, "_uid": uid, "_action": "show"}, quote_via=quote
    )
    return f"{base_url.rstrip('/')}/?{query}"


def translate_error(exc: BaseException) -> ConnectorError:
    """Map network / IMAP failures to one friendly ConnectorError (no server text kept)."""
    if isinstance(exc, ConnectorError):
        return exc
    # TimeoutError is a subclass of OSError, so test it first.
    if isinstance(exc, TimeoutError | socket.timeout):
        return ConnectorError("timeout", _TIMEOUT)
    # TLS problems are OSErrors too, but "connect to the VPN" would be the wrong advice.
    if isinstance(exc, ssl.SSLCertVerificationError):
        return ConnectorError("unreachable", _CERT)
    if isinstance(exc, ssl.SSLError):
        return ConnectorError("unreachable", _TLS)
    if isinstance(exc, OSError):  # DNS failure, refused, unreachable network
        return ConnectorError("unreachable", _UNREACHABLE)
    return ConnectorError("unreachable", _SERVER)


def imap_date(day: date) -> str:
    """IMAP wants `27-Nov-2026` with English month names, whatever the system locale."""
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


@dataclass
class RawMail:
    uid: str
    header: bytes
    text: bytes


class SearchRefused(Exception):
    """The server said NO/BAD to a SEARCH (e.g. no TEXT search or no UTF-8)."""


class ReadOnlyMailbox:
    def __init__(self, settings: Settings) -> None:
        self._conn = IMAP4_SSL(
            settings.imap_host,
            settings.imap_port,
            ssl_context=imap_ssl_context(),
            timeout=settings.imap_timeout_s,
        )

    def login(self, username: str, password: str) -> None:
        try:
            self._conn.login(username, password)
        except imaplib.IMAP4.error:
            raise ConnectorError("auth_failed", _AUTH) from None

    def select_readonly(self, folder: str) -> None:
        typ, _ = self._conn.select(folder, readonly=True)
        if typ != "OK":
            raise ConnectorError("unreachable", _SERVER)

    def search_uids(self, since: date) -> list[int]:
        """UIDs (ascending) of mails received since a date.

        We never ask the server to search text. Measured on IITB's server (27 Nov 2026):
        `SEARCH SINCE` over two weeks answers in ~0.1 s, but `SEARCH TEXT` for a word it hasn't
        searched before took over 20 s (it scans every body), which hit our timeout. Fetching
        two weeks of headers + text (~170 mails) and filtering here takes well under a second.
        """
        try:
            typ, data = self._conn.uid("SEARCH", "SINCE", imap_date(since))
        except imaplib.IMAP4.error:
            raise SearchRefused from None
        if typ != "OK":
            raise SearchRefused
        raw = data[0] if data and isinstance(data[0], bytes) else b""
        return sorted(int(x) for x in raw.split() if x.isdigit())

    def fetch_peek(self, uids: list[int]) -> list[RawMail]:
        """Headers plus the first part of the text. BODY.PEEK never sets \\Seen."""
        if not uids:
            return []
        spec = f"(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.{TEXT_BYTES_CAP}>)"
        typ, data = self._conn.uid("FETCH", ",".join(str(u) for u in uids), spec)
        if typ != "OK":
            raise ConnectorError("unreachable", _SERVER)
        return parse_fetch_response(data)

    def logout(self) -> None:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):  # closing is best effort
            self._conn.logout()


def parse_fetch_response(data: list) -> list[RawMail]:
    """Group imaplib's FETCH answer (tuples and trailing bytes) into one RawMail per message."""
    records: list[dict] = []
    for item in data:
        if isinstance(item, tuple):
            desc, literal = item[0], item[1]
            if re.match(rb"\s*\d+ \(", desc):  # "12 (UID 5 BODY[HEADER] {312}" starts a message
                records.append({"uid": None, "header": b"", "text": b""})
            if not records:
                continue
            uid = re.search(rb"UID (\d+)", desc)
            if uid:
                records[-1]["uid"] = uid.group(1).decode()
            if b"BODY[HEADER]" in desc:
                records[-1]["header"] = literal[:HEADER_BYTES_CAP]
            elif b"BODY[TEXT]" in desc:
                records[-1]["text"] = literal
        elif isinstance(item, bytes) and records:
            uid = re.search(rb"UID (\d+)", item)  # some servers put the UID after the literals
            if uid:
                records[-1]["uid"] = uid.group(1).decode()
    return [RawMail(r["uid"], r["header"], r["text"]) for r in records if r["uid"]]


def matches_query(mail: ParsedMail, query: str) -> bool:
    """Client-side fallback search: every word of the query appears somewhere in the mail."""
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    m = mail.message
    haystack = f"{m.subject} {m.sender_name} {m.sender_email} {mail.body}".lower()
    return all(w in haystack for w in words) if words else True


@dataclass
class ScanResult:
    mails: list[ParsedMail]  # newest first
    scanned: int


def _scan(
    settings: Settings, username: str, password: str, *, days: int, query: str | None
) -> ScanResult:
    box = ReadOnlyMailbox(settings)
    try:
        box.login(username, password)
        box.select_readonly(settings.imap_folder)
        since = (datetime.now(UTC) - timedelta(days=days)).date()
        uids = box.search_uids(since)  # date only; the query is matched here (see search_uids)
        newest = uids[-settings.mail_max_scan :]
        mails: list[ParsedMail] = []
        for i in range(0, len(newest), FETCH_BATCH):
            for raw in box.fetch_peek(newest[i : i + FETCH_BATCH]):
                link = webmail_link(settings.webmail_url, settings.imap_folder, raw.uid)
                mails.append(
                    parse_message(
                        raw.header + raw.text,
                        uid=raw.uid,
                        folder=settings.imap_folder,
                        open_url=link,
                    )
                )
        if query:
            mails = [m for m in mails if matches_query(m, query)]
        mails.sort(key=lambda m: m.message.date, reverse=True)
        return ScanResult(mails=mails, scanned=len(newest))
    finally:
        box.logout()


async def scan_mail(
    settings: Settings, username: str, password: str, *, days: int, query: str | None = None
) -> ScanResult:
    try:
        return await asyncio.to_thread(_scan, settings, username, password, days=days, query=query)
    except Exception as exc:
        raise translate_error(exc) from None  # `from None`: the cause could mention the user


def _check(settings: Settings, username: str, password: str) -> None:
    box = ReadOnlyMailbox(settings)
    try:
        box.login(username, password)
    finally:
        box.logout()


async def check_login(settings: Settings, username: str, password: str) -> None:
    """Try an IMAP LOGIN and log out again. Raises ConnectorError on any failure."""
    try:
        await asyncio.to_thread(_check, settings, username, password)
    except Exception as exc:
        raise translate_error(exc) from None
