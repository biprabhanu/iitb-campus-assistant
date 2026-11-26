"""Bring-your-own-key providers (hosted mode). Lead-owned: this table is a security decision.

The client only ever names a provider id from this allowlist. Base URLs are fixed here and
are never taken from a request, so a client cannot make the server call an arbitrary address.
All four speak the OpenAI-compatible /chat/completions API with tool calling.

Default model ids are checked in Phase 0 (see docs/DEPLOY.md "Default models"). `tested`
says whether a live tool-call probe passed with a real key on the date recorded there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ProviderId = Literal["groq", "gemini", "openai", "openrouter"]

# A key is opaque to us: only a length limit and a conservative character set.
KEY_RE = re.compile(r"^[A-Za-z0-9_\-.]{20,300}$")
# Model ids such as "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "meta-llama/x:free".
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,99}$")


@dataclass(frozen=True)
class Provider:
    id: ProviderId
    label: str  # shown in the UI and in error messages ("Your Groq key was rejected")
    base_url: str  # hard-coded; never from the client
    router_model: str  # small/fast: clarify pre-check and tool routing
    answer_model: str  # larger: the streamed final answer
    key_url: str  # official page where a student creates a key
    recommended: bool = False
    free_tier: bool = False
    note: str = ""  # one line for the key card
    tested: bool = False  # live tool-call probe passed (date in docs/DEPLOY.md)


PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        id="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        router_model="llama-3.1-8b-instant",
        answer_model="llama-3.3-70b-versatile",
        key_url="https://console.groq.com/keys",
        recommended=True,
        free_tier=True,
        note="Recommended. Free, no card needed.",
    ),
    "gemini": Provider(
        id="gemini",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        router_model="gemini-2.5-flash-lite",
        answer_model="gemini-2.5-flash",
        key_url="https://aistudio.google.com/app/apikey",
        free_tier=True,
        note=(
            "Google's free tier may use your prompts to improve its products; Groq is recommended."
        ),
    ),
    "openai": Provider(
        id="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        router_model="gpt-4.1-nano",
        answer_model="gpt-4.1-mini",
        key_url="https://platform.openai.com/api-keys",
        note="Paid; billed to your OpenAI account.",
    ),
    "openrouter": Provider(
        id="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        router_model="meta-llama/llama-3.3-70b-instruct:free",
        answer_model="meta-llama/llama-3.3-70b-instruct:free",
        key_url="https://openrouter.ai/settings/keys",
        note="Free models have low daily limits.",
    ),
}


def get_provider(provider_id: str) -> Provider | None:
    return PROVIDERS.get(provider_id.strip().lower())


def valid_key(key: str) -> bool:
    return bool(KEY_RE.fullmatch(key))


def valid_model(model: str) -> bool:
    return bool(MODEL_RE.fullmatch(model))
