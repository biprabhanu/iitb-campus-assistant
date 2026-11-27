"""ASC in chat: privacy routing, answer sentences, cards, mock routing, refresh (CONTRACT §11.8).

Offline. The asc package (Worker A) is never called: tests monkeypatch `campuspilot.asc.<tool>`.
Rule under test: the student's own ASC data reaches only the local model (mode live or mock);
with a cloud model (byok, fallback) the personal tools are not offered and a personal question
gets one fixed reply without any tool or model call.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

import campuspilot.asc
from campuspilot.agent.asc_intent import CLOUD_REPLY, asc_tool_call, is_asc_personal_question
from campuspilot.agent.orchestrator import RunTrace, run_chat
from campuspilot.agent.personal_answer import personal_sentence
from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.llm.base import LLMReply
from campuspilot.llm.mock import MockLLM
from campuspilot.main import create_app
from campuspilot.schemas.chat import ChatRequest, ChatTurn
from campuspilot.schemas.connectors import (
    AscCourse,
    AscCourseDetail,
    AscCourseDetailsInput,
    AscCourseDetailsOutput,
    AscCourseHistoryInput,
    AscCourseHistoryOutput,
    AscCoursesOutput,
    AscCurrentCoursesInput,
    AscFeeItem,
    AscFeeStatusInput,
    AscFeeStatusOutput,
    AscMyTimetableInput,
    AscOfferedCoursesInput,
    AscOfferedCoursesOutput,
    AscOffering,
    AscProfile,
    AscProfileInput,
    AscProfileOutput,
    AscRegistrationOutput,
    AscRegistrationStatusInput,
    AscTimetableOutput,
    AscTimetableSlot,
    ConnectorStatus,
)
from campuspilot.tools.registry import TOOLS, offered_tools, tool_schemas
from tests.backend_helpers import ScriptedLLM, answer_text, call, done_of, install_fake_tools, names

SENTINEL = "SENTINEL-ASC-9F3A"
CONFIRM = {"X-CampusPilot-Confirm": "yes"}
LOCAL_ONLY = {n for n, s in TOOLS.items() if s.local_only}
PUBLIC_ASC = {"asc_offered_courses", "asc_course_offering_history", "asc_course_details"}


def _env(monkeypatch, **env: str) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


async def _run(llm, message: str, history: list[ChatTurn] | None = None):
    trace = RunTrace(request_id="t1")
    request = ChatRequest(message=message, history=history or [])
    return [e async for e in run_chat(request, llm, trace)], trace


def _slot(day: str = "Fri") -> AscTimetableSlot:
    return AscTimetableSlot(
        course_code="IE 624",
        course_title=SENTINEL,
        day=day,  # type: ignore[arg-type]
        start="09:00",
        end="10:00",
        venue="LH 101",
    )


def _timetable(n: int = 3, dates: list[date] | None = None) -> AscTimetableOutput:
    return AscTimetableOutput(slots=[_slot() for _ in range(n)], for_dates=dates or [])


def _offered(n: int = 2) -> AscOfferedCoursesOutput:
    courses = [AscCourse(code=f"IE {600 + i}", title=f"Course {i}") for i in range(n)]
    return AscOfferedCoursesOutput(dept="IE", year=2026, semester="autumn", courses=courses)


def _fake(monkeypatch, name: str, output, seen: list | None = None) -> None:
    async def run(args):
        if seen is not None:
            seen.append(args)
        return output

    monkeypatch.setattr(campuspilot.asc, name, run)


def _offered_names(llm) -> set[str]:
    return {t["function"]["name"] for t in llm.chat_calls[0][1]}


# ---------- intent rules ----------

PERSONAL = [
    ("what's my timetable tomorrow?", "asc_my_timetable", {"day": "tomorrow"}),
    ("do I have classes today", "asc_my_timetable", {"day": "today"}),
    ("my classes this week", "asc_my_timetable", {}),
    ("what are my current courses", "asc_my_current_courses", {}),
    ("show my registered courses", "asc_my_current_courses", {}),
    ("what is my registration status", "asc_registration_status", {}),
    ("is the registration window open?", "asc_registration_status", {}),
    ("do I owe any fees", "asc_fee_status", {}),
    ("what's my fee status", "asc_fee_status", {}),
    ("amount due", "asc_fee_status", {}),
    ("who is my advisor", "asc_profile", {}),
    ("what is my academic standing", "asc_profile", {}),
    ("my department and program", "asc_profile", {}),
]
PUBLIC = [
    ("which IE courses run in autumn 2026", "asc_offered_courses", {"dept": "IE", "year": 2026}),
    ("courses offered in spring 2027", "asc_offered_courses", {"semester": "spring", "year": 2026}),
    ("when is IE 307 usually offered", "asc_course_offering_history", {"course_code": "IE 307"}),
    ("prerequisites of IE 307", "asc_course_details", {"course_code": "IE 307"}),
    ("syllabus of ie624", "asc_course_details", {"course_code": "IE 624"}),
]
NOT_ASC = [
    "what are my grades",
    "show my SPI and CPI",
    "what are the hostel fees",
    "when does the semester start?",
    "latest academic calendar",
    "exam timetable rules",
]


@pytest.mark.parametrize(("question", "tool", "expected"), PERSONAL)
def test_personal_questions_pick_the_right_tool(question, tool, expected) -> None:
    assert is_asc_personal_question(question)
    name, args = asc_tool_call(question)  # type: ignore[misc]
    assert name == tool and args == expected


@pytest.mark.parametrize(("question", "tool", "expected"), PUBLIC)
def test_public_course_questions_pick_a_public_tool(question, tool, expected) -> None:
    assert not is_asc_personal_question(question)
    name, args = asc_tool_call(question, today=date(2026, 11, 27))  # type: ignore[misc]
    assert name == tool and expected.items() <= args.items()


@pytest.mark.parametrize("question", NOT_ASC)
def test_grades_and_campus_questions_get_no_asc_tool(question: str) -> None:
    assert not is_asc_personal_question(question)
    assert asc_tool_call(question) is None


@pytest.mark.parametrize(("question", "tool", "expected"), PERSONAL + PUBLIC)
async def test_mock_routes_asc_phrasings(monkeypatch, question, tool, expected) -> None:
    _env(monkeypatch, ASC_ENABLED="true")
    schemas = tool_schemas(offered_tools(get_settings()))
    reply = await MockLLM().chat([{"role": "user", "content": question}], schemas)
    assert [c.name for c in reply.tool_calls] == [tool]
    assert expected.items() <= reply.tool_calls[0].arguments.items()


async def test_mock_gives_grades_no_asc_tool(monkeypatch) -> None:
    _env(monkeypatch, ASC_ENABLED="true")
    reply = await MockLLM().chat([{"role": "user", "content": "what are my grades"}], [])
    assert not any(c.name.startswith("asc_") for c in reply.tool_calls)


# ---------- offered_tools ----------


def test_local_only_tools_are_hidden_from_a_cloud_model(monkeypatch) -> None:
    _env(monkeypatch, ASC_ENABLED="true")
    settings = get_settings()
    local = {s.name for s in offered_tools(settings, local_model=True)}
    cloud = {s.name for s in offered_tools(settings, local_model=False)}
    assert LOCAL_ONLY and local >= LOCAL_ONLY
    assert not cloud & LOCAL_ONLY
    assert cloud >= PUBLIC_ASC and {"search_campus_docs", "get_my_deadlines"} <= cloud


def test_asc_off_offers_no_asc_tool_to_any_model() -> None:
    for local in (True, False):
        assert not {s.name for s in offered_tools(local_model=local) if s.kind == "asc"}


def test_hosted_mode_offers_no_asc_tool(monkeypatch) -> None:
    _env(monkeypatch, DEPLOY_MODE="hosted", ASC_ENABLED="true")
    for local in (True, False):
        assert not {s.name for s in offered_tools(get_settings(), local_model=local)} & (
            LOCAL_ONLY | PUBLIC_ASC
        )


# ---------- orchestrator: local model ----------


@pytest.mark.parametrize("make_llm", [MockLLM, lambda: ScriptedLLM([], mode="live")])
async def test_local_model_runs_personal_tools_and_never_sees_the_data(monkeypatch, make_llm):
    _env(monkeypatch, ASC_ENABLED="true")
    seen: list = []
    _fake(monkeypatch, "asc_my_timetable", _timetable(3, [date(2026, 11, 28)]), seen)
    llm = make_llm()
    if isinstance(llm, ScriptedLLM):  # a model that routes badly: the backend runs the tool
        llm = ScriptedLLM([LLMReply(content="I think you have no classes.")], mode="live")
    events, trace = await _run(llm, "what's my timetable tomorrow?")
    assert trace.tools == ["asc_my_timetable"] and seen[0].day == "tomorrow"
    assert "sources" not in names(events)
    order = names(events)
    assert order.index("cards") < order.index("token")
    cards = next(d for n, d in events if n == "cards")
    assert [c["id"] for c in cards] == ["A1", "A2", "A3"]
    assert all(c["type"] == "asc_slot" and c["source_label"] == "ASC" for c in cards)
    assert answer_text(events).startswith("You have 3 classes tomorrow (Sat 28 Nov).")
    assert done_of(events)["answer_kind"] == "personal"
    if isinstance(llm, ScriptedLLM):
        assert SENTINEL not in str(llm.chat_calls) and llm.stream_calls == 0
        assert "search_campus_docs" not in _offered_names(llm)  # ASC question: ASC tools only
        assert _offered_names(llm) >= LOCAL_ONLY


async def test_asc_card_content_never_reaches_the_model(monkeypatch) -> None:
    _env(monkeypatch, ASC_ENABLED="true")
    _fake(monkeypatch, "asc_my_timetable", _timetable(2))
    llm = ScriptedLLM([LLMReply(tool_calls=[call("asc_my_timetable", day="Fri")])], mode="live")
    events, _ = await _run(llm, "what's my timetable on friday?")
    cards = next(d for n, d in events if n == "cards")
    assert SENTINEL in str(cards)  # the UI gets it
    assert SENTINEL not in str(llm.chat_calls)  # the model does not
    assert (
        "[ASC results shown to the user: 2 items]" in str(llm.chat_calls) or llm.stream_calls == 0
    )


async def test_asc_history_turns_are_hidden_from_the_model(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    history = [
        ChatTurn(role="user", content="my timetable tomorrow?"),
        ChatTurn(role="assistant", content=f"You have 3 classes {SENTINEL}", kind="personal"),
    ]
    llm = ScriptedLLM([LLMReply(tool_calls=[call("search_campus_docs", query="x")])])
    await _run(llm, "when does the semester start?", history)
    assert SENTINEL not in str(llm.chat_calls)


async def test_tool_failure_is_told_plainly_for_asc(monkeypatch) -> None:
    _env(monkeypatch, ASC_ENABLED="true")
    message = "ASC needs the campus network or IITB VPN."

    async def unreachable(args):
        raise ConnectorError("unreachable", message)

    monkeypatch.setattr(campuspilot.asc, "asc_fee_status", unreachable)
    events, trace = await _run(MockLLM(), "do I owe any fees")
    assert trace.tools == ["asc_fee_status"]
    assert answer_text(events) == f"I couldn't read ASC. {message}"
    assert done_of(events)["answer_kind"] == "personal"


# ---------- orchestrator: cloud model ----------


@pytest.mark.parametrize("mode", ["byok", "fallback"])
async def test_cloud_model_gets_no_personal_tool_and_a_fixed_reply(monkeypatch, mode) -> None:
    _env(monkeypatch, ASC_ENABLED="true")
    install_fake_tools(monkeypatch)
    llm = ScriptedLLM([LLMReply(tool_calls=[call("asc_my_timetable")])], mode=mode)
    events, trace = await _run(llm, "what's my timetable tomorrow?")
    assert answer_text(events) == CLOUD_REPLY
    assert CLOUD_REPLY == (
        "That needs your ASC data, which CampusPilot only shares with the local model. "
        "Switch to Local Gemma in Settings."
    )
    assert llm.chat_calls == [] and llm.stream_calls == 0  # no model call
    assert trace.tools == []  # no tool call
    assert names(events) == ["status", *["token"] * names(events).count("token"), "done"]
    assert done_of(events)["answer_kind"] == "personal"


@pytest.mark.parametrize("mode", ["byok", "fallback"])
async def test_cloud_model_is_offered_only_public_tools(monkeypatch, mode) -> None:
    _env(monkeypatch, ASC_ENABLED="true")
    seen: list = []
    _fake(monkeypatch, "asc_offered_courses", _offered(2), seen)
    llm = ScriptedLLM(
        [
            LLMReply(
                tool_calls=[call("asc_offered_courses", dept="IE", year=2026, semester="autumn")]
            )
        ],
        mode=mode,
    )
    events, trace = await _run(llm, "which IE courses run in autumn 2026")
    offered = _offered_names(llm)
    assert not offered & LOCAL_ONLY
    assert offered >= PUBLIC_ASC and "search_campus_docs" in offered
    assert trace.tools == ["asc_offered_courses"]
    cards = next(d for n, d in events if n == "cards")
    assert [c["id"] for c in cards] == ["A1", "A2"]
    assert answer_text(events).startswith("ASC lists 2 IE courses running in Autumn 2026-27.")


async def test_cloud_model_ignores_a_personal_tool_it_asks_for_anyway(monkeypatch) -> None:
    _env(monkeypatch, ASC_ENABLED="true")
    install_fake_tools(monkeypatch)
    ran: list = []
    _fake(monkeypatch, "asc_profile", AscProfileOutput(), ran)
    llm = ScriptedLLM(
        [LLMReply(tool_calls=[call("asc_profile")]), LLMReply(content="x")], mode="byok"
    )
    _, trace = await _run(llm, "tell me about the hostel")  # not a personal ASC question
    assert "asc_profile" not in trace.tools and ran == []


async def test_asc_off_keeps_todays_behaviour(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    llm = ScriptedLLM([LLMReply(content="ok")], mode="byok")
    events, trace = await _run(llm, "what's my timetable tomorrow?")
    assert answer_text(events) != CLOUD_REPLY
    assert not any(n.startswith("asc_") for n in trace.tools)
    assert not any(n.startswith("asc_") for n in _offered_names(llm))


# ---------- per-tool timeout ----------


async def _slow(args):
    await asyncio.sleep(0.5)
    return AscProfileOutput()


async def test_a_short_tool_timeout_is_used(monkeypatch) -> None:
    _env(monkeypatch, ASC_ENABLED="true", TOOL_TIMEOUT_S="30")
    monkeypatch.setattr(campuspilot.asc, "asc_profile", _slow)
    monkeypatch.setitem(
        TOOLS, "asc_profile", dataclasses.replace(TOOLS["asc_profile"], timeout_s=0.05)
    )
    events, _ = await _run(MockLLM(), "who is my advisor")
    assert ("asc_profile", "error") in [(d["name"], d["state"]) for n, d in events if n == "tool"]
    assert "timed out" in answer_text(events)


async def test_a_long_tool_timeout_beats_the_global_one(monkeypatch) -> None:
    _env(monkeypatch, ASC_ENABLED="true", TOOL_TIMEOUT_S="0.05")
    monkeypatch.setattr(campuspilot.asc, "asc_profile", _slow)
    monkeypatch.setitem(
        TOOLS, "asc_profile", dataclasses.replace(TOOLS["asc_profile"], timeout_s=5.0)
    )
    events, _ = await _run(MockLLM(), "who is my advisor")
    assert answer_text(events).startswith("Here is your ASC profile.")


# ---------- cards ----------


async def test_cards_are_numbered_a1_across_tools_and_types(monkeypatch) -> None:
    _env(monkeypatch, ASC_ENABLED="true")
    _fake(monkeypatch, "asc_profile", AscProfileOutput(profile=AscProfile(department="IEOR")))
    _fake(
        monkeypatch,
        "asc_fee_status",
        AscFeeStatusOutput(items=[AscFeeItem(label="Tuition", status="Paid")]),
    )
    _fake(
        monkeypatch,
        "asc_course_offering_history",
        AscCourseHistoryOutput(
            course_code="IE 307",
            offerings=[AscOffering(year=2025, semester="autumn", offered=True)],
        ),
    )
    _fake(
        monkeypatch,
        "asc_course_details",
        AscCourseDetailsOutput(detail=AscCourseDetail(code="IE 307", title="Optimization")),
    )
    llm = ScriptedLLM(
        [
            LLMReply(
                tool_calls=[
                    call("asc_profile"),
                    call("asc_fee_status"),
                    call("asc_course_offering_history", course_code="IE 307"),
                    call("asc_course_details", course_code="IE 307"),
                ]
            )
        ],
        mode="live",
    )
    events, _ = await _run(llm, "who is my advisor and fee status")
    cards = next(d for n, d in events if n == "cards")
    assert [(c["id"], c["type"]) for c in cards] == [
        ("A1", "asc_profile"),
        ("A2", "asc_fee"),
        ("A3", "asc_history"),
        ("A4", "asc_detail"),
    ]


# ---------- sentences ----------


def _course(status: str = "registered") -> AscCourse:
    return AscCourse(code="IE 624", status=status)  # type: ignore[arg-type]


def test_sentence_timetable() -> None:
    out = _timetable(3, [date(2026, 11, 28)])
    assert (
        personal_sentence("asc_my_timetable", AscMyTimetableInput(day="tomorrow"), out)
        == "You have 3 classes tomorrow (Sat 28 Nov)."
    )
    none = _timetable(0, [date(2026, 11, 28)])
    assert (
        personal_sentence("asc_my_timetable", AscMyTimetableInput(day="tomorrow"), none)
        == "Your ASC timetable shows no classes tomorrow (Sat 28 Nov)."
    )
    week = personal_sentence("asc_my_timetable", AscMyTimetableInput(), _timetable(1))
    assert week == "You have 1 class this week."


def test_sentence_current_courses() -> None:
    out = AscCoursesOutput(courses=[_course()] * 5, semester="2026-27 Autumn")
    text = personal_sentence("asc_my_current_courses", AscCurrentCoursesInput(), out)
    assert text == "ASC shows 5 courses for 2026-27 Autumn."


def test_sentence_registration_closed_and_open() -> None:
    args = AscRegistrationStatusInput()
    closed = AscRegistrationOutput(
        window_open=False,
        courses=[_course()] * 4,
        semester="2026-27 Autumn",
        note="Registration is closed.",
    )
    assert personal_sentence("asc_registration_status", args, closed) == (
        "ASC shows 4 registered courses for 2026-27 Autumn. Registration is closed."
    )
    opened = AscRegistrationOutput(
        window_open=True, courses=[_course(), _course(), _course("pending")]
    )
    assert personal_sentence("asc_registration_status", args, opened) == (
        "Registration is open. ASC shows 3 courses: registered 2, pending 1."
    )


def test_sentence_fees() -> None:
    out = AscFeeStatusOutput(
        items=[AscFeeItem(label="Tuition", status="Paid"), AscFeeItem(label="Hostel", status="Due")]
    )
    text = personal_sentence("asc_fee_status", AscFeeStatusInput(), out)
    assert text == "ASC shows 2 fee entries; 1 is due."
    paid = AscFeeStatusOutput(items=[AscFeeItem(label="Tuition", status="Paid")])
    assert personal_sentence("asc_fee_status", AscFeeStatusInput(), paid) == (
        "ASC shows 1 fee entry; none is due."
    )
    assert personal_sentence("asc_fee_status", AscFeeStatusInput(), AscFeeStatusOutput()) == (
        "ASC shows no fee entries."
    )


def test_sentence_profile_offered_and_details() -> None:
    assert (
        personal_sentence("asc_profile", AscProfileInput(), AscProfileOutput())
        == "Here is your ASC profile."
    )
    args = AscOfferedCoursesInput(dept="IE", year=2026, semester="autumn")
    assert personal_sentence("asc_offered_courses", args, _offered(12)) == (
        "ASC lists 12 IE courses running in Autumn 2026-27."
    )
    details = AscCourseDetailsOutput(detail=AscCourseDetail(code="IE 307"))
    assert personal_sentence(
        "asc_course_details", AscCourseDetailsInput(course_code="IE 307"), details
    ) == ("Here are the ASC details for IE 307.")


def test_sentence_history() -> None:
    args = AscCourseHistoryInput(course_code="IE 307")
    offerings = [
        AscOffering(year=y, semester="autumn", offered=True) for y in (2024, 2025, 2026)
    ] + [AscOffering(year=y, semester="spring", offered=False) for y in (2024, 2025, 2026)]
    out = AscCourseHistoryOutput(course_code="IE 307", offerings=offerings)
    assert personal_sentence("asc_course_offering_history", args, out) == (
        "IE 307 ran in Autumn 2024-25, 2025-26 and 2026-27; not in Spring."
    )
    nothing = AscCourseHistoryOutput(
        course_code="IE 307",
        offerings=[AscOffering(year=2025, semester="autumn", offered=False)],
    )
    assert personal_sentence("asc_course_offering_history", args, nothing) == (
        "ASC shows no runs of IE 307 in the last 3 years."
    )


def test_sentence_adds_note_and_demo_label() -> None:
    out = AscProfileOutput(demo=True, note="Read 2 min ago.")
    text = personal_sentence("asc_profile", AscProfileInput(), out)
    assert text == "Here is your ASC profile. Read 2 min ago. These are demo ASC data."


# ---------- refresh endpoint ----------


def _client(monkeypatch, **env: str) -> TestClient:
    _env(monkeypatch, **env)
    return TestClient(create_app())


def test_refresh_needs_the_confirm_header(monkeypatch) -> None:
    client = _client(monkeypatch, ASC_ENABLED="true")
    assert client.post("/v1/connectors/asc/refresh").status_code == 403


def test_refresh_returns_the_status_and_maps_errors(monkeypatch) -> None:
    client = _client(monkeypatch, ASC_ENABLED="true")
    stamp = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)

    async def ok():
        return ConnectorStatus(name="asc", enabled=True, state="connected", refreshed_at=stamp)

    monkeypatch.setattr(campuspilot.asc, "asc_refresh", ok)
    response = client.post("/v1/connectors/asc/refresh", headers=CONFIRM)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "connected" and body["refreshed_at"].startswith("2026-11-27T09:00")

    async def down():
        raise ConnectorError("unreachable", "ASC needs the campus network or IITB VPN.")

    monkeypatch.setattr(campuspilot.asc, "asc_refresh", down)
    failed = client.post("/v1/connectors/asc/refresh", headers=CONFIRM)
    assert failed.status_code == 503 and failed.json()["code"] == "UNREACHABLE"


def test_refresh_is_off_when_asc_is_off_and_absent_in_hosted(monkeypatch) -> None:
    off = _client(monkeypatch)
    assert off.post("/v1/connectors/asc/refresh", headers=CONFIRM).status_code == 404
    hosted = _client(monkeypatch, DEPLOY_MODE="hosted", ASC_ENABLED="true")
    assert "/v1/connectors/asc/refresh" not in {getattr(r, "path", "") for r in hosted.app.routes}
    assert hosted.post("/v1/connectors/asc/refresh", headers=CONFIRM).status_code == 404
