"""v2 connector endpoints: Settings (connect / disconnect) and the calendar "Add" click.

CONTRACT §11.5. This router is **only mounted in local mode** (see main.py), so in hosted mode
none of these paths exist at all. Each endpoint also checks its own *_ENABLED flag.

Two protections for a local API that holds the student's passwords and can write to their
calendar:
- Every POST / DELETE needs the header `X-CampusPilot-Confirm: yes`. A custom header forces a
  CORS preflight, and CORS only allows the local UI, so another website open in the same
  browser cannot log in, disconnect or create events behind the student's back.
- Passwords, OTPs and tokens are passed straight to the connector module and never logged,
  echoed or put in an error message (errors use the module's fixed, friendly text).

The Google OAuth callback is a plain GET (Google's redirect cannot add headers); it is
protected by the OAuth `state` value and PKCE, which the gcal module checks.
"""

from __future__ import annotations

import importlib
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from campuspilot.api.errors import ApiError
from campuspilot.api.ratelimit import client_ip
from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.schemas.connectors import (
    CalendarEventRequest,
    CalendarEventResult,
    ConnectorLoginRequest,
    ConnectorOtpRequest,
    ConnectorsResponse,
    ConnectorStatus,
    GcalConnectStart,
)

CONFIRM_HEADER = "X-CampusPilot-Confirm"

router = APIRouter()

_FLAG = {"webmail": "WEBMAIL_ENABLED", "asc": "ASC_ENABLED", "gcal": "GCAL_ENABLED"}
_MODULE = {"webmail": "mail", "asc": "asc", "gcal": "gcal"}

# ConnectorError code -> (HTTP status, API error code)
_HTTP = {
    "disabled": (404, "NOT_AVAILABLE"),
    "not_connected": (409, "NOT_CONNECTED"),
    "auth_failed": (401, "AUTH_FAILED"),
    "otp_required": (401, "OTP_REQUIRED"),
    "otp_invalid": (401, "AUTH_FAILED"),
    "session_expired": (401, "SESSION_EXPIRED"),
    "unreachable": (503, "UNREACHABLE"),
    "timeout": (503, "UNREACHABLE"),
    "parse_failed": (502, "INTERNAL"),
    "blocked": (502, "NOT_AVAILABLE"),
    "google_error": (502, "CALENDAR_ERROR"),
    "not_implemented": (501, "NOT_AVAILABLE"),
}


def _module(name: str) -> Any:
    return importlib.import_module(f"campuspilot.{_MODULE[name]}")


def _is_on(name: str) -> bool:
    settings = get_settings()
    return {"webmail": settings.webmail_on, "asc": settings.asc_on, "gcal": settings.gcal_on}[name]


def _require_on(name: str) -> None:
    if not _is_on(name):
        raise ApiError(404, "NOT_AVAILABLE", f"Turn this on with {_FLAG[name]}=true in .env.")


def _api_error(exc: ConnectorError) -> ApiError:
    status, code = _HTTP.get(exc.code, (502, "INTERNAL"))
    return ApiError(status, code, exc.message)


def require_confirm(request: Request) -> None:
    """Dependency for every state-changing endpoint (see the module docstring)."""
    if request.headers.get(CONFIRM_HEADER, "").strip().lower() != "yes":
        raise ApiError(403, "BAD_REQUEST", "This action must come from the CampusPilot app.")


def rate_limit(request: Request) -> None:
    limiter = request.app.state.rate_limiter
    wait = limiter.check(client_ip(request, get_settings().hosted))
    if wait is not None:
        raise ApiError(429, "RATE_LIMITED", "Too many requests. Please wait a bit and retry.", wait)


_GUARDS = [Depends(require_confirm), Depends(rate_limit)]


# ---------- status ----------


async def _status(name: str) -> ConnectorStatus:
    if not _is_on(name):
        return ConnectorStatus(
            name=name,  # type: ignore[arg-type]
            enabled=False,
            state="disabled",
            message=f"Off. Set {_FLAG[name]}=true in .env and restart the API.",
        )
    func = {"webmail": "mail_status", "asc": "asc_status", "gcal": "gcal_status"}[name]
    try:
        return await getattr(_module(name), func)()
    except ConnectorError as exc:
        return ConnectorStatus(name=name, enabled=True, state="error", message=exc.message)  # type: ignore[arg-type]
    except Exception:
        return ConnectorStatus(
            name=name,  # type: ignore[arg-type]
            enabled=True,
            state="error",
            message="Could not check this connection.",
        )


