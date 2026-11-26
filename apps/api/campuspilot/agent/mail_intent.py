"""Is this question about the student's own mail? (v2 Webmail, local mode only)

Used in two places:
- the orchestrator: when Webmail is on and the question is about mail, the turn uses the mail
  tools only and never answers from campus documents (owner rule, 27 Nov 2026);
- the scripted MockLLM, so mock mode routes mail questions like the real model should.

Plain keyword rules, kept simple on purpose. "latest" or "from X" alone are not enough (think
"latest academic calendar" or "fees from the accounts office"); they only matter together with
a clear mail word.
"""

from __future__ import annotations

import re

# Clear signs the student means their mailbox.
_MAIL_WORDS = re.compile(
    r"\b(web\s?mail|e-?mails?|mails?|mailbox|inbox|msgs?|messages?|unread)\b", re.IGNORECASE
)
_UNREAD = re.compile(r"\bunread\b", re.IGNORECASE)
_SUMMARY = re.compile(r"\bsummar", re.IGNORECASE)
# What to search for: "from <sender>", "about / regarding / on / for <topic>".
_FROM = re.compile(r"\bfrom\s+(?:the\s+)?([\w .&'-]{2,60})", re.IGNORECASE)
_TOPIC = re.compile(
    r"\b(?:about|regarding|re|on|for|mentioning|with)\s+(?:the\s+)?([\w .&'-]{2,60})",
    re.IGNORECASE,
)
# Words that are about the request, not the thing searched for.
_FILLER = re.compile(
    r"\b(this|last|past|next)\s+(week|month|few days|days?)\b|\b(today|yesterday|recently|"
    r"please|pls|in my|my|inbox|mails?|e-?mails?|web\s?mail|msgs?|messages?|any|anything|"
    r"did i get|have i got|got|received|sent me|send me)\b",
    re.IGNORECASE,
)


def is_mail_question(text: str) -> bool:
    return bool(_MAIL_WORDS.search(text))


def wants_unread(text: str) -> bool:
    return bool(_UNREAD.search(text))


def wants_summary(text: str) -> bool:
    return bool(_SUMMARY.search(text))


def _clean(fragment: str) -> str:
    fragment = _FILLER.sub(" ", fragment)
    fragment = re.sub(r"[?.!,]+", " ", fragment)
    return " ".join(fragment.split())[:200]


def mail_query(text: str) -> str | None:
    """The sender or topic to search for, or None when the student just wants recent mail."""
    for pattern in (_FROM, _TOPIC):
        match = pattern.search(text)
        if match:
            query = _clean(match.group(1))
            if query:
                return query
    return None


def mail_tool_call(text: str) -> tuple[str, dict]:
    """The read-only mail tool (name, arguments) a mail question should use."""
    query = mail_query(text)
    if query is None or (wants_unread(text) and not _FROM.search(text)):
        return "list_recent_mail", {"limit": 10, "unread_only": wants_unread(text)}
    return "search_my_mail", {"query": query, "days": 14, "summarize": wants_summary(text)}
