"""Reads Google's "Desktop app" OAuth client file (kept outside the repo, never logged)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError

DEFAULT_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 (a URL, not a secret)

SETUP_HELP = (
    "Google Calendar needs a one-time setup: in Google Cloud Console create an OAuth client of "
    "type 'Desktop app', download its JSON and save it as {path}. Then press Connect again."
)


@dataclass(frozen=True)
class ClientConfig:
    client_id: str
    client_secret: str = field(repr=False)  # repr=False: a stray print/log never shows it
    auth_uri: str
    token_uri: str


def client_file_exists() -> bool:
    return get_settings().gcal_client_file.is_file()


def load_client() -> ClientConfig:
    path = get_settings().gcal_client_file
    problem = SETUP_HELP.format(path=path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        installed = raw["installed"]  # the "Desktop app" format
        client_id = str(installed["client_id"]).strip()
        client_secret = str(installed["client_secret"]).strip()
        auth_uri = str(installed.get("auth_uri") or DEFAULT_AUTH_URI)
        token_uri = str(installed.get("token_uri") or DEFAULT_TOKEN_URI)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Deliberately no detail: the file holds a secret.
        raise ConnectorError("not_connected", problem) from None
    if not client_id or not client_secret:
        raise ConnectorError("not_connected", problem)
    # The client secret is POSTed to token_uri, so refuse anything but https.
    if not auth_uri.startswith("https://") or not token_uri.startswith("https://"):
        raise ConnectorError("not_connected", problem)
    return ClientConfig(client_id, client_secret, auth_uri, token_uri)
