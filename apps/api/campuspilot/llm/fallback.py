"""Optional OpenAI-compatible fallback (/chat/completions).

Only used when LLM_FALLBACK_ENABLED=true and Ollama is offline. Moodle tools are
not offered to it unless ALLOW_PERSONAL_DATA_TO_CLOUD=true (decided by the orchestrator).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from campuspilot.config import Settings, get_settings
from campuspilot.llm.base import LLMError, LLMReply, Message, ModelOffline, ToolCall
from campuspilot.llm.ollama import _map_http_error, parse_arguments


def to_openai_messages(messages: list[Message]) -> list[Message]:
    """Convert our Ollama-style history into plain OpenAI chat messages.

    Tool results become user messages and assistant tool-call stubs are dropped. That is
    less strict than the real tool protocol but works with any compatible server.
    """
    converted: list[Message] = []
    for msg in messages:
        role = msg["role"]
        if role == "tool":
            converted.append(
                {
                    "role": "user",
                    "content": f"Tool result ({msg.get('tool_name')}):\n{msg['content']}",
                }
            )
        elif role == "assistant" and msg.get("tool_calls") and not msg.get("content"):
            continue
        else:
            converted.append({"role": role, "content": msg["content"]})
    return converted


class FallbackClient:
    mode = "fallback"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.model = self._settings.llm_fallback_model
        self._base = self._settings.llm_fallback_base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            self._settings.ollama_timeout_s, connect=self._settings.ollama_connect_timeout_s
        )

    def _headers(self) -> dict[str, str]:
        key = self._settings.llm_fallback_api_key.get_secret_value()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _payload(self, messages: list[Message], stream: bool) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "stream": stream,
            "temperature": 0.2,
        }

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None) -> LLMReply:
        payload = self._payload(messages, stream=False)
        if tools:
            payload["tools"] = tools
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base}/chat/completions", json=payload, headers=self._headers()
                )
        except httpx.HTTPError as exc:
            raise _map_http_error(exc) from exc
        if response.status_code >= 400:
            raise LLMError("The fallback model returned an error.")
        choices = response.json().get("choices") or []
        if not choices:
            raise LLMError("The fallback model returned no answer.")
        message = choices[0].get("message") or {}
        calls = [
            ToolCall(
                name=(c.get("function") or {}).get("name", ""),
                arguments=parse_arguments((c.get("function") or {}).get("arguments")),
            )
            for c in message.get("tool_calls") or []
        ]
        return LLMReply(content=message.get("content") or "", tool_calls=calls)

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        payload = self._payload(messages, stream=True)
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream(
                    "POST", f"{self._base}/chat/completions", json=payload, headers=self._headers()
                ) as response,
            ):
                if response.status_code >= 400:
                    raise LLMError("The fallback model returned an error.")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    try:
                        delta = json.loads(body)["choices"][0].get("delta") or {}
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta.get("content"):
                        yield delta["content"]
        except httpx.ConnectError as exc:
            raise ModelOffline("The fallback model is not reachable.") from exc
        except httpx.HTTPError as exc:
            raise _map_http_error(exc) from exc
