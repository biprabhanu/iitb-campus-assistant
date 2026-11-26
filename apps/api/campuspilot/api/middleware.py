"""Pure-ASGI middleware: request body size limit and one log line per request."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("campuspilot.request")
MAX_BODY_BYTES = 32 * 1024


class BodyTooLarge(Exception):
    pass


async def _send_json(send: Send, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class LimitsAndLogMiddleware:
    def __init__(self, app: ASGIApp, max_body: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_body = max_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        status = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
            await send(message)

        # Fast reject when the client announces a big body.
        length = dict(scope["headers"]).get(b"content-length")
        too_big = {"code": "BAD_REQUEST", "message": "That request is too large."}
        if length and length.isdigit() and int(length) > self.max_body:
            await _send_json(send_wrapper, 413, too_big)
        else:
            received = 0

            async def receive_wrapper() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_body:
                        raise BodyTooLarge
                return message

            try:
                await self.app(scope, receive_wrapper, send_wrapper)
            except BodyTooLarge:
                if not response_started:
                    await _send_json(send_wrapper, 413, too_big)

        # /v1/chat success logs its own, richer line when the stream ends.
        if scope["path"] == "/v1/chat" and status == 200:
            return
        ms = int((time.monotonic() - started) * 1000)
        log.info(
            "request_id=- model=- mode=- tools=[] chunks=[] latency_ms=%d error_code=%s path=%s "
            "status=%d",
            ms,
            "-" if status < 400 else status,
            scope["path"],
            status,
        )
