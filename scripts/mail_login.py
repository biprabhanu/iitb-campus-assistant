"""Save your IITB webmail login in the macOS Keychain (`make mail-login`).

Asks for the username and the password (hidden), checks them with a real IMAP login, and
stores them only if that worked. It prints success or failure and never echoes the password.
Run it on the campus network or the IITB VPN.
"""

from __future__ import annotations

import asyncio
import getpass
import sys

from pydantic import ValidationError

from campuspilot.connectors.errors import ConnectorError
from campuspilot.mail import mail_login
from campuspilot.schemas.connectors import ConnectorLoginRequest


def main() -> int:
    username = input("IITB LDAP username: ").strip()
    password = getpass.getpass("IITB LDAP password (hidden): ")
    if not username or not password:
        print("Both a username and a password are needed.")
        return 1
    try:
        asyncio.run(mail_login(ConnectorLoginRequest(username=username, password=password)))
    except ValidationError:  # its message would quote the input, so print our own
        print("Not saved: the username or password has an invalid length.")
        return 1
    except ConnectorError as exc:
        print(f"Not saved: {exc.message}")
        return 1
    print("Connected. The login is saved in your macOS Keychain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
