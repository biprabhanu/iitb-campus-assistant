"""iCal (calendar export) fallback: fetch the URL and turn events into Deadlines."""

from __future__ import annotations

import re
import time
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import httpx
from icalendar import Calendar

from campuspilot.config import get_settings
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
    parsed = urlparse(url)
    expected_host = urlparse(get_settings().moodle_base_url).hostname
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname != expected_host:
        raise MoodleError(
            "unavailable", f"The calendar URL must be an https link on {expected_host}."
        )


async def fetch_ics(url: str) -> str:
    validate_ical_url(url)
    key = fingerprint(url)
    hit = _CACHE.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=settings.moodle_timeout_s, follow_redirects=False
        ) as http:
            response = await http.get(url)
    except httpx.TimeoutException:
        raise MoodleError(
            "timeout", "Moodle took too long to answer. Try again in a moment."
        ) from None
    except httpx.HTTPError:
        raise MoodleError("unavailable", "Could not reach the Moodle calendar export.") from None
    if response.status_code >= 400:
        raise MoodleError(
            "unavailable", "The Moodle calendar export link did not work (it may have changed)."
        )
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
