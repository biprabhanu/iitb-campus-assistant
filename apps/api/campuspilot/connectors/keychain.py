"""macOS Keychain storage for connector secrets (via the `keyring` package).

One service name for the whole app (`campuspilot`, as Moodle uses) and one entry per secret:
`webmail_username`, `webmail_password`, `asc_username`, `asc_password`, `gcal_refresh_token`,
`gcal_account`. Values are only read back for use: never returned by the API, logged or put in
an error message.
"""

from __future__ import annotations

import contextlib

import keyring
from keyring.errors import KeyringError

SERVICE = "campuspilot"

ENTRIES = (
    "webmail_username",
    "webmail_password",
    "asc_username",
    "asc_password",
    "gcal_refresh_token",
    "gcal_account",
)


def get_secret(entry: str) -> str | None:
    assert entry in ENTRIES, entry
    try:
        return keyring.get_password(SERVICE, entry) or None
    except KeyringError:
        return None  # no usable keychain: behave as if nothing is stored


def set_secret(entry: str, value: str) -> None:
    assert entry in ENTRIES, entry
    keyring.set_password(SERVICE, entry, value)


def delete_secret(*entries: str) -> None:
    """Remove entries; a missing entry is fine."""
    for entry in entries:
        assert entry in ENTRIES, entry
        with contextlib.suppress(KeyringError):
            keyring.delete_password(SERVICE, entry)
