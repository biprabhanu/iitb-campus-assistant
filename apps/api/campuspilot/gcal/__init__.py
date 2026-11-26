"""Google Calendar connector (the app's only write). CONTRACT §11.

`create_event` runs only from POST /v1/calendar/events, i.e. a student's click. It is never a
tool the model can call.

PHASE 0 STUB: these are the exact signatures the API calls. Worker C replaces the bodies (and
may add modules in this package), keeping the signatures.
"""

from __future__ import annotations

from campuspilot.connectors.errors import ConnectorError
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

_TODO = "Google Calendar is not built yet."


def is_connected() -> bool:
    """Cheap check (Keychain only, no network) used to set EventCard.can_add_to_calendar."""
    return False


async def gcal_status() -> ConnectorStatus:
    return ConnectorStatus(name="gcal", enabled=True, state="error", message=_TODO)


async def gcal_start_connect() -> GcalConnectStart:
    raise ConnectorError("not_implemented", _TODO)


async def gcal_finish_connect(code: str, state: str) -> ConnectorStatus:
    raise ConnectorError("not_implemented", _TODO)


async def gcal_disconnect() -> ConnectorStatus:
    raise ConnectorError("not_implemented", _TODO)


async def create_event(req: CalendarEventRequest) -> CalendarEventResult:
    raise ConnectorError("not_implemented", _TODO)
