"""The chat loop (MASTER_BUILD_PROMPT §5.2, CONTRACT §3, §5, §6).

`run_chat` is an async generator of (event_name, json_payload) pairs. The API layer
turns them into Server-Sent Events; tests can read them directly.

Steps: ask the model which tools to use -> run them (validated, time-limited, max 4)
-> send `sources` -> send `cards` (v2 Webmail / ASC) -> stream the answer (abstain prefix and
bad citations stripped) -> `done`.

Personal data (Moodle, Webmail, ASC) never goes back to the chat model: those tools return
cards for the UI and a template sentence written by our code; the model only learns a count.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from campuspilot.agent.citations import CitationFilter
from campuspilot.agent.clarify import needs_clarification
from campuspilot.agent.mail_intent import is_mail_question, mail_tool_call
from campuspilot.agent.moodle_answer import moodle_sentence
from campuspilot.agent.personal_answer import personal_sentence
from campuspilot.agent.prompts import build_short_prompt, build_system_prompt
from campuspilot.config import Settings, get_settings
from campuspilot.llm.base import (
    LLMClient,
    LLMError,
    LLMReply,
    Message,
    ModelOffline,
    ModelTimeout,
    ProviderError,
    ToolCall,
)
from campuspilot.schemas.chat import (
    ChatRequest,
    ChatTurn,
    DoneEvent,
    ErrorEvent,
    FollowUp,
    OfficeLink,
    StatusEvent,
    ToolEvent,
)
from campuspilot.schemas.tools import GetOfficialLinkInput, GetOfficialLinkOutput
from campuspilot.tools.cards import number_cards
from campuspilot.tools.evidence import EvidenceBudget, EvidenceStore
from campuspilot.tools.registry import (
    PERSONAL_KINDS,
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
    provider: str = ""  # hosted: the provider id, never the key
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
    # The template sentence for a personal-data tool (Moodle, Webmail, ASC), success or failure.
    personal_text: str | None = None
    cards: list[Any] = field(default_factory=list)  # Webmail / ASC cards (ids not yet numbered)


MOODLE_HISTORY_TEXT = "[Moodle results were shown to the user]"
PERSONAL_HISTORY_TEXT = "[Results from the student's own accounts were shown to the user]"
_COUNT_LABEL = {"moodle": "Moodle", "mail": "Webmail", "asc": "ASC"}


# ---------- small helpers ----------


def chunk_text(text: str, size: int = 20) -> list[str]:
    """Split text into small pieces so a non-streamed reply still looks streamed."""
    return [text[i : i + size] for i in range(0, len(text), size)]


ABSTAIN_TEXT = (
    "I couldn't verify this in my sources, so I won't guess. "
    "Please check with the office or portal linked below."
)


class AbstainFilter:
    """Detects a leading 'ABSTAIN:' in streamed text.

    When the model abstains, everything it wrote after the prefix is replaced by one fixed,
    honest sentence. Free-text abstentions tended to name portals that are in no source
    (e.g. invented mess-app names); the real pointers come from `office_links` instead.
    """

    PREFIX = "ABSTAIN:"

    def __init__(self) -> None:
        self.abstained = False
        self._decided = False
        self._buf = ""

    def feed(self, text: str) -> str:
        if self._decided:
            return "" if self.abstained else text
        self._buf += text
        head = self._buf.lstrip()
        if len(head) < len(self.PREFIX) and self.PREFIX.startswith(head):
            return ""  # could still become the prefix; wait
        self._decided = True
        buf, self._buf = self._buf, ""
        if head.startswith(self.PREFIX):
            self.abstained = True
            return ABSTAIN_TEXT
        return buf

    def flush(self) -> str:
        buf, self._buf = self._buf, ""
        if not self._decided and buf.strip() == self.PREFIX.rstrip(":"):
            buf = ""
        self._decided = True
        return "" if self.abstained else buf


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


_FAILED_PREFIX = {"mail": "I couldn't read your mail.", "asc": "I couldn't read ASC."}


def _failed(spec: ToolSpec, note: str, message: str) -> ToolOutcome:
    """A tool that did not finish. A failed personal-data tool tells the student itself, and
    clearly: for a mail question nothing else answers instead (see `_run`)."""
    if spec.kind in PERSONAL_KINDS:
        prefix = _FAILED_PREFIX.get(spec.kind)
        text = f"{prefix} {message}" if prefix else message
        return ToolOutcome(False, _note(note), personal_text=text)
    return ToolOutcome(False, _note(note), message)


async def _execute_tool(
    spec: ToolSpec,
    arguments: dict[str, Any],
    store: EvidenceStore,
    timeout_s: float,
    budget: EvidenceBudget | None = None,
) -> ToolOutcome:
    try:
        args = spec.input_model.model_validate(arguments)
    except ValidationError as exc:
        fields = ", ".join(sorted({str(e["loc"][0]) if e["loc"] else "?" for e in exc.errors()}))
        note = f"Tool {spec.name} was called with invalid arguments (check: {fields})."
        return _failed(spec, note, f"A tool call had invalid arguments ({spec.name}).")
    try:
        output = await asyncio.wait_for(spec.run(args), timeout=timeout_s)
    except TimeoutError:
        return _failed(spec, f"{spec.name} timed out.", f"{spec.label} timed out.")
    except ToolFailure as exc:
        return _failed(spec, str(exc), str(exc))
    except Exception as exc:
        log.warning(
            "tool %s failed: %s", spec.name, type(exc).__name__
        )  # no details: may be private
        return _failed(spec, f"{spec.name} is unavailable right now.", f"{spec.label} failed.")
    return _success_outcome(spec, args, output, store, budget)


def _success_outcome(
    spec: ToolSpec, args: Any, output: Any, store: EvidenceStore, budget: EvidenceBudget | None
) -> ToolOutcome:
    if isinstance(output, AskClarificationInput):
        return ToolOutcome(
            True, "", follow_up=FollowUp(question=output.question, options=output.options)
        )
    if spec.kind in ("mail", "asc"):
        # v2: cards go to the UI; the model only learns how many there were.
        assert spec.to_cards is not None
        cards = spec.to_cards(output)
        text = personal_sentence(spec.name, args, output)
        content = f"[{_COUNT_LABEL[spec.kind]} results shown to the user: {len(cards)} items]"
        return ToolOutcome(True, content, personal_text=text, cards=cards)
    assert spec.to_evidence is not None
    items, note = spec.to_evidence(output)
    if spec.kind == "moodle":
        # The cards go to the UI; the model only learns how many there were.
        added = store.add(items)
        text = moodle_sentence(spec.name, args, output, datetime.now(UTC))
        content = f"[Moodle results shown to the user: {len(added)} items]"
        return ToolOutcome(True, content, personal_text=text)
    if budget is not None:
        items = budget.fit(items)
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


# ---------- retrieval guard ----------

_SMALL_TALK = re.compile(
    r"^\s*(hi|hii+|hello|hey|thanks|thank you|thx|ok|okay|bye|good (morning|evening|night))\b",
    re.IGNORECASE,
)


def _is_small_talk(message: str) -> bool:
    """Greetings and one-word replies don't need a document search."""
    return len(message.split()) <= 2 or bool(_SMALL_TALK.match(message))


