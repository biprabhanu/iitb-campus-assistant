"""HTTP endpoints (CONTRACT §2)."""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from campuspilot.agent.orchestrator import RunTrace, run_chat
from campuspilot.api.sse import RateLimiter, format_sse
from campuspilot.config import get_settings
from campuspilot.llm.base import LLMError
from campuspilot.llm.mock import MockLLM
from campuspilot.llm.ollama import OllamaClient
from campuspilot.llm.select import select_llm
from campuspilot.schemas.chat import (
    ChatRequest,
    KnowledgeSearchRequest,
    MoodleTokenRequest,
    MoodleTokenResponse,
    SourcePublic,
    StatusResponse,
)
from campuspilot.schemas.tools import SearchCampusDocsInput, SearchCampusDocsOutput

router = APIRouter()
log = logging.getLogger("campuspilot.request")


class ApiError(Exception):
    """An error with an HTTP status and a friendly message (rendered as JSON)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


def _retrieval() -> Any:
    return importlib.import_module("campuspilot.retrieval.tools")


def _moodle() -> Any:
    return importlib.import_module("campuspilot.moodle.tools")


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


@router.get("/v1/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    settings = get_settings()
    (online, loaded, model, mode), (moodle, moodle_mode), sources = await asyncio.gather(
        _model_status(settings), _moodle_status(), _count_sources()
    )
    return StatusResponse(
        model_online=online,
        model_loaded=loaded,
        model=model,
        moodle=moodle,  # type: ignore[arg-type]
        moodle_mode=moodle_mode,
        sources_indexed=sources,
        mode=mode,  # type: ignore[arg-type]
    )


# ---------- chat ----------


def rate_limit(request: Request) -> None:
    """Dependency: runs before the body is validated."""
    limiter: RateLimiter = request.app.state.rate_limiter
    client = request.client.host if request.client else "unknown"
    if not limiter.allow(client):
        raise ApiError(429, "RATE_LIMITED", "Too many requests. Please wait a minute and retry.")


def _log_line(trace: RunTrace) -> None:
    log.info(
        "request_id=%s model=%s mode=%s tools=%s chunks=%s latency_ms=%d error_code=%s",
        trace.request_id,
        trace.model,
        trace.mode,
        trace.tools,
        trace.chunk_ids,
        trace.latency_ms,
        trace.error_code or "-",
    )


async def _event_stream(body: ChatRequest) -> AsyncIterator[str]:
    settings = get_settings()
    trace = RunTrace(request_id=uuid.uuid4().hex[:8])
    started = time.monotonic()
    try:
        llm = await select_llm(settings)
        async for name, data in run_chat(body, llm, trace, settings):
            yield format_sse(name, data)
    finally:  # also runs when the browser disconnects
        trace.latency_ms = int((time.monotonic() - started) * 1000)
        _log_line(trace)


@router.post("/v1/chat", dependencies=[Depends(rate_limit)])
async def chat(body: ChatRequest) -> StreamingResponse:
    headers = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    return StreamingResponse(_event_stream(body), media_type="text/event-stream", headers=headers)


# ---------- knowledge, sources ----------


@router.post("/v1/knowledge/search", response_model=SearchCampusDocsOutput)
async def knowledge_search(body: KnowledgeSearchRequest) -> Any:
    args = SearchCampusDocsInput(**body.model_dump())
    return await asyncio.to_thread(_retrieval().search_campus_docs, args)


@router.get("/v1/sources", response_model=list[SourcePublic])
async def sources() -> Any:
    return await asyncio.to_thread(_retrieval().list_sources)


# ---------- Moodle credentials (never echoed) ----------


@router.post("/v1/moodle/token", response_model=MoodleTokenResponse)
async def save_moodle_token(body: MoodleTokenRequest) -> Any:
    if bool(body.token) == bool(body.ical_url):
        raise ApiError(400, "BAD_REQUEST", "Send either a Moodle token or an iCal URL, not both.")
    module = _moodle()
    try:
        return await module.save_credentials(body)
    except module.MoodleError as exc:
        raise ApiError(400, "BAD_REQUEST", exc.message) from None  # drop context: may hold secrets


@router.delete("/v1/moodle/token", response_model=MoodleTokenResponse)
async def delete_moodle_token() -> Any:
    return await asyncio.to_thread(_moodle().delete_credentials)
