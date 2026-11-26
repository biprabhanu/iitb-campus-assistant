"""Webmail login stored in the macOS Keychain (entries `webmail_username` / `webmail_password`).

The password is only read back to open an IMAP session; it is never returned, logged or put
in an error message.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from campuspilot.connectors import keychain
from campuspilot.connectors.errors import ConnectorError

USERNAME_ENTRY = "webmail_username"
PASSWORD_ENTRY = "webmail_password"  # noqa: S105 (a keyring entry name, not a secret)


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str = field(repr=False)  # repr=False: never shows up in logs or tracebacks


def normalise_username(username: str) -> str:
    """IITB's IMAP login is the LDAP id, the part before @iitb.ac.in. Students often type the
    whole address, so drop that suffix (and stray spaces). Other domains are left as typed."""
    name = username.strip()
    if name.lower().endswith("@iitb.ac.in"):
        name = name[: -len("@iitb.ac.in")]
    return name


def load() -> Credentials | None:
    username = keychain.get_secret(USERNAME_ENTRY)
    password = keychain.get_secret(PASSWORD_ENTRY)
    return Credentials(username, password) if username and password else None


def require() -> Credentials:
    creds = load()
    if creds is None:
        raise ConnectorError("not_connected", "Connect IITB Webmail in Settings first.")
    return creds


def saved_username() -> str | None:
    return keychain.get_secret(USERNAME_ENTRY)


def save(username: str, password: str) -> None:
    keychain.set_secret(USERNAME_ENTRY, username)
    keychain.set_secret(PASSWORD_ENTRY, password)


def delete() -> None:
    keychain.delete_secret(USERNAME_ENTRY, PASSWORD_ENTRY)
