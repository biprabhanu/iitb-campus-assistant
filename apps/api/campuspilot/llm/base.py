"""Shared types for every LLM client (Ollama, fallback, mock)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from campuspilot.schemas.chat import Mode


class LLMError(Exception):
    """Base class for model failures. The message is safe to show to users."""


class ModelOffline(LLMError):
    """The model server cannot be reached (tunnel down, connection refused, DNS)."""


class ModelTimeout(LLMError):
    """The model server was reached but did not answer in time."""


class ProviderError(LLMError):
    """A hosted-mode provider (Groq, Gemini...) refused or failed. Safe to show to students.

    `code` is one of the PROVIDER_* error codes. Neither the message nor the attributes ever
    contain the student's API key.
    """

    def __init__(
        self, code: str, provider: str, message: str, retry_after_s: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.message = message
        self.retry_after_s = retry_after_s


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMReply:
    """One non-streaming model reply: some text and/or tool requests."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


Message = dict[str, Any]


class LLMClient(Protocol):
    mode: Mode
    model: str

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]] | None) -> LLMReply:
        """Non-streaming call, used to let the model pick tools."""
        ...

    def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        """Streaming call for the final answer; yields text pieces."""
        ...
