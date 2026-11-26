"""IITB Webmail connector (read-only IMAP). CONTRACT §11.

PHASE 0 STUB: these are the exact signatures the registry and API call. Worker A replaces the
bodies (and may add modules in this package), keeping the signatures.
"""

from __future__ import annotations

from campuspilot.connectors.errors import ConnectorError
from campuspilot.schemas.connectors import (
    ConnectorLoginRequest,
    ConnectorStatus,
    SearchMyMailInput,
    SearchMyMailOutput,
    UpcomingEventsInput,
    UpcomingEventsOutput,
)

__all__ = [
    "ConnectorError",
    "get_upcoming_institute_events",
    "mail_login",
    "mail_logout",
    "mail_status",
    "search_my_mail",
]

_TODO = "Webmail is not built yet."


async def search_my_mail(args: SearchMyMailInput) -> SearchMyMailOutput:
    raise ConnectorError("not_implemented", _TODO)


async def get_upcoming_institute_events(args: UpcomingEventsInput) -> UpcomingEventsOutput:
    raise ConnectorError("not_implemented", _TODO)


async def mail_status() -> ConnectorStatus:
    return ConnectorStatus(name="webmail", enabled=True, state="error", message=_TODO)


async def mail_login(req: ConnectorLoginRequest) -> ConnectorStatus:
    raise ConnectorError("not_implemented", _TODO)


def mail_logout() -> ConnectorStatus:
    raise ConnectorError("not_implemented", _TODO)
