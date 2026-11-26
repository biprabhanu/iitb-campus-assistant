"""The one exception type every v2 connector raises (CONTRACT §11.6).

`message` is friendly and safe to show the student. It never contains a password, OTP, token,
cookie, mail text or grade, so it can go to the UI, the model (as a note) and the logs.
"""

from __future__ import annotations

from typing import Literal

ConnectorErrorCode = Literal[
    "disabled",  # flag off or hosted mode
    "not_connected",  # no credentials saved
    "auth_failed",  # wrong username / password, or a revoked Google token
    "otp_required",  # a one-time code is needed; the UI asks the student
    "otp_invalid",
    "session_expired",  # ASC session ran out; log in again
    "unreachable",  # off campus without VPN, DNS, connection refused
    "timeout",
    "parse_failed",  # the page or mail format changed; nothing was guessed
    "blocked",  # cannot be automated safely (e.g. CAPTCHA); the student does it themselves
    "google_error",  # Google Calendar API refused for another reason
    "not_implemented",  # Phase 0 stub, replaced by the worker's real module
]


class ConnectorError(Exception):
    def __init__(self, code: ConnectorErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __repr__(self) -> str:  # never include anything but the code and safe message
        return f"ConnectorError({self.code!r}, {self.message!r})"
