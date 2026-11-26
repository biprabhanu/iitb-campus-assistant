"""The chat loop (MASTER_BUILD_PROMPT §5.2, CONTRACT §3, §5, §6).

`run_chat` is an async generator of (event_name, json_payload) pairs. The API layer
turns them into Server-Sent Events; tests can read them directly.

Steps: ask the model which tools to use -> run them (validated, time-limited, max 4)
-> send `sources` -> stream the answer (abstain prefix and bad citations stripped) -> `done`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from campuspilot.agent.citations import CitationFilter
from campuspilot.agent.prompts import build_system_prompt
from campuspilot.config import Settings, get_settings
from campuspilot.llm.base import LLMClient, LLMError, LLMReply, Message, ModelOffline, ModelTimeout
from campuspilot.schemas.chat import (
    ChatRequest,
    DoneEvent,
    ErrorEvent,
    FollowUp,
    OfficeLink,
    StatusEvent,
    ToolEvent,
)
from campuspilot.schemas.tools import GetOfficialLinkInput, GetOfficialLinkOutput
from campuspilot.tools.evidence import EvidenceStore
from campuspilot.tools.registry import (
    TOOLS,
    AskClarificationInput,
    ToolFailure,
    ToolSpec,
    offered_tools,
    tool_schemas,
)

log = logging.getLogger("campuspilot.agent")

Event = tuple[str, Any]
FRESH_DAYS = 400
OFFLINE_TEXT = (
    "The CampusPilot model is offline right now. Check the tunnel "
    "(`ssh -fN passpoli-llm`) and try again."
)
TIMEOUT_TEXT = "The model took too long to answer. Please try again."


@dataclass
class RunTrace:
    """What the API logs after a request (never message text)."""

    request_id: str
    model: str = ""
    mode: str = ""
    tools: list[str] = field(default_factory=list)
    chunk_ids: list[int] = field(default_factory=list)
    error_code: str | None = None
    latency_ms: int = 0


@dataclass
class ToolOutcome:
    ok: bool
    content: str  # goes back to the model as the tool message
    limitation: str | None = None
    links: list[OfficeLink] = field(default_factory=list)
    follow_up: FollowUp | None = None


# ---------- small helpers ----------


def chunk_text(text: str, size: int = 20) -> list[str]:
    """Split text into small pieces so a non-streamed reply still looks streamed."""
    return [text[i : i + size] for i in range(0, len(text), size)]


class AbstainFilter:
    """Detects and removes a leading 'ABSTAIN:' from streamed text."""

    PREFIX = "ABSTAIN:"

    def __init__(self) -> None:
        self.abstained = False
        self._decided = False
        self._buf = ""

    def feed(self, text: str) -> str:
        if self._decided:
            return text
        self._buf += text
        head = self._buf.lstrip()
        if len(head) < len(self.PREFIX) and self.PREFIX.startswith(head):
            return ""  # could still become the prefix; wait
        self._decided = True
        buf, self._buf = self._buf, ""
        if head.startswith(self.PREFIX):
            self.abstained = True
            return head[len(self.PREFIX) :].lstrip()
        return buf

    def flush(self) -> str:
        buf, self._buf = self._buf, ""
        self._decided = True
        return buf


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def compute_freshness(cited: list[str], store: EvidenceStore, today: date) -> str:
    """CONTRACT §3: current / needs_review / unknown, judged on the cited docs."""
    if not cited:
        return "unknown"
    for evidence_id in cited:
        item = store.get(evidence_id)
        if item is None or item.kind != "doc":
            continue
        dates = [d for d in (_parse_date(item.published), _parse_date(item.checked_at)) if d]
        if not any((today - d).days <= FRESH_DAYS for d in dates):
            return "needs_review"
    return "current"


def _note(text: str) -> str:
    return f"<note>{text}</note>"


# ---------- running one tool ----------


async def _execute_tool(
    spec: ToolSpec, arguments: dict[str, Any], store: EvidenceStore, timeout_s: float
) -> ToolOutcome:
    try:
        args = spec.input_model.model_validate(arguments)
    except ValidationError as exc:
        fields = ", ".join(sorted({str(e["loc"][0]) if e["loc"] else "?" for e in exc.errors()}))
        note = _note(f"Tool {spec.name} was called with invalid arguments (check: {fields}).")
        return ToolOutcome(False, note, f"A tool call had invalid arguments ({spec.name}).")
    try:
        output = await asyncio.wait_for(spec.run(args), timeout=timeout_s)
    except TimeoutError:
        return ToolOutcome(False, _note(f"{spec.name} timed out."), f"{spec.label} timed out.")
    except ToolFailure as exc:
        return ToolOutcome(False, _note(str(exc)), str(exc))
    except Exception as exc:
        log.warning(
            "tool %s failed: %s", spec.name, type(exc).__name__
        )  # no details: may be private
        return ToolOutcome(
            False, _note(f"{spec.name} is unavailable right now."), f"{spec.label} failed."
        )
    return _success_outcome(spec, output, store)


def _success_outcome(spec: ToolSpec, output: Any, store: EvidenceStore) -> ToolOutcome:
    if isinstance(output, AskClarificationInput):
        return ToolOutcome(
            True, "", follow_up=FollowUp(question=output.question, options=output.options)
        )
    assert spec.to_evidence is not None
    items, note = spec.to_evidence(output)
    added = store.add(items)
    parts = [item.to_block() for item in added] or ["No matching results found."]
    if note:
        parts.append(_note(note))
    links: list[OfficeLink] = []
    if isinstance(output, GetOfficialLinkOutput):
        links = [OfficeLink(title=x.title, url=x.url, issuer=x.issuer) for x in output.links]
    return ToolOutcome(True, "\n".join(parts), links=links)


async def _lookup_office_links(topic: str, timeout_s: float) -> list[OfficeLink]:
    """On abstain, find the office/portal ourselves if the model didn't."""
    try:
        args = GetOfficialLinkInput(topic=topic[:200])
        output = await asyncio.wait_for(TOOLS["get_official_link"].run(args), timeout=timeout_s)
    except Exception:
        return []
    return [OfficeLink(title=x.title, url=x.url, issuer=x.issuer) for x in output.links]


