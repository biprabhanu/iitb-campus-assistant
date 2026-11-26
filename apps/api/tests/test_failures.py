"""Failure handling: model down, slow model, tool errors, limits and bad input."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from campuspilot.config import get_settings
from campuspilot.llm.base import LLMReply
from campuspilot.main import create_app
from campuspilot.schemas.chat import ChatTurn
from tests.backend_helpers import (
    OLLAMA,
    ScriptedLLM,
    call,
    done_of,
    install_fake_tools,
    names,
    parse_sse,
)
from tests.qa_helpers import run, tool_states


def post_chat(monkeypatch, body: dict):
    get_settings.cache_clear()
    return TestClient(create_app()).post("/v1/chat", json=body)


@respx.mock
def test_tunnel_down_gives_model_offline(monkeypatch) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    events = parse_sse(post_chat(monkeypatch, {"message": "hello campus"}).text)
    assert names(events) == ["status", "error"]
    assert events[1][1]["code"] == "MODEL_OFFLINE"


@respx.mock
def test_read_timeout_gives_timeout(monkeypatch) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=httpx.ReadTimeout("slow"))
    events = parse_sse(post_chat(monkeypatch, {"message": "hello campus"}).text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "TIMEOUT"


async def test_moodle_error_is_a_tool_error_and_the_stream_still_finishes(monkeypatch) -> None:
    install_fake_tools(monkeypatch, moodle_error="Moodle is not connected.")
    llm = ScriptedLLM(
        [LLMReply(tool_calls=[call("get_my_deadlines")]), LLMReply(content="I can't reach Moodle.")]
    )
    events, _ = await run(llm, "What's due this week?")
    assert ("get_my_deadlines", "error") in tool_states(events)
    assert names(events)[-1] == "done"
    assert "error" not in names(events)  # a tool failure is not a stream failure


async def test_only_four_tool_calls_run(monkeypatch) -> None:
    fakes = install_fake_tools(monkeypatch)
    llm = ScriptedLLM(
        [LLMReply(tool_calls=[call("search_campus_docs", query=f"q{i}") for i in range(7)])],
        stream_pieces=["Answer [S1]."],
    )
    events, _ = await run(llm)
    assert len(fakes.search) == 4
    assert names(events)[-1] == "done"
    assert any("extra calls were ignored" in x for x in done_of(events)["limitations"])


def test_message_of_2001_characters_is_rejected_with_422(monkeypatch) -> None:
    response = post_chat(monkeypatch, {"message": "a" * 2001})
    assert response.status_code == 422
    assert "a" * 50 not in response.text  # the input is not echoed back


def test_message_of_2000_characters_is_accepted(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    monkeypatch.setenv("CAMPUSPILOT_MOCK_LLM", "true")
    response = post_chat(monkeypatch, {"message": "a" * 2000})
    assert response.status_code == 200


async def test_history_is_trimmed_to_the_last_20_turns(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    history = [
        ChatTurn(role="user" if i % 2 == 0 else "assistant", content=f"m{i}") for i in range(50)
    ]
    llm = ScriptedLLM([LLMReply(content="ok")])
    await run(llm, "hello campus", history=history)
    sent = llm.chat_calls[0][0]
    contents = [m["content"] for m in sent]
    assert len(sent) == 1 + 20 + 1  # system + 20 history turns + the new message
    assert "m29" not in contents and contents[1] == "m30"
