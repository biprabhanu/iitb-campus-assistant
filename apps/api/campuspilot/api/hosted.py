"""Hosted mode: read the per-request headers (CONTRACT §10.2, §10.5).

The student's LLM key and Moodle credentials arrive in headers, live for one request, and are
never stored or logged. Errors raised here use fixed messages that do not echo header values.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from starlette.requests import Request

from campuspilot.api.errors import ApiError
from campuspilot.config import Settings
from campuspilot.llm.base import LLMClient
from campuspilot.llm.byok import BYOKClient
from campuspilot.llm.mock import MockLLM
from campuspilot.llm.providers import Provider, get_provider, valid_key, valid_model
from campuspilot.moodle import credentials as moodle_credentials
from campuspilot.moodle.errors import MoodleError


@dataclass
class ByoKey:
    provider: Provider
    key: str = field(repr=False)  # never printed
    model: str | None = None


def read_byo_key(request: Request) -> ByoKey:
    """Check X-LLM-* headers in the order the contract fixes: present -> provider/model -> key."""
    provider_id = request.headers.get("x-llm-provider", "").strip()
    key = request.headers.get("x-llm-key", "").strip()
    if not provider_id or not key:
        raise ApiError(
            401,
            "MODEL_KEY_REQUIRED",
            "Add your own model key in Settings to start chatting.",
        )
    provider = get_provider(provider_id)
    if provider is None:
        raise ApiError(400, "BAD_REQUEST", "That model provider is not supported.")
    model = request.headers.get("x-llm-model", "").strip() or None
    if model is not None and not valid_model(model):
        raise ApiError(400, "BAD_REQUEST", "That model name is not valid.")
    if not valid_key(key):
        raise ApiError(
            401,
            "PROVIDER_KEY_REJECTED",
            f"Your {provider.label} key was rejected. Check it in Settings.",
        )
    return ByoKey(provider, key, model)


def build_llm(byo: ByoKey, settings: Settings) -> LLMClient:
    """The client for one hosted request. With CAMPUSPILOT_MOCK_LLM the headers are still
    required (so the UI flow is the same) but the scripted MockLLM answers."""
    if settings.campuspilot_mock_llm:
        return MockLLM()
    return BYOKClient(byo.provider, byo.key, byo.model, settings)


def read_moodle_credentials(request: Request) -> moodle_credentials.RequestCredentials | None:
    """X-Moodle-Token / X-Moodle-Ical-Url -> credentials, or None for demo data."""
    try:
        return moodle_credentials.parse_request_credentials(
            request.headers.get("x-moodle-token"), request.headers.get("x-moodle-ical-url")
        )
    except MoodleError as exc:
        raise ApiError(400, "BAD_REQUEST", exc.message) from None