# ---------- the main loop ----------


async def run_chat(
    request: ChatRequest,
    llm: LLMClient,
    trace: RunTrace,
    settings: Settings | None = None,
    today: date | None = None,
) -> AsyncIterator[Event]:
    started = time.monotonic()
    settings = settings or get_settings()
    trace.model, trace.mode = llm.model, llm.mode
    yield (
        "status",
        StatusEvent(request_id=trace.request_id, model=llm.model, mode=llm.mode).model_dump(
            mode="json"
        ),
    )
    try:
        async for event in _run(request, llm, trace, settings, today or date.today(), started):
            yield event
    except ModelOffline:
        yield _error(trace, "MODEL_OFFLINE", OFFLINE_TEXT)
    except ModelTimeout:
        yield _error(trace, "TIMEOUT", TIMEOUT_TEXT)
    except LLMError:
        yield _error(trace, "INTERNAL", "The model returned an error. Please try again.")
    except Exception as exc:
        log.error("chat failed: %s", type(exc).__name__)
        yield _error(trace, "INTERNAL", "Something went wrong on our side. Please try again.")
    trace.latency_ms = int((time.monotonic() - started) * 1000)


def _error(trace: RunTrace, code: str, message: str) -> Event:
    trace.error_code = code
    return "error", ErrorEvent(code=code, message=message).model_dump(mode="json")  # type: ignore[arg-type]


