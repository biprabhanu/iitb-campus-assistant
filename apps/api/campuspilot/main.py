"""CampusPilot API entry point: `uvicorn campuspilot.main:app --host 127.0.0.1`."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from campuspilot.api.middleware import LimitsAndLogMiddleware
from campuspilot.api.routes import ApiError, router
from campuspilot.api.sse import RateLimiter
from campuspilot.config import get_settings

log = logging.getLogger("campuspilot")


def _json_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return _json_error(exc.status, exc.code, exc.message)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Name the fields only; never echo what the user typed.
    fields = sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")})
    detail = f" Check: {', '.join(fields)}." if fields else ""
    return _json_error(422, "BAD_REQUEST", f"That request wasn't valid.{detail}")


async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled error: %s", type(exc).__name__)  # type only, no stack or values
    return _json_error(500, "INTERNAL", "Something went wrong on our side. Please try again.")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="CampusPilot API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_min)

    app.add_exception_handler(ApiError, _api_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unexpected_error)

    app.add_middleware(LimitsAndLogMiddleware)
    # Added last = outermost, so CORS headers also appear on 413/429 responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
