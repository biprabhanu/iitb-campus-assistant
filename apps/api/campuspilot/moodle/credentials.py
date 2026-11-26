"""Keychain storage for the Moodle token / iCal URL (via the `keyring` package).

Values are only ever read back for use; they are never returned to callers of the API,
logged, or put in exception messages.
"""

from __future__ import annotations

import contextlib

import keyring
from keyring.errors import KeyringError

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
