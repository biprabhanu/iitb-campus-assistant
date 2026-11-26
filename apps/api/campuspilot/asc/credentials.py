"""ASC login details in the macOS Keychain (via connectors.keychain). Never logged or returned."""

from __future__ import annotations

from campuspilot.connectors import keychain


def load() -> tuple[str, str] | None:
    username = keychain.get_secret("asc_username")
    password = keychain.get_secret("asc_password")
    if username and password:
        return username, password
    return None


def save(username: str, password: str) -> None:
    keychain.set_secret("asc_username", username)
    keychain.set_secret("asc_password", password)


def clear() -> None:
    keychain.delete_secret("asc_username", "asc_password")


def username() -> str | None:
    return keychain.get_secret("asc_username")
