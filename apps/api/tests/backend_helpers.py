"""Shared helpers for the backend tests: fake tools, a scripted LLM, an SSE parser."""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from campuspilot.llm.base import LLMReply, Message, ToolCall
from campuspilot.schemas.tools import (
    Deadline,
    DocChunkHit,
    GetMyDeadlinesOutput,
    GetOfficialLinkOutput,
    OfficialLink,
    SearchCampusDocsOutput,
)

OLLAMA = "http://127.0.0.1:11500"


def make_hit(
    chunk_id: int = 1, text: str = "Classes begin on 3 August.", **extra: Any
) -> DocChunkHit:
    fields: dict[str, Any] = {
        "chunk_id": chunk_id,
        "source_id": "cal",
        "document_id": 1,
        "title": "Academic Calendar",
        "issuer": "Academic Office",
        "url": "https://www.iitb.ac.in/cal.pdf",
        "heading_path": "Autumn",
        "page": 2,
        "text": text,
        "audience": "all",
        "authority_tier": 1,
        "checked_at": "2026-11-01",
        "published_at": "2026-05-10",
        "score": 3.0,
    }
    fields.update(extra)
    return DocChunkHit(**fields)


def install_fake_tools(monkeypatch, hits=None, links=None, deadlines=None, moodle_error=None):
    """Replace the retrieval and Moodle tool modules with fakes. Returns a call recorder."""
    calls = SimpleNamespace(search=[], link=[], deadlines=[])
    hit_list = [make_hit()] if hits is None else hits

    def search_campus_docs(args, db_path=None):
        calls.search.append(args)
        return SearchCampusDocsOutput(hits=hit_list)

    def get_official_link(args, db_path=None):
        calls.link.append(args)
        found = (
            links
            if links is not None
            else [
                OfficialLink(
                    source_id="hos",
                    title="Hostel Office",
                    issuer="Hostel Affairs",
                    url="https://www.iitb.ac.in/hostel",
                    category="hostel",
                    notes="Hostel help",
                )
            ]
        )
        return GetOfficialLinkOutput(links=found)

    class MoodleError(Exception):
        def __init__(self, code: str, message: str) -> None:
            super().__init__(message)
            self.code, self.message = code, message

    async def get_my_deadlines(args):
        calls.deadlines.append(args)
        if moodle_error:
            raise MoodleError("unavailable", moodle_error)
        from datetime import UTC, datetime

        items = (
            deadlines
            if deadlines is not None
            else [
                Deadline(
                    id="assign-1",
                    title="Quiz 2",
                    course="IE624",
                    due_at=datetime(2026, 11, 28, 17, 0, tzinfo=UTC),
                    kind="assignment",
                )
            ]
        )
        return GetMyDeadlinesOutput(deadlines=items, mode="demo", demo=True)

    async def moodle_status():
        return "connected", "demo"

    retrieval = SimpleNamespace(
        search_campus_docs=search_campus_docs,
        get_official_link=get_official_link,
        count_indexed_sources=lambda db_path=None: 7,
        list_sources=lambda db_path=None: [],
    )
    moodle = SimpleNamespace(
        get_my_deadlines=get_my_deadlines,
        moodle_status=moodle_status,
        MoodleError=MoodleError,
    )
    monkeypatch.setitem(sys.modules, "campuspilot.retrieval.tools", retrieval)
    monkeypatch.setitem(sys.modules, "campuspilot.moodle.tools", moodle)
    return calls


class ScriptedLLM:
    """Plays back prepared replies. `stream_text` is what stream() yields in pieces."""

    def __init__(
        self, replies: list[LLMReply], stream_pieces: list[str] | None = None, mode: str = "live"
    ) -> None:
        self.mode = mode
        self.model = "scripted"
        self._replies = list(replies)
        self._stream_pieces = stream_pieces or []
        self.chat_calls: list[tuple[list[Message], list[dict[str, Any]] | None]] = []
        self.stream_calls = 0

    async def chat(self, messages, tools):
        self.chat_calls.append((list(messages), tools))
        return self._replies.pop(0) if self._replies else LLMReply(content="done")

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        self.stream_calls += 1
        for piece in self._stream_pieces:
            yield piece


def call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(name=name, arguments=arguments)


def parse_sse(text: str) -> list[tuple[str, Any]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        events.append(
            (lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: ")))
        )
    return events


def names(events: list[tuple[str, Any]]) -> list[str]:
    return [name for name, _ in events]


def answer_text(events: list[tuple[str, Any]]) -> str:
    return "".join(data["text"] for name, data in events if name == "token")


def done_of(events: list[tuple[str, Any]]) -> dict[str, Any]:
    return next(data for name, data in events if name == "done")


def ndjson(*objects: dict[str, Any]) -> bytes:
    return "\n".join(json.dumps(o) for o in objects).encode() + b"\n"
