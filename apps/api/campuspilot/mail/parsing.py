"""Turn raw RFC 5322 bytes into a `ParsedMail` (a `MailMessage` card plus the text we scan).

Mail content is untrusted: we only decode and clean it here. Nothing in this module logs, and
the body text never leaves the process except as the card's <=300 character snippet.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup

from campuspilot.schemas.connectors import MailMessage

SNIPPET_MAX = 300
BODY_MAX_CHARS = 20_000  # the text we keep for rules and the model; the fetch is capped too


@dataclass
class ParsedMail:
    message: MailMessage
    body: str  # plain text, whitespace kept as paragraphs (used for date/venue rules)


def collapse(text: str) -> str:
    return " ".join(text.split())


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    return soup.get_text("\n")


def _body_text(msg: EmailMessage) -> tuple[str, bool]:
    """(text, has_attachments). Prefers text/plain, falls back to HTML converted to text."""
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    text = ""
    for part, is_html in ((plain, False), (html, True)):
        if part is None:
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError, AssertionError):
            continue  # unknown charset or a body cut off by the size cap
        text = _html_to_text(content) if is_html else content
        if text.strip():
            break
    attachments = any(True for _ in msg.iter_attachments())
    # Keep line structure but drop runs of blank lines and trailing spaces.
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned[:BODY_MAX_CHARS], attachments


def _aware_date(msg: EmailMessage, fallback: datetime) -> datetime:
    try:
        parsed = parsedate_to_datetime(str(msg["Date"]))
    except (TypeError, ValueError, IndexError):
        return fallback
    if parsed is None:
        return fallback
    # A date header without a zone is treated as UTC rather than guessed.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_message(
    raw: bytes, *, uid: str, folder: str = "INBOX", open_url: str | None = None
) -> ParsedMail:
    msg = message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    date = _aware_date(msg, fallback=datetime.fromtimestamp(0, UTC))
    name, email_addr = parseaddr(str(msg.get("From", "")))
    subject = collapse(str(msg.get("Subject", "") or ""))
    message_id = collapse(str(msg.get("Message-ID", "") or ""))
    if not message_id:
        # No header: build a stable id from what we do have, so the same mail always maps to
        # the same id (and the same calendar duplicate check).
        digest = hashlib.sha256(f"{folder}|{uid}|{date.isoformat()}".encode()).hexdigest()[:20]
        message_id = f"<synthetic-{digest}@campuspilot.invalid>"
    body, has_attachments = _body_text(msg)
    card = MailMessage(
        uid=uid,
        folder=folder,
        message_id=message_id,
        sender_name=collapse(name),
        sender_email=email_addr.lower(),
        subject=subject,
        date=date,
        snippet=collapse(body)[:SNIPPET_MAX],
        has_attachments=has_attachments,
        open_url=open_url,
    )
    return ParsedMail(message=card, body=body)
