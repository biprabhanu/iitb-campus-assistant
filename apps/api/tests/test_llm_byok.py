"""BYOKClient: payloads, model choice, and the CONTRACT §10.3 error mapping."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from campuspilot.config import get_settings
from campuspilot.llm.base import ProviderError
from campuspilot.llm.byok import BYOKClient
from campuspilot.llm.providers import PROVIDERS
from tests.hosted_helpers import FAKE_KEY, GROQ_URL, completion, sse_stream, tool_call

MESSAGES = [{"role": "user", "content": "hello"}]


def make(model: str | None = None) -> BYOKClient:
    return BYOKClient(PROVIDERS["groq"], FAKE_KEY, model, get_settings())


@respx.mock
async def test_chat_uses_router_model_temperature_zero_and_tools() -> None:
    route = respx.post(GROQ_URL).mock(
        return_value=completion(tool_calls=[tool_call("search_campus_docs", query="fees")])
    )
    reply = await make().chat(MESSAGES, [{"type": "function"}])
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "llama-3.1-8b-instant" and body["temperature"] == 0
    assert body["tools"] and "stream" not in body
    assert route.calls[0].request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert reply.tool_calls[0].name == "search_campus_docs"
    assert reply.tool_calls[0].arguments == {"query": "fees"}


@respx.mock
async def test_stream_uses_answer_model_and_caps_output() -> None:
    route = respx.post(GROQ_URL).mock(return_value=sse_stream("Hel", "lo"))
    pieces = [p async for p in make().stream(MESSAGES)]
    body = json.loads(route.calls[0].request.content)
    assert pieces == ["Hel", "lo"]
    assert body["model"] == "llama-3.3-70b-versatile" and body["temperature"] == 0.2
    assert body["max_tokens"] == 400 and body["stream"] is True


@respx.mock
async def test_model_override_applies_to_both_models() -> None:
    route = respx.post(GROQ_URL).mock(return_value=completion("ok"))
    client = make("openai/gpt-oss-20b")
    await client.chat(MESSAGES, None)
    assert json.loads(route.calls[0].request.content)["model"] == "openai/gpt-oss-20b"
    assert client.model == "openai/gpt-oss-20b" and client.mode == "byok"


@respx.mock
async def test_check_sends_one_token_request() -> None:
    route = respx.post(GROQ_URL).mock(return_value=completion("a"))
    await make().check()
    body = json.loads(route.calls[0].request.content)
    assert body["max_tokens"] == 1 and body["model"] == "llama-3.1-8b-instant"


@pytest.mark.parametrize("status", [401, 403])
@respx.mock
async def test_key_rejected(status: int) -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(status))
    with pytest.raises(ProviderError) as exc:
        await make().chat(MESSAGES, None)
    assert exc.value.code == "PROVIDER_KEY_REJECTED" and exc.value.provider == "groq"
    assert str(exc.value) == "Your Groq key was rejected. Check it in Settings."


@respx.mock
async def test_rate_limited_carries_retry_after() -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(429, headers={"retry-after": "17"}))
    with pytest.raises(ProviderError) as exc:
        await make().chat(MESSAGES, None)
    assert exc.value.code == "PROVIDER_RATE_LIMITED" and exc.value.retry_after_s == 17
    assert "free limit" in exc.value.message


@respx.mock
async def test_rate_limited_without_header_has_no_retry_after() -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(ProviderError) as exc:
        await make().chat(MESSAGES, None)
    assert exc.value.retry_after_s is None


@respx.mock
async def test_timeout_is_retried_once_then_reported() -> None:
    route = respx.post(GROQ_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderError) as exc:
        await make().chat(MESSAGES, None)
    assert exc.value.code == "PROVIDER_TIMEOUT" and route.call_count == 2


@respx.mock
async def test_timeout_then_success() -> None:
    route = respx.post(GROQ_URL).mock(side_effect=[httpx.ReadTimeout("slow"), completion("fine")])
    reply = await make().chat(MESSAGES, None)
    assert reply.content == "fine" and route.call_count == 2


@pytest.mark.parametrize("status", [400, 500, 503])
@respx.mock
async def test_other_errors_are_not_retried(status: int) -> None:
    route = respx.post(GROQ_URL).mock(return_value=httpx.Response(status, text="boom"))
    with pytest.raises(ProviderError) as exc:
        await make().chat(MESSAGES, None)
    assert exc.value.code == "PROVIDER_ERROR" and route.call_count == 1
    assert exc.value.message == "Groq returned an error. Please try again."


@respx.mock
async def test_connection_error_maps_to_provider_error_without_key() -> None:
    respx.post(GROQ_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ProviderError) as exc:
        await make().chat(MESSAGES, None)
    assert exc.value.code == "PROVIDER_ERROR"
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


@respx.mock
async def test_stream_error_status_maps() -> None:
    respx.post(GROQ_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(ProviderError) as exc:
        [p async for p in make().stream(MESSAGES)]
    assert exc.value.code == "PROVIDER_KEY_REJECTED"


@respx.mock
async def test_key_never_in_repr_or_errors() -> None:
    client = make()
    assert FAKE_KEY not in repr(client) and FAKE_KEY not in str(vars(client).get("provider"))
    respx.post(GROQ_URL).mock(return_value=httpx.Response(401, text=FAKE_KEY))
    with pytest.raises(ProviderError) as exc:
        await client.chat(MESSAGES, None)
    shown = f"{exc.value!s}{exc.value!r}{exc.value.args}{exc.value.__dict__}"
    assert FAKE_KEY not in shown
