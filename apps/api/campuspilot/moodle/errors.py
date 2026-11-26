"""The one error type the Moodle tools raise."""

from __future__ import annotations

from typing import Literal

ErrorCode = Literal["not_configured", "invalid_token", "access_exception", "timeout", "unavailable"]


class MoodleError(Exception):
    """A Moodle problem with a short code and a message that is safe to show a student.

    Messages are always fixed, friendly strings: never a token, URL or server text.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message
