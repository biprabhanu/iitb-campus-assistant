"""Hosted-mode LLM client: the student's own key against one allow-listed provider.

Every provider speaks the OpenAI-compatible `/chat/completions` API. The base URL comes only
from `llm/providers.py`, never from a request. The key is held for one request, sent only in
the Authorization header, and kept out of every exception, repr and log line.

Errors become `ProviderError` (CONTRACT §10.3). A timeout is retried once; nothing else is
retried and we never switch to another provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from campuspilot.config import Settings
from campuspilot.llm.base import LLMReply, Message, ProviderError, ToolCall
from campuspilot.llm.fallback import to_openai_messages
from campuspilot.llm.ollama import parse_arguments
from campuspilot.llm.providers import Provider


def _retry_after(headers: httpx.Headers) -> int | None:
    """Seconds from a `retry-after` header, if it is a plain number."""
    try:
        return max(1, int(float(headers.get("retry-after", ""))))
    except ValueError:
        return None


def error_for_status(provider: Provider, status: int, headers: httpx.Headers) -> ProviderError:
    """Map an HTTP error status to the right ProviderError."""
    name = provider.label
    if status in (401, 403):
        return ProviderError(
            "PROVIDER_KEY_REJECTED",
            provider.id,
            f"Your {name} key was rejected. Check it in Settings.",
        )
    if status == 429:
        return ProviderError(
            "PROVIDER_RATE_LIMITED",
            provider.id,
            f"{name} says you've hit your free limit; try again in a minute.",
            retry_after_s=_retry_after(headers),
        )
    return ProviderError(
        "PROVIDER_ERROR", provider.id, f"{name} returned an error. Please try again."
    )


class BYOKClient:
    mode = "byok"

    def __init__(
        self, provider: Provider, key: str, model_override: str | None, settings: Settings
    ) -> None:
        self.provider = provider
        self._key = key
        self.router_model = model_override or provider.router_model
        self.model = model_override or provider.answer_model  # the streamed answer
        self._base = provider.base_url.rstrip("/")
        self._max_output = settings.hosted_max_output_tokens
        self._timeout = httpx.Timeout(settings.provider_timeout_s)

    def __repr__(self) -> str:  # no key, ever
        return f"BYOKClient(provider={self.provider.id!r}, model={self.model!r})"

    # ---------- plumbing ----------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}

    def _payload(self, model: str, messages: list[Message], temperature: float) -> dict[str, Any]:
        return {
            "model": model,
            "messages": to_openai_messages(messages),
            "temperature": temperature,
        }

    def _timeout_error(self) -> ProviderError:
        return ProviderError(
            "PROVIDER_TIMEOUT",
            self.provider.id,
            f"{self.provider.label} took too long to answer. Please try again.",
        )

    def _generic_error(self) -> ProviderError:
        return error_for_status(self.provider, 500, httpx.Headers())

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST once, retrying a single time after a timeout. Returns the JSON reply."""
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base}/chat/completions", json=payload, headers=self._headers()
                    )
            except httpx.TimeoutException:
                if attempt == 2:
                    raise self._timeout_error() from None
                continue
            except httpx.HTTPError:
                raise self._generic_error() from None
            if response.status_code >= 400:
                raise error_for_status(self.provider, response.status_code, response.headers)
            try:
                return response.json()
            except ValueError:
                raise self._generic_error() from None
        raise self._timeout_error()  # unreachable; keeps type checkers happy

    # ---------- LLMClient interface ----------

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None) -> LLMReply:
        """Router call: small model, temperature 0, tools allowed."""
        payload = self._payload(self.router_model, messages, 0)
        if tools:
            payload["tools"] = tools
        data = await self._post(payload)
        choices = data.get("choices") or []
        if not choices:
            raise self._generic_error()
        message = choices[0].get("message") or {}
        calls = [
            ToolCall(
                name=(c.get("function") or {}).get("name", ""),
                arguments=parse_arguments((c.get("function") or {}).get("arguments")),
            )
            for c in message.get("tool_calls") or []
        ]
        return LLMReply(content=message.get("content") or "", tool_calls=calls)

    async def check(self) -> None:
        """One tiny router call (1 output token) to test the key. Raises ProviderError."""
        payload = self._payload(self.router_model, [{"role": "user", "content": "hi"}], 0)
        payload["max_tokens"] = 1
        await self._post(payload)

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        """Answer call: bigger model, temperature 0.2, capped output."""
        payload = self._payload(self.model, messages, 0.2)
        payload.update(stream=True, max_tokens=self._max_output)
        for attempt in (1, 2):
            started = False
            try:
                async for piece in self._stream_once(payload):
                    started = True
                    yield piece
                return
            except httpx.TimeoutException:
                if started or attempt == 2:  # never repeat text the student already saw
                    raise self._timeout_error() from None
            except httpx.HTTPError:
                raise self._generic_error() from None

    async def _stream_once(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        async with (
            httpx.AsyncClient(timeout=self._timeout) as client,
            client.stream(
                "POST", f"{self._base}/chat/completions", json=payload, headers=self._headers()
            ) as response,
        ):
            if response.status_code >= 400:
                raise error_for_status(self.provider, response.status_code, response.headers)
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
