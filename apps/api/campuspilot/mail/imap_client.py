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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

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
_AUTH = "IITB Webmail rejected the username or password."
_SERVER = "IITB Webmail returned an unexpected answer. Try again in a moment."


def translate_error(exc: BaseException) -> ConnectorError:
    """Map network / IMAP failures to one friendly ConnectorError (no server text kept)."""
    if isinstance(exc, ConnectorError):
        return exc
    # TimeoutError is a subclass of OSError, so test it first.
    if isinstance(exc, TimeoutError | socket.timeout):
        return ConnectorError("timeout", _TIMEOUT)
    if isinstance(exc, OSError):  # DNS failure, refused, unreachable network, TLS failure
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
            settings.imap_host, settings.imap_port, timeout=settings.imap_timeout_s
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

    def search_uids(self, since: date, text: str | None = None) -> list[int]:
        """UIDs (ascending) of mails since a date, optionally filtered by the server on TEXT."""
        args: list[str | bytes] = []
        if text:
            safe = text.replace("\\", " ").replace('"', " ").strip()
            quoted = f'"{safe}"'
            if safe.isascii():
                args = ["SINCE", imap_date(since), "TEXT", quoted]
            else:
                # A non-ASCII term needs a declared charset and raw UTF-8 bytes.
                args = ["CHARSET", "UTF-8", "SINCE", imap_date(since), "TEXT", quoted.encode()]
        else:
            args = ["SINCE", imap_date(since)]
        try:
            typ, data = self._conn.uid("SEARCH", *args)
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
        uids: list[int] = []
        client_filter = False
        if query:
            with contextlib.suppress(SearchRefused):
                uids = box.search_uids(since, query)
            # Refused, or a phrase that matched nothing (the words may sit apart): filter
            # client-side over a plain SINCE scan instead.
            client_filter = not uids
        if not query or client_filter:
            uids = box.search_uids(since)
        newest = uids[-settings.mail_max_scan :]
        mails: list[ParsedMail] = []
        for i in range(0, len(newest), FETCH_BATCH):
            for raw in box.fetch_peek(newest[i : i + FETCH_BATCH]):
                mails.append(
                    parse_message(raw.header + raw.text, uid=raw.uid, folder=settings.imap_folder)
                )
        if query and client_filter:
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
