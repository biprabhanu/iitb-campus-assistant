"""One ASC web session: manual redirects, host allow-list, GET-only once logged in.

Cookies live in the httpx client's in-memory jar only; nothing is written to disk. The
messages of the errors raised here never contain URLs, page text or credentials.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from urllib.parse import urljoin, urlsplit

import httpx

from campuspilot.asc import pages
from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError

_REDIRECT_CODES = {301, 302, 303, 307, 308}
_UNREACHABLE = (
    "Can't reach ASC. ASC only works on the campus network or the IITB VPN, so check you are "
    "connected to one of them."
)


# httpx logs every request URL at INFO, and SSO redirect URLs carry one-time tickets. While an
# ASC request runs, drop httpx/httpcore log records so such URLs never reach a log file.
_in_asc_request: contextvars.ContextVar[bool] = contextvars.ContextVar("in_asc", default=False)


class _QuietDuringAsc(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _in_asc_request.get()


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_QuietDuringAsc())


def host_allowed(url: str) -> bool:
    """https only, and the host must end with `.iitb.ac.in`."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and host.endswith(pages.ALLOWED_HOST_SUFFIX)


class AscSession:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=get_settings().asc_timeout_s,
            follow_redirects=False,  # we follow by hand so every hop can be checked
            headers={"User-Agent": "CampusPilot (student prototype; read-only)"},
        )
        self._lock = asyncio.Lock()  # one request at a time: be polite to the portal
        # Set once login succeeded. From then on only GET is ever sent.
        self.logged_in = False

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(
        self, method: str, url: str, data: dict[str, str] | None = None
    ) -> httpx.Response:
        """Send one request and follow redirects. Returns the final response."""
        if method != "GET" and self.logged_in:
            # The core read-only guarantee: no form is ever submitted after login.
            raise ConnectorError("blocked", "ASC access is read-only; nothing was sent.")
        async with self._lock:
            hops = 0
            while True:
                if not host_allowed(url):
                    raise ConnectorError(
                        "blocked",
                        "ASC pointed CampusPilot to an address it doesn't trust, so it stopped.",
                    )
                response = await self._send(method, url, data)
                if response.status_code not in _REDIRECT_CODES:
                    return response
                location = response.headers.get("location")
                hops += 1
                if not location or hops > pages.MAX_REDIRECTS:
                    raise ConnectorError("blocked", "ASC redirected too many times, so it stopped.")
                url = urljoin(str(response.url), location)
                # After a redirect the credentials must never be sent again.
                method, data = "GET", None

    async def _send(self, method: str, url: str, data: dict[str, str] | None) -> httpx.Response:
        token = _in_asc_request.set(True)
        try:
            return await self._http.request(method, url, data=data)
        except httpx.TimeoutException:
            raise ConnectorError(
                "timeout", "ASC took too long to answer. Check the campus network or IITB VPN."
            ) from None
        except httpx.TransportError:
            raise ConnectorError("unreachable", _UNREACHABLE) from None
        finally:
            _in_asc_request.reset(token)
