"""Shared fakes for the Webmail tests: synthetic mails, a fake IMAP server, a scripted model.

Everything here is made up (example.org addresses). Nothing connects to a real server.
"""

from __future__ import annotations

import imaplib
import re
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from campuspilot.llm.base import LLMReply
from campuspilot.mail import imap_client

SENDER = "Gymkhana Events <gymkhana-events@example.org>"
FRIEND = "Asha Demo <asha.demo@example.com>"


def day_text(delta_days: int) -> str:
    """e.g. '3 December' for three days from today (IST date, like the app uses)."""
    from campuspilot.mail.events import IST

    day = datetime.now(IST).date() + timedelta(days=delta_days)
    return f"{day.day} {day:%B}"


def make_eml(
    subject: str,
    body: str,
    *,
    sender: str = SENDER,
    date: datetime | None = None,
    message_id: str | None = "auto",
    html: bool = False,
    attachment: bool = False,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "student@example.org"
    msg["Subject"] = subject
    if message_id == "auto":
        message_id = f"<{abs(hash((subject, body))) % 10**10}@example.org>"
    if message_id:
        msg["Message-ID"] = message_id
    msg["Date"] = format_datetime(date or datetime.now(UTC) - timedelta(hours=2))
    if html:
        msg.set_content("fallback")
        msg.replace_header("Content-Type", "text/html; charset=utf-8")
        msg.set_payload(body)
    else:
        msg.set_content(body)
    if attachment:
        msg.add_attachment(b"%PDF-fake", maintype="application", subtype="pdf", filename="a.pdf")
    return msg.as_bytes()


class FakeImap:
    """Stands in for imaplib.IMAP4_SSL and records every command that reaches the 'server'.

    Any command outside login / select / UID SEARCH / UID FETCH-with-PEEK / logout fails the
    test immediately, and fetched mails stay unread (no \\Seen flag is ever set)."""

    def __init__(self, mails: dict[int, bytes] | None = None) -> None:
        self.mails = dict(mails or {})
        self.flags: dict[int, set[str]] = {uid: set() for uid in self.mails}
        self.seen: dict[int, set[str]] = {}  # mails already read before the test (server state)
        self.commands: list[tuple] = []
        self.fetched: list[int] = []
        self.searches: list[tuple] = []
        self.refuse_text = False
        self.login_error: Exception | None = None
        self.valid = ("user", "secret-pw")
        self.selected_readonly: bool | None = None
        self.logged_out = False

    # --- the commands the app is allowed to use ---
    def login(self, user: str, password: str) -> tuple[str, list]:
        self.commands.append(("LOGIN",))  # never record the credentials
        if self.login_error:
            raise self.login_error
        if (user, password) != self.valid:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] bad credentials")
        return "OK", [b"logged in"]

    def select(self, folder: str = "INBOX", readonly: bool = False) -> tuple[str, list]:
        self.commands.append(("SELECT", folder, readonly))
        self.selected_readonly = readonly
        assert readonly is True, "mailbox must be opened read-only"
        return "OK", [str(len(self.mails)).encode()]

    def uid(self, command: str, *args: Any) -> tuple[str, list]:
        command = command.upper()
        self.commands.append(("UID", command))
        assert command in ("SEARCH", "FETCH"), f"forbidden UID command {command}"
        if command == "SEARCH":
            return self._search(args)
        return self._fetch(*args)

    def logout(self) -> tuple[str, list]:
        self.commands.append(("LOGOUT",))
        self.logged_out = True
        return "BYE", [b"bye"]

    # --- internals ---
    def _search(self, args: tuple) -> tuple[str, list]:
        self.searches.append(args)
        uids = sorted(self.mails)
        if "UNSEEN" in args:  # reading flags only; the test sets `seen` to mark some as read
            uids = [u for u in uids if "\\Seen" not in self.seen.get(u, set())]
        if "TEXT" in args:
            if self.refuse_text:
                return "NO", [b"TEXT not supported"]
            raw = args[args.index("TEXT") + 1]
            needle = (raw.decode() if isinstance(raw, bytes) else raw).strip('"').lower()
            uids = [u for u in uids if needle in self.mails[u].decode(errors="ignore").lower()]
        return "OK", [" ".join(str(u) for u in uids).encode()]

    def _fetch(self, uid_set: str, spec: str) -> tuple[str, list]:
        assert "PEEK" in spec and not re.search(r"BODY\[", spec), f"non-peek fetch: {spec}"
        assert "RFC822" not in spec and "FLAGS" not in spec
        data: list = []
        for seq, uid in enumerate(int(u) for u in uid_set.split(",")):
            raw = self.mails.get(uid)
            if raw is None:
                continue
            self.fetched.append(uid)
            head, _, text = raw.partition(b"\r\n\r\n")
            head += b"\r\n\r\n"
            data.append((f"{seq + 1} (UID {uid} BODY[HEADER] {{{len(head)}}}".encode(), head))
            data.append((f" BODY[TEXT]<0> {{{len(text)}}}".encode(), text))
            data.append(b")")
        return "OK", data

    # Any other imaplib method a careless change might call is an immediate test failure.
    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"forbidden IMAP call: {name}")

    # --- assertions ---
    def assert_read_only(self) -> None:
        names = {c[1] if c[0] == "UID" else c[0] for c in self.commands}
        assert names <= {"LOGIN", "SELECT", "SEARCH", "FETCH", "LOGOUT"}, names
        assert all(not flags for flags in self.flags.values()), "a mail was flagged"
        assert self.selected_readonly is True


def install_fake_imap(monkeypatch, server: FakeImap) -> list[dict]:
    """Make the mail module use `server`. Returns the list of constructor calls."""
    calls: list[dict] = []

    def factory(host: str, port: int, ssl_context=None, timeout: float | None = None) -> FakeImap:
        calls.append({"host": host, "port": port, "timeout": timeout, "ssl_context": ssl_context})
        return server

    monkeypatch.setattr(imap_client, "IMAP4_SSL", factory)
    return calls


class ScriptedLLM:
    """A model that returns canned text and records what it was asked."""

    mode = "live"
    model = "scripted"

    def __init__(self, replies: list[str] | str = "", *, error: Exception | None = None) -> None:
        self.replies = [replies] if isinstance(replies, str) else list(replies)
        self.error = error
        self.calls: list[tuple[list[dict], Any]] = []

    async def chat(self, messages, tools):
        self.calls.append((messages, tools))
        if self.error:
            raise self.error
        reply = self.replies.pop(0) if len(self.replies) > 1 else (self.replies or [""])[0]
        return LLMReply(content=reply)

    def stream(self, messages):  # never used by the mail module
        raise AssertionError("the mail module must not stream")


def use_llm(monkeypatch, llm: Any) -> None:
    """Make the mail tools see `llm` as the allowed local model (or None)."""
    from campuspilot.mail import tools

    async def fake(_settings):
        return llm

    monkeypatch.setattr(tools, "personal_data_llm", fake)
