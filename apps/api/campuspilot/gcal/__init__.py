"""Google Calendar connector (the app's only write). CONTRACT §11.

`create_event` runs only from POST /v1/calendar/events, i.e. a student's click. It is never a
tool the model can call.

Plain httpx against Google's REST endpoints (no Google SDK). Modules: `client_file` (the Desktop
OAuth client JSON), `auth` (OAuth + PKCE, tokens, disconnect), `events` (the idempotent insert).
"""

from __future__ import annotations

from campuspilot.config import get_settings
from campuspilot.connectors import keychain
from campuspilot.connectors.errors import ConnectorError
from campuspilot.gcal import auth, events
from campuspilot.gcal.client_file import SETUP_HELP, client_file_exists
from campuspilot.schemas.connectors import (
    CalendarEventRequest,
    CalendarEventResult,
    ConnectorStatus,
    GcalConnectStart,
)

__all__ = [
    "ConnectorError",
    "create_event",
    "gcal_disconnect",
    "gcal_finish_connect",
    "gcal_start_connect",
    "gcal_status",
    "is_connected",
]


def is_connected() -> bool:
    """Cheap check (Keychain and client file only, no network) for EventCard.can_add_to_calendar."""
    return keychain.get_secret("gcal_refresh_token") is not None and client_file_exists()


async def gcal_status() -> ConnectorStatus:
    has_token = keychain.get_secret("gcal_refresh_token") is not None
    if not has_token:
        message = None
        if not client_file_exists():
            message = SETUP_HELP.format(path=get_settings().gcal_client_file)
        return ConnectorStatus(name="gcal", enabled=True, state="not_connected", message=message)
    if not client_file_exists():
        return ConnectorStatus(
            name="gcal",
            enabled=True,
            state="error",
            message=SETUP_HELP.format(path=get_settings().gcal_client_file),
        )
    return auth.connected_status()


async def gcal_start_connect() -> GcalConnectStart:
    return auth.start_connect()


async def gcal_finish_connect(code: str, state: str) -> ConnectorStatus:
    return await auth.finish_connect(code, state)


async def gcal_disconnect() -> ConnectorStatus:
    return await auth.disconnect()


async def create_event(req: CalendarEventRequest) -> CalendarEventResult:
    return await events.create_event(req)