@router.get("/v1/connectors", response_model=ConnectorsResponse)
async def connectors() -> ConnectorsResponse:
    return ConnectorsResponse(
        webmail=await _status("webmail"), asc=await _status("asc"), gcal=await _status("gcal")
    )


# ---------- Webmail ----------


@router.post("/v1/connectors/webmail/login", response_model=ConnectorStatus, dependencies=_GUARDS)
async def webmail_login(body: ConnectorLoginRequest) -> Any:
    _require_on("webmail")
    try:
        return await _module("webmail").mail_login(body)
    except ConnectorError as exc:
        raise _api_error(exc) from None  # drop the context: it may hold the password


@router.delete("/v1/connectors/webmail", response_model=ConnectorStatus, dependencies=_GUARDS)
async def webmail_logout() -> Any:
    _require_on("webmail")
    try:
        return _module("webmail").mail_logout()
    except ConnectorError as exc:
        raise _api_error(exc) from None


# ---------- ASC ----------


@router.post("/v1/connectors/asc/login", response_model=ConnectorStatus, dependencies=_GUARDS)
async def asc_login(body: ConnectorLoginRequest) -> Any:
    """May answer state="needs_otp" with a challenge_id; the UI then asks for the code."""
    _require_on("asc")
    try:
        return await _module("asc").asc_login(body)
    except ConnectorError as exc:
        raise _api_error(exc) from None


@router.post("/v1/connectors/asc/otp", response_model=ConnectorStatus, dependencies=_GUARDS)
async def asc_otp(body: ConnectorOtpRequest) -> Any:
    _require_on("asc")
    try:
        return await _module("asc").asc_submit_otp(body)
    except ConnectorError as exc:
        raise _api_error(exc) from None


@router.delete("/v1/connectors/asc", response_model=ConnectorStatus, dependencies=_GUARDS)
async def asc_logout() -> Any:
    _require_on("asc")
    try:
        return _module("asc").asc_logout()
    except ConnectorError as exc:
        raise _api_error(exc) from None


@router.post("/v1/connectors/asc/refresh", response_model=ConnectorStatus, dependencies=_GUARDS)
async def asc_refresh() -> Any:
    """Re-read every personal ASC page into the in-memory snapshot now (Settings button)."""
    _require_on("asc")
    try:
        return await _module("asc").asc_refresh()
    except ConnectorError as exc:
        raise _api_error(exc) from None


# ---------- Google Calendar ----------


@router.post("/v1/connectors/gcal/connect", response_model=GcalConnectStart, dependencies=_GUARDS)
async def gcal_connect() -> Any:
    _require_on("gcal")
    try:
        return await _module("gcal").gcal_start_connect()
    except ConnectorError as exc:
        raise _api_error(exc) from None


def _page(title: str, text: str) -> HTMLResponse:
    body = (
        "<!doctype html><meta charset='utf-8'><title>CampusPilot</title>"
        "<body style='font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
        f"<h1 style='font-size:1.3rem'>{escape(title)}</h1><p>{escape(text)}</p></body>"
    )
    return HTMLResponse(body)


@router.get("/v1/connectors/gcal/callback", response_class=HTMLResponse)
async def gcal_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    """Google's loopback redirect after the student approves (or cancels) access."""
    _require_on("gcal")
    if error or not code or not state:
        return _page(
            "Google Calendar not connected", "Access was not granted. You can close this tab."
        )
    try:
        await _module("gcal").gcal_finish_connect(code, state)
    except ConnectorError as exc:
        return _page("Google Calendar not connected", exc.message)
    return _page("Google Calendar connected", "You can close this tab and go back to CampusPilot.")


@router.delete("/v1/connectors/gcal", response_model=ConnectorStatus, dependencies=_GUARDS)
async def gcal_disconnect() -> Any:
    """Revokes the token at Google, then deletes it from the Keychain."""
    _require_on("gcal")
    try:
        return await _module("gcal").gcal_disconnect()
    except ConnectorError as exc:
        raise _api_error(exc) from None


@router.post("/v1/calendar/events", response_model=CalendarEventResult, dependencies=_GUARDS)
async def calendar_add(body: CalendarEventRequest) -> Any:
    """The only write in the app: one event, from one click on an event card. Never a tool."""
    _require_on("gcal")
    try:
        return await _module("gcal").create_event(body)
    except ConnectorError as exc:
        raise _api_error(exc) from None
