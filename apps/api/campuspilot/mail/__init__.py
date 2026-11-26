"""IITB Webmail connector (read-only IMAP). CONTRACT §11.

Layout:
  imap_client.py  the only code that touches imaplib (login, read-only select, SEARCH, PEEK)
  parsing.py      raw bytes -> `MailMessage` card + text
  events.py       rule-based event detection (dates, times, venues, institute senders)
  extract.py      optional local-model refinement, checked against the mail text
  summary.py      optional local-model summary
  demo.py         fixture mails for CONNECTORS_DEMO
  credentials.py  Keychain storage;  tools.py  the public functions below
"""

from __future__ import annotations

from campuspilot.connectors.errors import ConnectorError
from campuspilot.mail.tools import (
    get_upcoming_institute_events,
    mail_login,
    mail_logout,
    mail_status,
    search_my_mail,
)

__all__ = [
    "ConnectorError",
    "get_upcoming_institute_events",
    "mail_login",
    "mail_logout",
    "mail_status",
    "search_my_mail",
]
