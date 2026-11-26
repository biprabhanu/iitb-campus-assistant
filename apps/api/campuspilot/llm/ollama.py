"""Client for Ollama's native /api/chat endpoint (through the SSH tunnel).

Notes:
- `think: false` keeps Gemma from spending time on hidden reasoning.
- We never send `num_ctx`: changing it makes Ollama reload the model.
- Tool results go back as {"role": "tool", "tool_name": ..., "content": ...}.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from campuspilot.config import Settings, get_settings
from campuspilot.llm.base import (
    LLMError,
    LLMReply,
    Message,
    ModelOffline,
    ModelTimeout,
    ToolCall,
)

_STATUS_TIMEOUT_S = 3.0


def parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments are normally a dict; accept a JSON string too (OpenAI style)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {"_unparsable": True}  # fails validation later, on purpose
        return value if isinstance(value, dict) else {"_unparsable": True}
    return {}


def _map_http_error(exc: httpx.HTTPError) -> LLMError:
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout):
        return ModelOffline("The model server is not reachable.")
    if isinstance(exc, httpx.TimeoutException):
        return ModelTimeout("The model took too long to answer.")
    return LLMError("The model connection failed.")


class OllamaClient:
    mode = "live"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.model = self._settings.ollama_model
        self._base = self._settings.ollama_base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            self._settings.ollama_timeout_s, connect=self._settings.ollama_connect_timeout_s
        )

    def _payload(self, messages: list[Message], stream: bool) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "think": False,
            "options": {"temperature": 0.2},
        }

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None) -> LLMReply:
        payload = self._payload(messages, stream=False)
        if tools:
            payload["tools"] = tools
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await self._post_with_retry(client, payload)
        data = response.json()
        message = data.get("message") or {}
        calls = [
            ToolCall(
                name=(call.get("function") or {}).get("name", ""),
                arguments=parse_arguments((call.get("function") or {}).get("arguments")),
            )
            for call in message.get("tool_calls") or []
        ]
        return LLMReply(content=message.get("content") or "", tool_calls=calls)

    async def _post_with_retry(self, client: httpx.AsyncClient, payload: dict[str, Any]):
        """POST once; if the connection fails, try one more time (tunnels blip)."""
        for attempt in (1, 2):
            try:
                response = await client.post(f"{self._base}/api/chat", json=payload)
                break
            except httpx.ConnectError as exc:
                if attempt == 2:
                    raise _map_http_error(exc) from exc
            except httpx.HTTPError as exc:
                raise _map_http_error(exc) from exc
        if response.status_code >= 400:
            raise LLMError("The model returned an error.")
        return response

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        payload = self._payload(messages, stream=True)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await self._open_stream(client, payload)
            try:
                if response.status_code >= 400:
                    raise LLMError("The model returned an error.")
                async for line in response.aiter_lines():
                    text, done = self._parse_line(line)
                    if text:
                        yield text
                    if done:
                        break
            except httpx.HTTPError as exc:
                raise _map_http_error(exc) from exc
            finally:
                await response.aclose()

    async def _open_stream(self, client: httpx.AsyncClient, payload: dict[str, Any]):
        request = client.build_request("POST", f"{self._base}/api/chat", json=payload)
        for attempt in (1, 2):
            try:
                return await client.send(request, stream=True)
            except httpx.ConnectError as exc:
                if attempt == 2:
                    raise _map_http_error(exc) from exc
            except httpx.HTTPError as exc:
                raise _map_http_error(exc) from exc
        raise ModelOffline("The model server is not reachable.")  # pragma: no cover

    @staticmethod
    def _parse_line(line: str) -> tuple[str, bool]:
        """One NDJSON line -> (text piece, is_last)."""
        if not line.strip():
            return "", False
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return "", False
        text = (data.get("message") or {}).get("content") or ""
        return text, bool(data.get("done"))

    # ---------- status helpers ----------

    async def _get_names(self, path: str) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=_STATUS_TIMEOUT_S) as client:
                response = await client.get(f"{self._base}{path}")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise _map_http_error(exc) from exc
        models = response.json().get("models") or []
        return [m.get("name") or m.get("model") or "" for m in models]

    async def list_models(self) -> list[str]:
        """Names of models installed on the server (/api/tags)."""
        return await self._get_names("/api/tags")

    async def loaded_models(self) -> list[str]:
        """Names of models currently in GPU memory (/api/ps)."""
        return await self._get_names("/api/ps")