def _forced_mail(message: str) -> LLMReply:
    """A mail question the model answered without a mail tool: run the right one ourselves."""
    name, args = mail_tool_call(message)
    return LLMReply(tool_calls=[ToolCall(name, args)])


def _forced_search(message: str) -> LLMReply:
    """Gemma sometimes answers or abstains without looking anything up. We never let it
    finish an institutional question without a search, so the backend makes the call itself."""
    return LLMReply(tool_calls=[ToolCall("search_campus_docs", {"query": message[:300]})])


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
    except ProviderError as exc:
        yield _error(trace, exc.code, exc.message, exc.provider, exc.retry_after_s)
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


def _error(
    trace: RunTrace,
    code: str,
    message: str,
    provider: str | None = None,
    retry_after_s: int | None = None,
) -> Event:
    trace.error_code = code
    event = ErrorEvent(
        code=code,  # type: ignore[arg-type]
        message=message,
        provider=provider,
        retry_after_s=retry_after_s,
    )
    return "error", event.model_dump(mode="json", exclude_none=True)


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
    hosted = settings.hosted
    budget = (
        EvidenceBudget(
            settings.hosted_max_evidence_chunks, settings.hosted_evidence_token_budget * 4
        )
        if hosted
        else None
    )
    specs = offered_tools(settings)
    # Owner rule (27 Nov 2026): with Webmail on, a question about the student's mail is answered
    # from the mail tools only, never from campus documents. If the mail tools fail, the student
    # is told so; nothing else answers instead.
    mail_turn = any(s.kind == "mail" for s in specs) and is_mail_question(request.message)
    if mail_turn:
        specs = [spec for spec in specs if spec.kind == "mail"]
    precheck_on = settings.clarify_precheck and llm.mode != "mock" and not mail_turn
    if precheck_on:
        # The pre-check owns the "ask or not" decision; offering ask_clarification to the
        # routing call as well made Gemma ask even when the student had named their cohort.
        specs = [spec for spec in specs if spec.name != "ask_clarification"]
    by_name = {s.name: s for s in specs}
    schemas = tool_schemas(specs)

    keep = settings.hosted_max_history_turns if hosted else settings.max_history_turns
    history = [_hide_moodle(t) for t in request.history[-keep:]]
    if hosted:
        system = build_short_prompt(today)
    else:
        connector_tools = [s.name for s in specs if s.kind in ("mail", "asc")]
        system = build_system_prompt(
            today, clarify_tool="ask_clarification" in by_name, connector_tools=connector_tools
        )
    messages: list[Message] = [{"role": "system", "content": system}]
    messages += [{"role": t.role, "content": t.content} for t in history]
    messages.append({"role": "user", "content": request.message})

    executed = 0
    moodle_texts: list[str] = []  # template sentences of every personal-data tool
    cards: list[Any] = []
    card_counters: dict[str, int] = {}
    final_reply: LLMReply | None = None
    follow_up: FollowUp | None = None

    # Step 0: a focused yes/no check for "needs a clarifying question" (see agent/clarify.py).
    if precheck_on and not _is_small_talk(request.message):
        follow_up = await needs_clarification(llm, request.message, history)
        if follow_up is not None:
            trace.tools.append("ask_clarification")
            for state in ("start", "done"):
                event = ToolEvent(
                    name="ask_clarification", label="Asking a clarifying question", state=state
                )
                yield "tool", event.model_dump()

    while executed < settings.max_tool_calls and follow_up is None:
        reply = await llm.chat(messages, schemas)
        # Ignore requests for tools we didn't offer, so the search guard below still applies.
        offered_calls = [c for c in reply.tool_calls if c.name in by_name]
        if len(offered_calls) != len(reply.tool_calls):
            reply = LLMReply(content=reply.content, tool_calls=offered_calls)
        if mail_turn and not reply.tool_calls and not trace.tools:
            reply = _forced_mail(request.message)
        # Only when NO tool has run yet: a Moodle-only or link-only turn is fine as it is.
        if (
            not reply.tool_calls
            and not trace.tools
            and "search_campus_docs" in by_name
            and not _is_small_talk(request.message)
        ):
            reply = _forced_search(request.message)
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
            outcome = await _execute_tool(
                spec, call.arguments, store, settings.tool_timeout_s, budget
            )
            state = "done" if outcome.ok else "error"
            yield "tool", ToolEvent(name=spec.name, label=spec.label, state=state).model_dump()
            if outcome.personal_text:
                moodle_texts.append(outcome.personal_text)
            cards.extend(number_cards(outcome.cards, card_counters))
            if outcome.limitation:
                limitations.append(outcome.limitation)
            office_links.extend(outcome.links)
            messages.append({"role": "tool", "tool_name": spec.name, "content": outcome.content})
            if outcome.follow_up:  # clarification ends the loop; nothing runs after it
                follow_up = outcome.follow_up
                break
        # One routing round is enough: Gemma asks for all the tools it needs in one reply
        # (parallel calls). Stopping here means the answer comes from a real streaming call
        # (no tools offered), so the first words reach the student as soon as they're written.
        break

    # Official portals (support portal, ASC, InstiApp...) are registry links, not documents,
    # so a document search alone misses them. If the model searched but didn't look up links,
    # the backend does it too (local and cheap) so the answer can cite the right portal.
    link_spec = by_name.get("get_official_link")
    if (
        settings.auto_official_links
        and follow_up is None
        and link_spec is not None
        and "search_campus_docs" in trace.tools
        and "get_official_link" not in trace.tools
    ):
        args = {"topic": request.message[:200]}
        trace.tools.append(link_spec.name)
        yield (
            "tool",
            ToolEvent(name=link_spec.name, label=link_spec.label, state="start").model_dump(),
        )
        outcome = await _execute_tool(link_spec, args, store, settings.tool_timeout_s, budget)
        state = "done" if outcome.ok else "error"
        yield (
            "tool",
            ToolEvent(name=link_spec.name, label=link_spec.label, state=state).model_dump(),
        )
        office_links.extend(outcome.links)
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": link_spec.name, "arguments": args}}],
            }
        )
        messages.append({"role": "tool", "tool_name": link_spec.name, "content": outcome.content})

    trace.chunk_ids = store.chunk_ids()
    if store.items:
        yield "sources", [s.model_dump(mode="json") for s in store.sources()]
    if cards:
        yield "cards", [c.model_dump(mode="json") for c in cards]

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

    doc_ran = any(TOOLS[name].kind == "doc" for name in trace.tools if name in TOOLS)
    if moodle_texts:
        text = " ".join(moodle_texts)
        for piece in chunk_text(text if not doc_ran else text + "\n\n"):
            yield "token", {"text": piece}
        if not doc_ran:  # personal data only: our sentence is the whole answer, no model call
            v2_ran = any(TOOLS[n].kind in ("mail", "asc") for n in trace.tools if n in TOOLS)
            kind = "personal" if v2_ran else "moodle"
            done = DoneEvent(limitations=limitations, answer_kind=kind, latency_ms=_ms(started))
            yield "done", done.model_dump(mode="json")
            return

    abstain, cites = AbstainFilter(), CitationFilter(store.ids())
    emitted = bool(moodle_texts)
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


def _hide_moodle(turn: ChatTurn) -> ChatTurn:
    """A past answer built from Moodle, Webmail or ASC data must not reach the model."""
    if turn.kind == "moodle":
        return turn.model_copy(update={"content": MOODLE_HISTORY_TEXT})
    if turn.kind == "personal":
        return turn.model_copy(update={"content": PERSONAL_HISTORY_TEXT})
    return turn


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
