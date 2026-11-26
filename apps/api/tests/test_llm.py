"""Ollama client and fallback client, with HTTP mocked by respx (never the real server)."""

from __future__ import annotations

import httpx
import pytest
import respx

from campuspilot.config import get_settings
from campuspilot.llm.base import ModelOffline, ModelTimeout
from campuspilot.llm.fallback import FallbackClient, to_openai_messages
from campuspilot.llm.ollama import OllamaClient
from campuspilot.tools.registry import offered_tools, tool_schemas
from tests.backend_helpers import OLLAMA, ndjson

CHAT_URL = f"{OLLAMA}/api/chat"


def _tool_reply() -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "x",
                    "function": {
                        "index": 0,
                        "name": "search_campus_docs",
                        "arguments": {"query": "academic calendar"},
                    },
                }
            ],
        },
        "done": True,
    }


@respx.mock
async def test_chat_parses_tool_calls_and_sends_expected_payload() -> None:
    route = respx.post(CHAT_URL).respond(json=_tool_reply())
    tools = tool_schemas(offered_tools("live", False))
    reply = await OllamaClient().chat([{"role": "user", "content": "hi"}], tools)

    assert reply.tool_calls[0].name == "search_campus_docs"
    assert reply.tool_calls[0].arguments == {"query": "academic calendar"}
    body = route.calls[0].request.content.decode()
    assert '"think": false' in body or '"think":false' in body
    assert "num_ctx" not in body
    assert '"stream": false' in body or '"stream":false' in body
    assert "search_campus_docs" in body


@respx.mock
async def test_chat_retries_connect_error_once_then_offline() -> None:
    route = respx.post(CHAT_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ModelOffline):
        await OllamaClient().chat([{"role": "user", "content": "hi"}], None)
    assert route.call_count == 2


@respx.mock
async def test_chat_recovers_when_second_connect_works() -> None:
    route = respx.post(CHAT_URL).mock(
        side_effect=[httpx.ConnectError("blip"), httpx.Response(200, json=_tool_reply())]
    )
    reply = await OllamaClient().chat([{"role": "user", "content": "hi"}], None)
    assert route.call_count == 2 and reply.tool_calls


@respx.mock
async def test_chat_read_timeout_maps_to_model_timeout() -> None:
    respx.post(CHAT_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ModelTimeout):
        await OllamaClient().chat([{"role": "user", "content": "hi"}], None)


@respx.mock
async def test_stream_yields_ndjson_pieces() -> None:
    body = ndjson(
        {"message": {"content": "Hel"}, "done": False},
        {"message": {"content": "lo"}, "done": False},
        {"message": {"content": ""}, "done": True},
    )
    route = respx.post(CHAT_URL).respond(content=body)
    pieces = [p async for p in OllamaClient().stream([{"role": "user", "content": "hi"}])]
    assert pieces == ["Hel", "lo"]
    assert "num_ctx" not in route.calls[0].request.content.decode()


@respx.mock
async def test_stream_offline_raises_model_offline() -> None:
    respx.post(CHAT_URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(ModelOffline):
        async for _ in OllamaClient().stream([{"role": "user", "content": "hi"}]):
            pass


@respx.mock
async def test_list_and_loaded_models() -> None:
    respx.get(f"{OLLAMA}/api/tags").respond(json={"models": [{"name": "gemma4:26b-a4b-it-q4_K_M"}]})
    respx.get(f"{OLLAMA}/api/ps").respond(json={"models": []})
    client = OllamaClient()
    assert await client.list_models() == ["gemma4:26b-a4b-it-q4_K_M"]
    assert await client.loaded_models() == []


@respx.mock
async def test_list_models_offline() -> None:
    respx.get(f"{OLLAMA}/api/tags").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(ModelOffline):
        await OllamaClient().list_models()


def test_tool_schemas_come_from_input_models() -> None:
    schemas = {s["function"]["name"]: s for s in tool_schemas(offered_tools("live", False))}
    assert set(schemas) >= {"search_campus_docs", "ask_clarification", "get_my_deadlines"}
    params = schemas["search_campus_docs"]["function"]["parameters"]
    assert "query" in params["properties"] and "title" not in params


def test_moodle_tools_hidden_in_fallback_without_consent() -> None:
    hidden = {t.name for t in offered_tools("fallback", False)}
    assert "get_my_deadlines" not in hidden and "search_campus_docs" in hidden
    assert "get_my_deadlines" in {t.name for t in offered_tools("fallback", True)}
    assert "get_my_deadlines" in {t.name for t in offered_tools("live", False)}


@respx.mock
async def test_fallback_client_uses_openai_format(monkeypatch) -> None:
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "small")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "key-123")
    get_settings.cache_clear()
    route = respx.post("https://llm.example/v1/chat/completions").respond(
        json={
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "get_official_link",
                                    "arguments": '{"topic": "hostel"}',
                                }
                            }
                        ],
                    }
                }
            ]
        }
    )
    reply = await FallbackClient().chat([{"role": "user", "content": "hi"}], None)
    assert reply.tool_calls[0].arguments == {"topic": "hostel"}
    assert route.calls[0].request.headers["authorization"] == "Bearer key-123"


def test_openai_message_conversion_turns_tool_results_into_user_text() -> None:
    out = to_openai_messages(
        [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "x"}}]},
            {"role": "tool", "tool_name": "x", "content": "<evidence>"},
        ]
    )
    assert out == [{"role": "user", "content": "Tool result (x):\n<evidence>"}]
