"""A scripted fake LLM with the same interface as the real clients.

Used when CAMPUSPILOT_MOCK_LLM=true and in tests. Keyword rules pick tools; after the
tool results come back, the answer cites exactly the evidence ids it was given.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

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
    if re.search(r"\bdue\b|deadline", low):
        return [ToolCall("get_my_deadlines", {"days_ahead": 7})]
    if "hostel" in low and re.search(r"maintenance|repair|complaint", low):
        return [
            ToolCall("get_official_link", {"topic": "hostel maintenance"}),
            ToolCall("search_campus_docs", {"query": "hostel maintenance complaint"}),
        ]
    if "mess menu" in low and (re.search(r"\b20[3-9]\d\b", low) or "next year" in low):
        return []  # nothing could cover a far-future menu -> abstain
    return [ToolCall("search_campus_docs", {"query": text[:300]})]


def compose_answer(evidence: list[tuple[str, str]]) -> str:
    if not evidence:
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
            return LLMReply(content=compose_answer(evidence))
        calls = _route(_last_user_text(messages))
        if calls:
            return LLMReply(tool_calls=calls)
        return LLMReply(content=_ABSTAIN)

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        _, evidence = _evidence_since_last_user(messages)
        for piece in _pieces(compose_answer(evidence)):
            yield piece
