"""CONTRACT §10.4: nothing from the student's Moodle may appear in a request sent to an LLM.

Every outgoing model request body is recorded, once through BYOKClient (respx) and once
through a scripted fake, and searched for each Moodle field value.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import httpx
import respx

from campuspilot.agent.orchestrator import RunTrace, run_chat
from campuspilot.config import get_settings
from campuspilot.llm.base import LLMReply
from campuspilot.llm.byok import BYOKClient
from campuspilot.llm.providers import PROVIDERS
from campuspilot.schemas.chat import ChatRequest, ChatTurn
from campuspilot.schemas.tools import (
    Course,
    CourseResource,
    CourseSection,
    Deadline,
    GetCourseContentsOutput,
    GetMyDeadlinesOutput,
    ListMyCoursesOutput,
)
from tests.backend_helpers import (
    ScriptedLLM,
    answer_text,
    call,
    done_of,
    install_fake_tools,
)
from tests.hosted_helpers import FAKE_KEY, GROQ_URL, completion, sse_stream, tool_call

# Values that exist only in the student's Moodle (the user's own question never contains them).
SECRETS = [
    "Zebra Quantum Assignment 9",
    "ZZ999",
    "Advanced Zebra Studies",
    "view.php?id=424242",
    "mod/assign/view.php",
    "Secret Lecture Notes",
    "Hidden Week Seven",
    "2031-04-05",
]
BASE = "https://moodle.iitb.ac.in"
HISTORY_SECRET = "You have 1 deadline. The nearest is ZZ999 Zebra Quantum Assignment 9."


def install_moodle(monkeypatch) -> None:
    """Fake Moodle tools that return recognisable data."""
    install_fake_tools(monkeypatch)
    course = Course(
        id=5,
        short_name="IE624",
        full_name="Advanced Zebra Studies",
        url=f"{BASE}/course/view.php?id=424242",
    )

    async def get_my_deadlines(args):
        due = datetime(2031, 4, 5, 17, 0, tzinfo=UTC)
        item = Deadline(
            id="a1",
            title="Zebra Quantum Assignment 9",
            course="ZZ999",
            due_at=due,
            activity_url=f"{BASE}/mod/assign/view.php?id=424242",
            kind="assignment",
        )
        return GetMyDeadlinesOutput(deadlines=[item], mode="rest")

    async def list_my_courses(args):
        return ListMyCoursesOutput(courses=[course], mode="rest")

    async def get_course_contents(args):
        section = CourseSection(
            name="Hidden Week Seven",
            resources=[CourseResource(name="Secret Lecture Notes", type="resource")],
        )
        return GetCourseContentsOutput(course=course, sections=[section], mode="rest")

    moodle = sys.modules["campuspilot.moodle.tools"]
    for func in (get_my_deadlines, list_my_courses, get_course_contents):
        setattr(moodle, func.__name__, func)


def assert_clean(recorded: str) -> None:
    for secret in SECRETS:
        assert secret.lower() not in recorded.lower(), f"{secret!r} reached the model"


QUESTIONS = [
    ("what is due this week?", "get_my_deadlines", {"days_ahead": 7}),
    ("which courses am I enrolled in?", "list_my_courses", {}),
    ("what is in my IE624 course contents?", "get_course_contents", {"course_code": "IE624"}),
]


def route_for(body: str) -> tuple[str, dict]:
    """Pick the tool the fake router calls, from the user's question in the request body."""
    for question, tool, args in QUESTIONS:
        if question in body:
            return tool, args
    return "search_campus_docs", {"query": "semester start"}


def tool_reply(name: str, args: dict) -> LLMReply:
    return LLMReply(tool_calls=[call(name, **args)])


# ---------- through a scripted fake ----------


async def test_scripted_llm_never_sees_moodle_values(monkeypatch) -> None:
    install_moodle(monkeypatch)
    for question, tool, args in QUESTIONS:
        llm = ScriptedLLM([tool_reply(tool, args)])
        events = [e async for e in run_chat(ChatRequest(message=question), llm, RunTrace("t"))]
        assert_clean(str(llm.chat_calls))
        assert llm.stream_calls == 0
        assert done_of(events)["answer_kind"] == "moodle"
        assert answer_text(events)  # the student still gets a sentence, written by our code


async def test_cards_still_reach_the_ui(monkeypatch) -> None:
    install_moodle(monkeypatch)
    llm = ScriptedLLM([tool_reply("get_my_deadlines", {})])
    events = [e async for e in run_chat(ChatRequest(message="what is due?"), llm, RunTrace("t"))]
    source = next(d for n, d in events if n == "sources")[0]
    assert source["title"] == "Zebra Quantum Assignment 9" and source["id"] == "M1"


async def test_moodle_history_turn_is_replaced_before_any_call(monkeypatch) -> None:
    install_moodle(monkeypatch)
    history = [
        ChatTurn(role="user", content="what is due?"),
        ChatTurn(role="assistant", content=HISTORY_SECRET, kind="moodle"),
    ]
    llm = ScriptedLLM(
        [tool_reply("search_campus_docs", {"query": "calendar"})],
        stream_pieces=["Classes begin 3 Aug [S1]."],
    )
    request = ChatRequest(message="when does the semester start?", history=history)
    _ = [e async for e in run_chat(request, llm, RunTrace("t"))]
    sent = str(llm.chat_calls)
    assert_clean(sent)
    assert "[Moodle results were shown to the user]" in sent


async def test_precheck_history_is_scrubbed_too(monkeypatch) -> None:
    install_moodle(monkeypatch)
    monkeypatch.setenv("CLARIFY_PRECHECK", "true")
    get_settings.cache_clear()
    history = [ChatTurn(role="assistant", content=HISTORY_SECRET, kind="moodle")]
    llm = ScriptedLLM(
        [
            LLMReply(content='{"clarify": false}'),
            tool_reply("search_campus_docs", {"query": "x"}),
        ],
        stream_pieces=["ok [S1]"],
    )
    request = ChatRequest(message="when is the hostel fee due date?", history=history)
    _ = [e async for e in run_chat(request, llm, RunTrace("t"))]
    assert_clean(str(llm.chat_calls))


# ---------- through BYOKClient and real request bodies ----------


@respx.mock
async def test_byok_request_bodies_never_contain_moodle_values(monkeypatch) -> None:
    install_moodle(monkeypatch)
    settings = get_settings()
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.decode())
        if '"stream":true' in request.content.decode().replace(" ", ""):
            return sse_stream("Classes begin 3 Aug [S1].")
        name, args = route_for(request.content.decode())
        return completion(tool_calls=[tool_call(name, **args)])

    respx.post(GROQ_URL).mock(side_effect=handler)
    history = [ChatTurn(role="assistant", content=HISTORY_SECRET, kind="moodle")]
    for question in [*(q for q, _, _ in QUESTIONS), "when does the semester start?"]:
        client = BYOKClient(PROVIDERS["groq"], FAKE_KEY, None, settings)
        request = ChatRequest(message=question, history=history)
        events = [e async for e in run_chat(request, client, RunTrace("t"), settings)]
        assert events[-1][0] == "done"
    assert len(bodies) >= 4
    assert_clean("\n".join(bodies))
    assert "[Moodle results were shown to the user]" in "\n".join(bodies)
