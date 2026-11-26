"""HTTP endpoints (CONTRACT §2)."""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from campuspilot.agent.orchestrator import RunTrace, run_chat
from campuspilot.api import hosted
from campuspilot.api.errors import ApiError
from campuspilot.api.ratelimit import RateLimiter, client_ip
from campuspilot.api.sse import format_sse
from campuspilot.config import get_settings
from campuspilot.llm.base import LLMClient, LLMError, ProviderError
from campuspilot.llm.byok import BYOKClient
from campuspilot.llm.mock import MockLLM
from campuspilot.llm.ollama import OllamaClient
from campuspilot.llm.providers import PROVIDERS
from campuspilot.llm.select import select_llm
from campuspilot.schemas.chat import (
    ChatRequest,
    KnowledgeSearchRequest,
    LLMCheckResponse,
    MoodleTokenRequest,
    MoodleTokenResponse,
    ProviderInfo,
    SourcePublic,
    StatusResponse,
)
from campuspilot.schemas.tools import SearchCampusDocsInput, SearchCampusDocsOutput

router = APIRouter()
log = logging.getLogger("campuspilot.request")


def _retrieval() -> Any:
    return importlib.import_module("campuspilot.retrieval.tools")


def _moodle() -> Any:
    return importlib.import_module("campuspilot.moodle.tools")


def _credentials() -> Any:
    return importlib.import_module("campuspilot.moodle.credentials")


# ---------- health and status ----------


@router.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


async def _model_status(settings: Any) -> tuple[bool, bool, str, str]:
    """(online, loaded, model name, mode) - never raises."""
    if settings.campuspilot_mock_llm:
        return True, True, MockLLM.model, "mock"
    client = OllamaClient(settings)
    try:
        await client.list_models()
    except LLMError:
        mode = "fallback" if settings.llm_fallback_enabled else "live"
        return False, False, settings.ollama_model, mode
    try:
        loaded = settings.ollama_model in await client.loaded_models()
    except LLMError:
        loaded = False
    return True, loaded, settings.ollama_model, "live"


async def _moodle_status() -> tuple[str, str]:
    try:
        return await _moodle().moodle_status()
    except Exception:
        return "error", "none"


async def _count_sources() -> int:
    try:
        return int(await asyncio.to_thread(_retrieval().count_indexed_sources))
    except Exception:
        return 0


def _provider_infos() -> list[ProviderInfo]:
    return [
        ProviderInfo(
            id=p.id,
            label=p.label,
            router_model=p.router_model,
            answer_model=p.answer_model,
            key_url=p.key_url,
            recommended=p.recommended,
            free_tier=p.free_tier,
            note=p.note,
            tested=p.tested,
        )
        for p in PROVIDERS.values()
    ]


@router.get("/v1/status", response_model=StatusResponse)
async def status(request: Request) -> StatusResponse:
    settings = get_settings()
    info = request.app.state.index_info
    common = {
        "deploy_mode": settings.deploy_mode,
        "index": info.kind,
        "index_version": info.version,
    }
    (moodle, moodle_mode), sources = await asyncio.gather(_moodle_status(), _count_sources())
    if settings.hosted:  # no Ollama: the model is each student's own key
        return StatusResponse(
            model_online=True,
            model_loaded=True,
            model="byok",
            moodle=moodle,  # type: ignore[arg-type]
            moodle_mode=moodle_mode,
            sources_indexed=sources,
            mode="byok",
            providers=_provider_infos(),
            **common,  # type: ignore[arg-type]
        )
    online, loaded, model, mode = await _model_status(settings)
    return StatusResponse(
        model_online=online,
        model_loaded=loaded,
        model=model,
        moodle=moodle,  # type: ignore[arg-type]
        moodle_mode=moodle_mode,
        sources_indexed=sources,
        mode=mode,  # type: ignore[arg-type]
        **common,  # type: ignore[arg-type]
    )


# ---------- chat ----------


def rate_limit(request: Request) -> None:
    """Dependency: runs before the body is validated."""
    limiter: RateLimiter = request.app.state.rate_limiter
    wait = limiter.check(client_ip(request, get_settings().hosted))
    if wait is not None:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Too many requests. Please wait a bit and retry.",
            retry_after_s=wait,
        )


@dataclass
class ChatContext:
    """What the headers of one chat request gave us (hosted only)."""

    byo: hosted.ByoKey | None = None
    moodle: Any = None  # RequestCredentials | None


def chat_context(request: Request) -> ChatContext:
    """Dependency: hosted headers in the contract's order, before any work. Local ignores them."""
    if not get_settings().hosted:
        return ChatContext()
    byo = hosted.read_byo_key(request)
    return ChatContext(byo=byo, moodle=hosted.read_moodle_credentials(request))


def _log_line(trace: RunTrace) -> None:
    log.info(
        "request_id=%s model=%s mode=%s provider=%s tools=%s chunks=%s latency_ms=%d error_code=%s",
        trace.request_id,
        trace.model,
        trace.mode,
        trace.provider or "-",
        trace.tools,
        trace.chunk_ids,
        trace.latency_ms,
        trace.error_code or "-",
    )


