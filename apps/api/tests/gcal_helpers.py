"""Shared fakes for the Google Calendar tests. Every value here is obviously fake."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from campuspilot.connectors import keychain
from campuspilot.schemas.connectors import CalendarEventRequest, event_key

CLIENT_ID = "fake-client-id.apps.googleusercontent.com"
CLIENT_SECRET = "FAKE_SECRET"
REFRESH = "FAKE_REFRESH_TOKEN"
ACCESS = "FAKE_ACCESS_TOKEN"
TOKEN_URI = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SECRETS = (CLIENT_SECRET, REFRESH, ACCESS)


def write_client_file(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": TOKEN_URI,
                }
            }
        )
    )


def store_refresh() -> None:
    keychain.set_secret("gcal_refresh_token", REFRESH)


def make_request(**over) -> CalendarEventRequest:
    start = over.pop("start", datetime.fromisoformat("2026-12-05T17:00:00+05:30"))
    message_id = over.pop("message_id", "<talk-1@iitb.ac.in>")
    data = {
        "event_id": event_key(message_id, start),
        "message_id": message_id,
        "title": "Guest talk on RL",
        "start": start,
        "end": datetime.fromisoformat("2026-12-05T18:30:00+05:30"),
        "venue": "LA 201",
        "mail_subject": "Talk on RL this Friday",
    }
    data.update(over)
    return CalendarEventRequest(**data)
