"""CampusPilot API entry point: `uvicorn campuspilot.main:app --host 127.0.0.1`."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from campuspilot.api import connectors as connector_routes
from campuspilot.api.errors import ApiError
from campuspilot.api.middleware import LimitsAndLogMiddleware
from campuspilot.api.ratelimit import RateLimiter
from campuspilot.api.routes import router
from campuspilot.config import Settings, get_settings

log = logging.getLogger("campuspilot")


def _setup_logging() -> None:
    """Print our own one-line-per-request logs (INFO) to stderr next to uvicorn's.

    Only the "campuspilot" logger is configured; what it logs never includes message text,
    tokens or Moodle content (see api/routes.py `_log_line`)."""
    if log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


_setup_logging()


def _json_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    payload: dict[str, object] = {"code": exc.code, "message": exc.message}
    headers = {}
    if exc.retry_after_s is not None:
        payload["retry_after_s"] = exc.retry_after_s
        headers["Retry-After"] = str(exc.retry_after_s)
    return JSONResponse(payload, status_code=exc.status, headers=headers)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Name the fields only; never echo what the user typed.
    fields = sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")})
    detail = f" Check: {', '.join(fields)}." if fields else ""
    return _json_error(422, "BAD_REQUEST", f"That request wasn't valid.{detail}")


async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled error: %s", type(exc).__name__)  # type only, no stack or values
    return _json_error(500, "INTERNAL", "Something went wrong on our side. Please try again.")


CORS_HEADERS = [
    "Content-Type",
    "X-LLM-Provider",
    "X-LLM-Key",
    "X-LLM-Model",
    "X-Moodle-Token",
    "X-Moodle-Ical-Url",
    connector_routes.CONFIRM_HEADER,  # v2 connectors (local only)
]


@dataclass
class IndexState:
    """Which index the API serves: kind is release / local / fallback / missing."""

    kind: str
    version: str | None = None


def local_index_info(settings: Settings) -> IndexState:
    return IndexState("local" if settings.campuspilot_db_path.exists() else "missing")


async def _prepare_index(settings: Settings) -> Any:
    """INDEX_SOURCE=release: download the newest index (slow, so off the event loop)."""
    if settings.index_source != "release":
        return local_index_info(settings)
    try:
        from campuspilot.index_release import prepare_index  # lazy: only needed when hosted

        return await asyncio.to_thread(prepare_index, settings)
    except Exception as exc:  # any failure: serve without an index rather than crash
        log.error("index download failed: %s", type(exc).__name__)
        return IndexState("missing")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.index_info = await _prepare_index(get_settings())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        lifespan=_lifespan, title="CampusPilot API", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_min, settings.rate_limit_per_day)
    app.state.index_info = local_index_info(settings)

    app.add_exception_handler(ApiError, _api_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unexpected_error)

    app.add_middleware(LimitsAndLogMiddleware, max_body=settings.max_body_bytes)
    # Added last = outermost, so CORS headers also appear on 413/429 responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=CORS_HEADERS,
    )
    app.include_router(router)
    # v2 connectors (Webmail, ASC, Google Calendar) exist only in local mode: in hosted mode
    # their routes are not even registered (CONTRACT §11.1; tests/test_connectors_contract.py).
    if not settings.hosted:
        app.include_router(connector_routes.router)
    return app


app = create_app()
