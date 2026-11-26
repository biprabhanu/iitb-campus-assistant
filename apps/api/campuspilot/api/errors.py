"""The one HTTP error type the API raises (main.py renders it as JSON)."""

from __future__ import annotations


class ApiError(Exception):
    """An error with an HTTP status and a friendly message (rendered as JSON)."""

    def __init__(
        self, status: int, code: str, message: str, retry_after_s: int | None = None
    ) -> None:
        self.status, self.code, self.message = status, code, message
        self.retry_after_s = retry_after_s
