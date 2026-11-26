"""OAuth for an installed app (loopback redirect + PKCE), token refresh and disconnect.

Only the refresh token is persisted (macOS Keychain). Access tokens live in memory.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

from campuspilot.config import get_settings
from campuspilot.connectors import keychain
from campuspilot.connectors.errors import ConnectorError
from campuspilot.gcal.client_file import load_client
from campuspilot.gcal.http import json_body, send
from campuspilot.schemas.connectors import ConnectorStatus, GcalConnectStart

SCOPE = "https://www.googleapis.com/auth/calendar.events"  # the only scope we ask for
REVOKE_URI = "https://oauth2.googleapis.com/revoke"
STATE_TTL = 600.0  # seconds a pending sign-in stays valid
_MAX_PENDING = 20

REVOKED_MESSAGE = "Google Calendar access was revoked. Connect it again in Settings."

# state -> (code_verifier, expires_at). In memory only; each entry is single use.
_pending: dict[str, tuple[str, float]] = {}
# (access_token, expires_at)
_access: tuple[str, float] | None = None


def _now() -> float:
    return time.monotonic()  # a separate function so tests can move the clock


def redirect_uri() -> str:
    return f"http://127.0.0.1:{get_settings().api_port}/v1/connectors/gcal/callback"


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def reset_memory() -> None:
    """Forget pending sign-ins and the cached access token (used by tests and disconnect)."""
    global _access
    _pending.clear()
    _access = None


def start_connect() -> GcalConnectStart:
    client = load_client()  # fails early with setup instructions
    now = _now()
    for old in [s for s, (_, exp) in _pending.items() if exp <= now]:
        del _pending[old]
    while len(_pending) >= _MAX_PENDING:  # bound memory; drop the oldest
        del _pending[next(iter(_pending))]
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    _pending[state] = (verifier, now + STATE_TTL)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client.client_id,
            "redirect_uri": redirect_uri(),
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",  # makes Google always return a refresh token
            "state": state,
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return GcalConnectStart(auth_url=f"{client.auth_uri}?{query}")


def _remember_access(body: dict) -> str:
    global _access
    token = str(body.get("access_token") or "")
    if not token:
        raise ConnectorError("google_error", "Google sent an unexpected reply. Try again.")
    lifetime = float(body.get("expires_in") or 3600)
    _access = (token, _now() + max(lifetime - 60, 0))  # refresh a minute early
    return token


def connected_status() -> ConnectorStatus:
    # There is no email scope, so the "account" shown in Settings is the calendar in use.
    return ConnectorStatus(
        name="gcal", enabled=True, state="connected", account=get_settings().gcal_calendar_id
    )


async def finish_connect(code: str, state: str) -> ConnectorStatus:
    entry = _pending.pop(state, None)  # pop: a state can be used only once
    if entry is None or entry[1] <= _now():
        raise ConnectorError(
            "auth_failed", "This sign-in link is no longer valid. Press Connect again."
        )
    client = load_client()
    resp = await send(
        "POST",
        client.token_uri,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "redirect_uri": redirect_uri(),
            "code_verifier": entry[0],
        },
    )
    body = json_body(resp)
    if resp.status_code != 200:
        raise ConnectorError("auth_failed", "Google did not accept the sign-in. Try again.")
    refresh = str(body.get("refresh_token") or "")
    if not refresh:
        raise ConnectorError(
            "auth_failed",
            "Google did not grant offline access. Press Connect again and approve all prompts.",
        )
    keychain.set_secret("gcal_refresh_token", refresh)
    keychain.set_secret("gcal_account", get_settings().gcal_calendar_id)
    _remember_access(body)
    return connected_status()


async def access_token(*, force_refresh: bool = False) -> str:
    """A valid access token, from the cache or via the stored refresh token."""
    global _access
    if not force_refresh and _access and _access[1] > _now():
        return _access[0]
    _access = None
    refresh = keychain.get_secret("gcal_refresh_token")
    if not refresh:
        raise ConnectorError("not_connected", "Google Calendar is not connected.")
    client = load_client()
    resp = await send(
        "POST",
        client.token_uri,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
        },
    )
    body = json_body(resp)
    if resp.status_code == 200:
        return _remember_access(body)
    if body.get("error") == "invalid_grant":  # the student revoked access (or it expired)
        keychain.delete_secret("gcal_refresh_token", "gcal_account")
        raise ConnectorError("auth_failed", REVOKED_MESSAGE)
    raise ConnectorError("google_error", "Google would not renew the connection. Try again later.")


async def disconnect() -> ConnectorStatus:
    refresh = keychain.get_secret("gcal_refresh_token")
    revoke_failed = False
    if refresh:
        try:
            resp = await send("POST", REVOKE_URI, data={"token": refresh})
            revoke_failed = resp.status_code != 200
        except ConnectorError:
            revoke_failed = True
    # Delete locally even when Google could not be reached.
    keychain.delete_secret("gcal_refresh_token", "gcal_account")
    reset_memory()
    message = None
    if revoke_failed:
        message = (
            "Disconnected here, but Google could not be told. "
            "You can remove access at myaccount.google.com/permissions."
        )
    return ConnectorStatus(name="gcal", enabled=True, state="not_connected", message=message)
