"""Save your IITB webmail login in the macOS Keychain (`make mail-login`).

Asks for your LDAP id and an IITB SSO access token for Emails (hidden), checks them with a
real IMAP login, and stores them only if that worked. IITB's IMAP server does not accept the
LDAP password itself. Create a token at sso.iitb.ac.in -> Manage account -> Access tokens ->
Emails. Prints success or failure and never echoes the token. Run it on the campus network or
the IITB VPN.
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
    print("IITB Webmail needs an SSO access token, not your LDAP password.")
    print("Create one at https://sso.iitb.ac.in -> Manage account -> Access tokens -> Emails.\n")
    username = input("IITB LDAP id: ").strip()
    password = getpass.getpass("SSO access token for Emails (hidden): ")
    if not username or not password:
        print("Both your LDAP id and the access token are needed.")
        return 1
    try:
        asyncio.run(mail_login(ConnectorLoginRequest(username=username, password=password)))
    except ValidationError:  # its message would quote the input, so print our own
        print("Not saved: the LDAP id or token has an invalid length.")
        return 1
    except ConnectorError as exc:
        print(f"Not saved: {exc.message}")
        return 1
    print("Connected. The login is saved in your macOS Keychain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
