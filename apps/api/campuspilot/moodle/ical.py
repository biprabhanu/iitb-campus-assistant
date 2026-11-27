"""iCal (calendar export) fallback: fetch the URL and turn events into Deadlines."""

from __future__ import annotations

import re
import time
from datetime import UTC, date, datetime
from urllib.parse import urljoin, urlparse

import httpx
from icalendar import Calendar

from campuspilot.config import get_settings
from campuspilot.moodle import credentials
from campuspilot.moodle.client import fingerprint
from campuspilot.moodle.errors import MoodleError
from campuspilot.schemas.tools import Deadline

# Looks like an IITB course code in a summary, e.g. "IE624" or "HS 101".
_CODE_RE = re.compile(r"\b([A-Z]{2,4}\s?\d{3}[A-Z]?)\b")

# (expires_at, ics text) keyed by URL fingerprint. Memory only.
_CACHE: dict[str, tuple[float, str]] = {}


def clear_cache() -> None:
    _CACHE.clear()


def validate_ical_url(url: str) -> None:
    """Only https URLs on the configured Moodle host are allowed."""
    credentials.validate_ical_url(url)


def masked(url: str) -> str:
    """The only part of a calendar link we ever show: its host. The path and the `authtoken`
    query never appear in a message, log line or exception."""
    try:
        host = urlparse(url).hostname
    except ValueError:
        host = None
    return host or "Moodle"


_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 3


async def fetch_ics(url: str) -> str:
    validate_ical_url(url)
    host = masked(url)
    settings = get_settings()
    use_cache = not settings.hosted
    key = fingerprint(url)
    if use_cache:
        hit = _CACHE.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    try:
        async with httpx.AsyncClient(
            timeout=settings.moodle_timeout_s, follow_redirects=False
        ) as http:
            response = await http.get(url)
            hops = 0
            while response.status_code in _REDIRECT_CODES:
                location = response.headers.get("location")
                hops += 1
                if not location or hops > _MAX_REDIRECTS:
                    raise MoodleError(
                        "unavailable", f"The Moodle calendar link ({host}) redirected too much."
                    )
                target = urljoin(str(response.url), location)
                validate_ical_url(target)  # every hop must stay on the Moodle host
                response = await http.get(target)
    except httpx.TimeoutException:
        raise MoodleError(
            "timeout", f"{host} took too long to answer. Try again in a moment."
        ) from None
    except httpx.HTTPError:
        raise MoodleError(
            "unavailable", f"Could not reach the Moodle calendar export on {host}."
        ) from None
    if response.status_code >= 400 or response.status_code in _REDIRECT_CODES:
        raise MoodleError(
            "unavailable",
            f"The Moodle calendar link on {host} did not work. It may have been reset: export "
            "a new one in Moodle (Calendar → Export calendar) and paste it in Settings.",
        )
    if use_cache:
        _CACHE[key] = (time.monotonic() + settings.moodle_cache_ttl_s, response.text)
    return response.text


def _as_utc(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _course_of(component, summary: str) -> str:
    categories = component.get("categories")
    if categories is not None:
        cats = categories if isinstance(categories, list) else [categories]
        for cat in cats:
            for name in getattr(cat, "cats", []):
                if str(name).strip():
                    return str(name).strip()
    match = _CODE_RE.search(summary)
    return match.group(1).replace(" ", "") if match else ""


def parse_ics(text: str) -> list[Deadline]:
    """Parse calendar text into Deadlines (all kind="event"), sorted by time."""
    try:
        calendar = Calendar.from_ical(text)
    except ValueError:
        raise MoodleError("unavailable", "The calendar export could not be read.") from None
    deadlines: list[Deadline] = []
    for index, event in enumerate(calendar.walk("VEVENT")):
        start = event.get("dtstart")
        if start is None:
            continue
        summary = str(event.get("summary", "Calendar event"))
        uid = str(event.get("uid", index))
        url = event.get("url")
        deadlines.append(
            Deadline(
                id=f"event-{uid}",
                title=summary,
                course=_course_of(event, summary),
                due_at=_as_utc(start.dt),
                activity_url=str(url) if url else None,
                kind="event",
            )
        )
    return sorted(deadlines, key=lambda d: d.due_at)
