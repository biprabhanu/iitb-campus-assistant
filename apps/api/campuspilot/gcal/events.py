"""Creates one calendar event, only from the UI click (POST /v1/calendar/events)."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.gcal.auth import access_token
from campuspilot.gcal.http import json_body, send
from campuspilot.schemas.connectors import CalendarEventRequest, CalendarEventResult, event_key

API = "https://www.googleapis.com/calendar/v3/calendars"
KEY = "campuspilotKey"


def build_body(req: CalendarEventRequest) -> dict:
    s = get_settings()
    tz = ZoneInfo(s.gcal_timezone)
    start = req.start.astimezone(tz)
    if req.all_day:
        first = start.date()
        # Google's all-day end is exclusive. A given `end` is read as the last day, inclusive.
        last = max(req.end.astimezone(tz).date(), first) if req.end else first
        start_part: dict = {"date": first.isoformat()}
        end_part: dict = {"date": (last + timedelta(days=1)).isoformat()}
    else:
        end = req.end.astimezone(tz) if req.end else start
        if end <= start:  # missing or nonsensical end: default to one hour
            end = start + timedelta(hours=1)
        start_part = {"dateTime": start.isoformat(), "timeZone": s.gcal_timezone}
        end_part = {"dateTime": end.isoformat(), "timeZone": s.gcal_timezone}
    body: dict = {
        "summary": req.title,
        "start": start_part,
        "end": end_part,
        "description": f"From your mail: {req.mail_subject}\n\nAdded by CampusPilot",
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": s.gcal_reminder_minutes}],
        },
        "extendedProperties": {"private": {KEY: req.event_id}},
    }
    if req.venue:
        body["location"] = req.venue
    return body


async def _call(method: str, url: str, **kwargs) -> httpx.Response:
    """Authorised request. A 401 refreshes the token once; a second 401 means auth_failed."""
    resp = await send(
        method, url, headers={"Authorization": f"Bearer {await access_token()}"}, **kwargs
    )
    if resp.status_code == 401:
        token = await access_token(force_refresh=True)
        resp = await send(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
    if resp.status_code == 401:
        raise ConnectorError("auth_failed", "Google rejected the saved access. Connect it again.")
    if resp.status_code in (403, 429):
        raise ConnectorError(
            "google_error",
            "Google Calendar refused the request (permission or rate limit). Try again later.",
        )
    if resp.status_code >= 400:
        raise ConnectorError("google_error", "Google Calendar could not save the event.")
    return resp


async def create_event(req: CalendarEventRequest) -> CalendarEventResult:
    # Integrity: the id must be the hash of this mail + start, or the dedupe key is meaningless.
    # No dedicated "bad request" code exists; google_error maps to a 502 the UI shows.
    if req.event_id != event_key(req.message_id, req.start):
        raise ConnectorError("google_error", "This event does not match its source. Not added.")
    cal = quote(get_settings().gcal_calendar_id, safe="")
    url = f"{API}/{cal}/events"

    # Idempotent: look for an event this same click already created.
    found = json_body(
        await _call(
            "GET",
            url,
            params={"privateExtendedProperty": f"{KEY}={req.event_id}", "maxResults": 1},
        )
    )
    items = found.get("items") or []
    if items:
        return CalendarEventResult(
            ok=True,
            status="already_exists",
            google_event_id=items[0].get("id"),
            html_link=items[0].get("htmlLink"),
            message="Already in your calendar.",
        )

    created = json_body(await _call("POST", url, json=build_body(req)))
    return CalendarEventResult(
        ok=True,
        status="created",
        google_event_id=created.get("id"),
        html_link=created.get("htmlLink"),
        message="Added to your calendar.",
    )
