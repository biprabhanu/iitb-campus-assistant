"""A scripted fake LLM with the same interface as the real clients.

Used when CAMPUSPILOT_MOCK_LLM=true and in tests. Keyword rules pick tools; after the
tool results come back, the answer cites exactly the evidence ids it was given.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from campuspilot.agent.asc_intent import asc_tool_call
from campuspilot.agent.mail_intent import is_mail_question, mail_tool_call
from campuspilot.llm.base import LLMReply, Message, ToolCall

_EVIDENCE_RE = re.compile(r'<evidence id="([SM]\d+)"[^>]*>\s*(.*?)\s*</evidence>', re.DOTALL)
_ABSTAIN = (
    "ABSTAIN: I could not find this in the official sources I have. "
    "Please check the relevant office or portal directly."
)


def _last_user_text(messages: list[Message]) -> str:
    for msg in reversed(messages):
        if msg["role"] == "user":
            return msg["content"]
    return ""


def _evidence_since_last_user(messages: list[Message]) -> tuple[bool, list[tuple[str, str]]]:
    """(did tools already run this turn?, [(evidence id, text), ...])."""
    index = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=0)
    tool_msgs = [m for m in messages[index:] if m["role"] == "tool"]
    found = [
        (eid, " ".join(text.split()))
        for m in tool_msgs
        for eid, text in _EVIDENCE_RE.findall(m["content"])
    ]
    return bool(tool_msgs), found


def _route(text: str) -> list[ToolCall]:
    """Keyword rules: question text -> tool calls (empty list means 'answer now')."""
    low = text.lower()
    if "change my room" in low:
        return [
            ToolCall(
                "ask_clarification",
                {
                    "question": "Which hostel category are you in?",
                    "options": ["UG hostel", "PG hostel", "PhD/married hostel"],
                },
            )
        ]
    asc = None if is_mail_question(text) else asc_tool_call(text)
    if asc:  # "amount due" is a fee question, not a Moodle deadline
        return [ToolCall(*asc)]
    if re.search(r"\bdue\b|deadline", low):
        # The mail call is dropped by the orchestrator when Webmail is off (not offered).
        return [
            ToolCall("get_my_deadlines", {"days_ahead": 7}),
            ToolCall("get_upcoming_institute_events", {"days": 7, "only_deadlines": True}),
        ]
    connector = _route_connectors(low, text)
    if connector:
        return connector
    if "hostel" in low and re.search(r"maintenance|repair|complaint", low):
        return [
            ToolCall("get_official_link", {"topic": "hostel maintenance"}),
            ToolCall("search_campus_docs", {"query": "hostel maintenance complaint"}),
        ]
    return [ToolCall("search_campus_docs", {"query": text[:300]})]


def _route_connectors(low: str, text: str) -> list[ToolCall]:
    """v2 connector questions (only reached when the connectors are on; see CONTRACT §11)."""
    if "event" in low and re.search(r"mail|institute", low):
        return [ToolCall("get_upcoming_institute_events", {"days": 7})]
    if is_mail_question(text):  # "check my webmail latest msg", "any mail from gymkhana"...
        name, args = mail_tool_call(text)
        return [ToolCall(name, args)]
    asc = asc_tool_call(text)  # grades match nothing: no ASC tool reads them
    if asc:
        return [ToolCall(*asc)]
    return []


def _unanswerable(text: str) -> bool:
    """A far-future mess menu can't be in any source, whatever the search returns."""
    low = text.lower()
    return "mess menu" in low and bool(re.search(r"\b20[3-9]\d\b|next year", low))


def compose_answer(evidence: list[tuple[str, str]], question: str = "") -> str:
    if not evidence or _unanswerable(question):
        return _ABSTAIN
    lines = ["Here is what the sources say:"]
    for eid, text in evidence[:3]:
        short = text if len(text) <= 160 else text[:157] + "..."
        lines.append(f"- {short} [{eid}]")
    return "\n".join(lines)


def _pieces(text: str, size: int = 24) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


class MockLLM:
    mode = "mock"
    model = "mock-llm"

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None) -> LLMReply:
        tools_ran, evidence = _evidence_since_last_user(messages)
        if tools_ran:
            return LLMReply(content=compose_answer(evidence, _last_user_text(messages)))
        calls = _route(_last_user_text(messages))
        if calls:
            return LLMReply(tool_calls=calls)
        return LLMReply(content=_ABSTAIN)

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        _, evidence = _evidence_since_last_user(messages)
        for piece in _pieces(compose_answer(evidence, _last_user_text(messages))):
            yield piece
