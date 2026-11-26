"""Keychain storage for the Moodle token / iCal URL (via the `keyring` package).

Values are only ever read back for use; they are never returned to callers of the API,
logged, or put in exception messages.
"""

from __future__ import annotations

import contextlib
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from urllib.parse import urlparse

import keyring
from keyring.errors import KeyringError

from campuspilot.config import get_settings
from campuspilot.moodle.errors import MoodleError

SERVICE = "campuspilot"
TOKEN_USER = "moodle_token"  # noqa: S105 (a keyring entry name, not a secret)
ICAL_USER = "moodle_ical_url"


def _get(username: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, username) or None
    except KeyringError:
        return None  # no usable keychain: behave as if nothing is stored


def get_keyring_token() -> str | None:
    return _get(TOKEN_USER)


def get_keyring_ical_url() -> str | None:
    return _get(ICAL_USER)


def store_token(token: str) -> None:
    keyring.set_password(SERVICE, TOKEN_USER, token)


def store_ical_url(url: str) -> None:
    keyring.set_password(SERVICE, ICAL_USER, url)


def delete_all() -> None:
    """Remove both entries; a missing entry is fine."""
    for username in (TOKEN_USER, ICAL_USER):
        with contextlib.suppress(KeyringError):
            keyring.delete_password(SERVICE, username)


# ---------- per-request credentials (hosted mode) ----------

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")
_MAX_ICAL_LEN = 1000


@dataclass(frozen=True)
class RequestCredentials:
    """Moodle credentials for exactly one request. Never printed."""

    token: str | None = None
    ical_url: str | None = None

    def __repr__(self) -> str:
        return "RequestCredentials(<hidden>)"

    __str__ = __repr__


def validate_ical_url(url: str) -> None:
    """https, exact Moodle host, no userinfo, default port, bounded length. Value never echoed."""
    expected_host = urlparse(get_settings().moodle_base_url).hostname
    bad = MoodleError("unavailable", f"The calendar URL must be an https link on {expected_host}.")
    if not isinstance(url, str) or len(url) > _MAX_ICAL_LEN:
        raise bad
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise bad from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or "@" in parsed.netloc
    ):
        raise bad


def parse_request_credentials(
    token_header: str | None, ical_header: str | None
) -> RequestCredentials | None:
    token = (token_header or "").strip()
    ical = (ical_header or "").strip()
    if not token and not ical:
        return None
    if token and ical:
        raise MoodleError("unavailable", "Send either a Moodle token or a calendar URL, not both.")
    if token:
        if not _TOKEN_RE.fullmatch(token):
            raise MoodleError("invalid_token", "The Moodle token has an invalid format.")
        return RequestCredentials(token=token)
    validate_ical_url(ical)
    return RequestCredentials(ical_url=ical)


_REQUEST_CREDS: ContextVar[RequestCredentials | None] = ContextVar(
    "moodle_request_credentials", default=None
)


def set_request_credentials(creds: RequestCredentials | None) -> Token[RequestCredentials | None]:
    return _REQUEST_CREDS.set(creds)


def reset_request_credentials(token: Token[RequestCredentials | None]) -> None:
    _REQUEST_CREDS.reset(token)


def get_request_credentials() -> RequestCredentials | None:
    return _REQUEST_CREDS.get()