async def _event_stream(body: ChatRequest, ctx: ChatContext) -> AsyncIterator[str]:
    settings = get_settings()
    trace = RunTrace(request_id=uuid.uuid4().hex[:8])
    started = time.monotonic()
    creds = _credentials()
    moodle_token = creds.set_request_credentials(ctx.moodle) if settings.hosted else None
    try:
        if ctx.byo is not None:
            trace.provider = ctx.byo.provider.id
            llm: LLMClient = hosted.build_llm(ctx.byo, settings)
        else:
            llm = await select_llm(settings)
        async for name, data in run_chat(body, llm, trace, settings):
            yield format_sse(name, data)
    finally:  # also runs when the browser disconnects
        if moodle_token is not None:
            creds.reset_request_credentials(moodle_token)
        trace.latency_ms = int((time.monotonic() - started) * 1000)
        _log_line(trace)


@router.post("/v1/chat", dependencies=[Depends(rate_limit)])
async def chat(body: ChatRequest, ctx: ChatContext = Depends(chat_context)) -> StreamingResponse:
    headers = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    return StreamingResponse(
        _event_stream(body, ctx), media_type="text/event-stream", headers=headers
    )


# ---------- key and Moodle checks (hosted) ----------

_CHECK_STATUS = {
    "PROVIDER_KEY_REJECTED": 401,
    "PROVIDER_RATE_LIMITED": 429,
    "PROVIDER_TIMEOUT": 504,
    "PROVIDER_ERROR": 502,
}


@router.post(
    "/v1/llm/check",
    response_model=LLMCheckResponse,
    dependencies=[Depends(rate_limit)],
)
async def llm_check(request: Request) -> Any:
    settings = get_settings()
    if not settings.hosted:
        raise ApiError(404, "NOT_AVAILABLE", "Model keys are only used in the hosted version.")
    byo = hosted.read_byo_key(request)
    client = hosted.build_llm(byo, settings)
    if not isinstance(client, BYOKClient):  # mock mode: nothing to call
        return LLMCheckResponse(ok=True, provider=byo.provider.id, model=client.model)
    try:
        await client.check()
    except ProviderError as exc:
        result = LLMCheckResponse(
            ok=False,
            provider=exc.provider,
            model=client.router_model,
            code=exc.code,  # type: ignore[arg-type]
            message=exc.message,
        )
        return JSONResponse(result.model_dump(), status_code=_CHECK_STATUS.get(exc.code, 502))
    return LLMCheckResponse(ok=True, provider=byo.provider.id, model=client.router_model)


@router.post(
    "/v1/moodle/check",
    response_model=MoodleTokenResponse,
    dependencies=[Depends(rate_limit)],
)
async def moodle_check(request: Request) -> Any:
    settings = get_settings()
    creds = _credentials()
    module = _moodle()
    given = hosted.read_moodle_credentials(request) if settings.hosted else None
    reset = creds.set_request_credentials(given)
    try:
        return await module.check_credentials()
    except module.MoodleError as exc:
        if settings.hosted and exc.code in ("unavailable", "timeout"):
            raise ApiError(
                503,
                "NOT_AVAILABLE",
                "Moodle isn't reachable from the hosted version. Use the local app.",
            ) from None
        raise ApiError(400, "BAD_REQUEST", exc.message) from None
    finally:
        creds.reset_request_credentials(reset)


# ---------- knowledge, sources ----------


@router.post(
    "/v1/knowledge/search",
    response_model=SearchCampusDocsOutput,
    dependencies=[Depends(rate_limit)],
)
async def knowledge_search(body: KnowledgeSearchRequest) -> Any:
    args = SearchCampusDocsInput(**body.model_dump())
    return await asyncio.to_thread(_retrieval().search_campus_docs, args)


@router.get("/v1/sources", response_model=list[SourcePublic])
async def sources() -> Any:
    return await asyncio.to_thread(_retrieval().list_sources)


# ---------- Moodle credentials (never echoed) ----------


def _no_keychain_when_hosted() -> None:
    if get_settings().hosted:
        raise ApiError(404, "NOT_AVAILABLE", "Saving a Moodle token isn't available here.")


@router.post("/v1/moodle/token", response_model=MoodleTokenResponse)
async def save_moodle_token(body: MoodleTokenRequest) -> Any:
    _no_keychain_when_hosted()
    if bool(body.token) == bool(body.ical_url):
        raise ApiError(400, "BAD_REQUEST", "Send either a Moodle token or an iCal URL, not both.")
    module = _moodle()
    try:
        return await module.save_credentials(body)
    except module.MoodleError as exc:
        raise ApiError(400, "BAD_REQUEST", exc.message) from None  # drop context: may hold secrets


@router.delete("/v1/moodle/token", response_model=MoodleTokenResponse)
async def delete_moodle_token() -> Any:
    _no_keychain_when_hosted()
    return await asyncio.to_thread(_moodle().delete_credentials)