async def _run(
    request: ChatRequest,
    llm: LLMClient,
    trace: RunTrace,
    settings: Settings,
    today: date,
    started: float,
) -> AsyncIterator[Event]:
    store = EvidenceStore()
    limitations: list[str] = []
    office_links: list[OfficeLink] = []
    specs = offered_tools(llm.mode, settings.allow_personal_data_to_cloud)
    by_name = {s.name: s for s in specs}
    schemas = tool_schemas(specs)

    history = request.history[-settings.max_history_turns :]
    messages: list[Message] = [{"role": "system", "content": build_system_prompt(today)}]
    messages += [{"role": t.role, "content": t.content} for t in history]
    messages.append({"role": "user", "content": request.message})

    executed = 0
    final_reply: LLMReply | None = None
    follow_up: FollowUp | None = None

    while executed < settings.max_tool_calls and follow_up is None:
        reply = await llm.chat(messages, schemas)
        if not reply.tool_calls:
            final_reply = reply
            break
        messages.append(
            {
                "role": "assistant",
                "content": reply.content,
                "tool_calls": [
                    {"function": {"name": c.name, "arguments": c.arguments}}
                    for c in reply.tool_calls
                ],
            }
        )
        for call in reply.tool_calls:
            if executed >= settings.max_tool_calls:
                note = (
                    f"Only {settings.max_tool_calls} tool calls are allowed per question; "
                    "extra calls were ignored."
                )
                if note not in limitations:
                    limitations.append(note)
                break
            executed += 1
            spec = by_name.get(call.name)
            if spec is None:  # unknown, or hidden from this mode
                content = _note(f"Tool {call.name!r} is not available.")
                messages.append({"role": "tool", "tool_name": call.name, "content": content})
                continue
            trace.tools.append(spec.name)
            yield "tool", ToolEvent(name=spec.name, label=spec.label, state="start").model_dump()
            outcome = await _execute_tool(spec, call.arguments, store, settings.tool_timeout_s)
            state = "done" if outcome.ok else "error"
            yield "tool", ToolEvent(name=spec.name, label=spec.label, state=state).model_dump()
            if outcome.limitation:
                limitations.append(outcome.limitation)
            office_links.extend(outcome.links)
            messages.append({"role": "tool", "tool_name": spec.name, "content": outcome.content})
            if outcome.follow_up:  # clarification ends the loop; nothing runs after it
                follow_up = outcome.follow_up
                break

    trace.chunk_ids = store.chunk_ids()
    if store.items:
        yield "sources", [s.model_dump(mode="json") for s in store.sources()]

    if follow_up is not None:
        for piece in chunk_text(follow_up.question):
            yield "token", {"text": piece}
        done = DoneEvent(
            follow_up=follow_up,
            limitations=limitations,
            answer_kind="clarify",
            latency_ms=_ms(started),
        )
        yield "done", done.model_dump(mode="json")
        return

    abstain, cites = AbstainFilter(), CitationFilter(store.ids())
    emitted = False
    async for piece in _answer_pieces(llm, messages, final_reply):
        text = cites.feed(abstain.feed(piece))
        if text:
            emitted = True
            yield "token", {"text": text}
    tail = cites.feed(abstain.flush()) + cites.flush()
    if tail:
        emitted = True
        yield "token", {"text": tail}
    if not emitted:
        emitted_text = "I could not produce an answer. Please try rephrasing your question."
        yield "token", {"text": emitted_text}
        limitations.append("The model returned an empty answer.")
    if cites.limitation():
        limitations.append(cites.limitation())

    if abstain.abstained:
        office_links = office_links or await _lookup_office_links(
            request.message, settings.tool_timeout_s
        )
    done = DoneEvent(
        citations=cites.cited,
        freshness=compute_freshness(cites.cited, store, today),  # type: ignore[arg-type]
        limitations=limitations,
        latency_ms=_ms(started),
        answer_kind="abstain" if abstain.abstained else "answer",
        office_links=office_links[:3] if abstain.abstained else [],
    )
    yield "done", done.model_dump(mode="json")


async def _answer_pieces(
    llm: LLMClient, messages: list[Message], final_reply: LLMReply | None
) -> AsyncIterator[str]:
    """Text for the final answer: reuse the routing reply if it has text, else stream."""
    if final_reply is not None and final_reply.content.strip():
        for piece in chunk_text(final_reply.content):
            yield piece
            await asyncio.sleep(0)
        return
    async for piece in llm.stream(messages):
        yield piece


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
