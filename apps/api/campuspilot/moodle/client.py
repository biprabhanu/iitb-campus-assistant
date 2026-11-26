"""Read-only Moodle REST client with a small in-memory cache.

Moodle quirk: errors come back as HTTP 200 with an "exception"/"errorcode" JSON body.
Nothing here is ever written to disk, and the raw token is never stored or logged.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from campuspilot.config import get_settings
from campuspilot.moodle.errors import MoodleError

# The ONLY functions this app may call. All of them only read data.
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "core_webservice_get_site_info",
        "core_enrol_get_users_courses",
        "mod_assign_get_assignments",
        "core_calendar_get_action_events_by_timesort",
        "core_course_get_contents",
    }
)

# (expires_at_monotonic, data), keyed by (token fingerprint, function, args).
_CACHE: dict[tuple[Any, ...], tuple[float, Any]] = {}


def clear_cache() -> None:
    _CACHE.clear()


def fingerprint(secret: str) -> str:
    """A short one-way hash, so cache keys never contain the real token."""
    return hashlib.sha256(secret.encode()).hexdigest()[:16]


def _friendly_error(errorcode: str) -> MoodleError:
    if errorcode == "invalidtoken":
        return MoodleError(
            "invalid_token",
            "Moodle rejected the token. It may be wrong or expired; save a fresh one.",
        )
    if errorcode == "accessexception":
        return MoodleError(
            "access_exception",
            "Moodle did not allow this request for your account (access denied).",
        )
    return MoodleError("unavailable", f"Moodle returned an error ({errorcode or 'unknown'}).")


def _check_for_moodle_error(data: Any) -> None:
    if isinstance(data, dict) and ("exception" in data or "errorcode" in data):
        raise _friendly_error(str(data.get("errorcode", "")))


class MoodleClient:
    """Calls Moodle web-service functions for one token."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._fp = fingerprint(token)

    async def call(self, wsfunction: str, args: dict[str, Any] | None = None) -> Any:
        if wsfunction not in ALLOWED_FUNCTIONS:
            raise MoodleError("unavailable", "That Moodle function is not allowed (read-only app).")
        args = args or {}
        key = (self._fp, wsfunction, tuple(sorted(args.items())))
        hit = _CACHE.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        data = await self._post(wsfunction, args)
        _CACHE[key] = (time.monotonic() + get_settings().moodle_cache_ttl_s, data)
        return data

    async def _post(self, wsfunction: str, args: dict[str, Any]) -> Any:
        settings = get_settings()
        url = settings.moodle_base_url.rstrip("/") + "/webservice/rest/server.php"
        form = {
            "wstoken": self._token,
            "wsfunction": wsfunction,
            "moodlewsrestformat": "json",
            **{k: str(v) for k, v in args.items()},
        }
        try:
            async with httpx.AsyncClient(timeout=settings.moodle_timeout_s) as http:
                response = await http.post(url, data=form)
        except httpx.TimeoutException:
            raise MoodleError(
                "timeout", "Moodle took too long to answer. Try again in a moment."
            ) from None
        except httpx.HTTPError:
            raise MoodleError("unavailable", "Could not reach Moodle right now.") from None
        if response.status_code >= 400:
            raise MoodleError("unavailable", f"Moodle returned HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError:
            raise MoodleError(
                "unavailable", "Moodle sent a reply that could not be read."
            ) from None
        _check_for_moodle_error(data)
        return data

    # --- thin wrappers, one per allowed function ---

    async def site_info(self) -> dict[str, Any]:
        return await self.call("core_webservice_get_site_info")

    async def courses(self, user_id: int) -> list[dict[str, Any]]:
        return await self.call("core_enrol_get_users_courses", {"userid": user_id})

    async def assignments(self) -> dict[str, Any]:
        return await self.call("mod_assign_get_assignments")

    async def action_events(self, time_from: int, time_to: int) -> dict[str, Any]:
        args = {"timesortfrom": time_from, "timesortto": time_to, "limitnum": 50}
        return await self.call("core_calendar_get_action_events_by_timesort", args)

    async def course_contents(self, course_id: int) -> list[dict[str, Any]]:
        return await self.call("core_course_get_contents", {"courseid": course_id})
