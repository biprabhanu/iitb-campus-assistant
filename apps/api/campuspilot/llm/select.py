"""Pick which LLM client serves a chat request."""

from __future__ import annotations

from campuspilot.config import Settings
from campuspilot.llm.base import LLMClient, LLMError
from campuspilot.llm.fallback import FallbackClient
from campuspilot.llm.mock import MockLLM
from campuspilot.llm.ollama import OllamaClient


async def select_llm(settings: Settings) -> LLMClient:
    if settings.campuspilot_mock_llm:
        return MockLLM()
    ollama = OllamaClient(settings)
    if settings.llm_fallback_enabled and settings.llm_fallback_base_url:
        try:
            await ollama.list_models()  # quick (3 s) reachability probe
        except LLMError:
            return FallbackClient(settings)
    return ollama
