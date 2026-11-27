"""One ASC Internal session: LDAP login, menu tokens and read-only page fetches (CONTRACT §11.8).

Safety rules enforced here, for every request and every redirect hop:
- https only, exactly the ASC host (never another host), and a path on the allowlist
  (`pages.request_allowed`); POST only to the login form and the two GO forms;
- redirects are followed by hand so each hop is checked;
- one request at a time, `ASC_MIN_INTERVAL_S` apart, `ASC_TIMEOUT_S` per request;
- the cookie jar and the menu links (which carry session tokens) live in memory only;
- httpx/httpcore log records are dropped while a request runs, and no error message ever
  contains a URL, page text or a credential.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from campuspilot.asc import pages, parsers
from campuspilot.config import Settings, get_settings
from campuspilot.connectors.errors import ConnectorError

# Tests inject an httpx.MockTransport here. None = the real network.
TRANSPORT: httpx.AsyncBaseTransport | None = None

MAX_HOPS = 5
# ASC answers "Attempt Logged! Invalid Access." to page requests that do not look like a menu
# click in a browser: it needs a browser User-Agent and the menu page as Referer.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MSG_UNREACHABLE = "ASC needs the campus network or IITB VPN."
MSG_AUTH = "ASC rejected the LDAP id or password."
MSG_EXPIRED = "ASC signed you out. Connect ASC again in Settings."
MSG_BLOCKED = "That ASC page is not on CampusPilot's read-only list."
MSG_PAGE = "ASC could not show that page."

_QUIET: contextvars.ContextVar[bool] = contextvars.ContextVar("asc_quiet", default=False)


class _DropHttpLogs(logging.Filter):
    """httpx logs full request URLs at INFO; ASC URLs hold session tokens, so drop them."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not _QUIET.get()


_FILTER = _DropHttpLogs()
for _name in (
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
):
    logging.getLogger(_name).addFilter(_FILTER)


class SessionExpired(ConnectorError):
    """The page came back as the login form, or ASC answered 401/403."""

    def __init__(self) -> None:
        super().__init__("session_expired", MSG_EXPIRED)


@dataclass
class Page:
    text: str
    path: str  # final URL path (after redirects); no query, never logged
    redirected: bool = False
    status: int = 200

    def __repr__(self) -> str:
        return f"Page(status={self.status}, redirected={self.redirected})"


def normalise_username(username: str) -> str:
    name = username.strip()
    if name.lower().endswith("@iitb.ac.in"):
        name = name[: -len("@iitb.ac.in")]
    return name


class AscSession:
    def __init__(
        self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.base = self.settings.asc_base_url.rstrip("/")
        self.host = (urlsplit(self.base).hostname or "").lower()
        self._client = httpx.AsyncClient(
            transport=transport or TRANSPORT,
            timeout=httpx.Timeout(self.settings.asc_timeout_s),
            follow_redirects=False,
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html,*/*;q=0.8"},
        )
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._referer = f"{self.base}{pages.MENU_PATH}"
        self._links: dict[str, str] = {}  # menu key -> absolute URL with token (memory only)
        self.fee_pages: frozenset[str] = frozenset()
        self.signed_in = False

    def __repr__(self) -> str:  # never show links, cookies or the host path
        return f"AscSession(signed_in={self.signed_in}, pages={sorted(self._links)})"

    # ---- low level ----

    def _absolute(self, target: str, current: str | None = None) -> str:
        return urljoin(current or f"{self.base}{pages.ACADMENU_PATH}", target)

    async def _send(
        self,
        method: str,
        target: str,
        data: dict[str, str] | None = None,
        *,
        follow: bool = True,
        referer: str | None = None,
    ) -> tuple[httpx.Response, str, bool]:
        """Send one request and follow redirects by hand. Returns (response, final URL, hopped)."""
        url = self._absolute(target)
        hopped = False
        async with self._lock:
            for _ in range(MAX_HOPS + 1):
                if not pages.request_allowed(method, url, self.host, self.fee_pages):
                    raise ConnectorError("blocked", MSG_BLOCKED)
                wait = self.settings.asc_min_interval_s - (time.monotonic() - self._last)
                if wait > 0:
                    await asyncio.sleep(wait)
                token = _QUIET.set(True)
                try:
                    response = await self._client.request(
                        method, url, data=data, headers={"Referer": referer or self._referer}
                    )
                except httpx.TimeoutException as exc:
                    if isinstance(exc, httpx.ConnectTimeout):
                        raise ConnectorError("unreachable", MSG_UNREACHABLE) from None
                    raise ConnectorError("timeout", "ASC took too long to answer.") from None
                except (httpx.TransportError, httpx.InvalidURL):
                    raise ConnectorError("unreachable", MSG_UNREACHABLE) from None
                finally:
                    _QUIET.reset(token)
                    self._last = time.monotonic()
                if follow and response.is_redirect:
                    location = response.headers.get("location", "")
                    url = self._absolute(location, url)
                    method, data, hopped = "GET", None, True
                    continue
                return response, url, hopped
        raise ConnectorError("parse_failed", MSG_PAGE)

    async def get(
        self, target: str, *, allow_login_page: bool = False, referer: str | None = None
    ) -> Page:
        """GET a page. `referer` overrides the menu page (RunningCourses answers an empty table
        unless the request comes from the allDept page, as the GO form's would)."""
        response, url, hopped = await self._send("GET", target, referer=referer)
        path = urlsplit(url).path
        if response.status_code in (401, 403):
            raise SessionExpired()
        if response.status_code >= 400:
            raise ConnectorError("parse_failed", MSG_PAGE)
        text = response.text
        if not allow_login_page and (
            pages.basename(path) == "Login.jsp" or parsers.looks_like_login_page(text)
        ):
            raise SessionExpired()
        return Page(text, path, hopped, response.status_code)

    async def post(self, target: str, data: dict[str, str]) -> Page:
        """POST a GO form. Redirects are not followed (the caller GETs what it needs)."""
        response, url, _ = await self._send("POST", target, data, follow=False)
        if response.status_code in (401, 403):
            raise SessionExpired()
        return Page(response.text, urlsplit(url).path, False, response.status_code)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- menu links ----

    def link(self, key: str) -> str | None:
        return self._links.get(key)

    def set_menu(self, html: str) -> None:
        """Pick the needed page links out of menu.jsp, by label and target page."""
        menu_url = f"{self.base}{pages.MENU_PATH}"
        found = parsers.parse_menu(html)
        links: dict[str, str] = {}
        fee_pages: set[str] = set()
        for target in pages.MENU_LINKS:
            for leaf in found:
                if pages.norm_label(leaf.label) != pages.norm_label(target.label):
                    continue
                url = urljoin(menu_url, leaf.href)
                path = urlsplit(url).path
                if target.page is None:
                    if not pages.fee_page_allowed(leaf.label, path):
                        continue
                    fee_pages.add(pages.basename(path))
                elif pages.basename(path) != target.page or pages.label_forbidden(leaf.label):
                    continue
                links[target.key] = url
                break
        self._links = links
        self.fee_pages = frozenset(fee_pages)

    # ---- login / logout ----

    async def sign_in(self, username: str, password: str) -> None:
        """Frameset -> login form -> POST ldaplogin.jsp -> menu.jsp must say "Sign out"."""
        frameset = await self.get(pages.ACADMENU_PATH, allow_login_page=True)
        frames = parsers.parse_frameset(frameset.text)
        login_src = frames.get("rightPage") or pages.LOGIN_PAGE_PATH
        login_page = await self.get(
            self._absolute(login_src, f"{self.base}{pages.ACADMENU_PATH}"), allow_login_page=True
        )
        form = parsers.parse_login_form(login_page.text) or parsers.LoginForm(
            pages.LOGIN_POST_PATH, pages.LOGIN_USER_FIELD, pages.LOGIN_PASSWORD_FIELD
        )
        body = {
            **form.hidden,
            form.user_field: normalise_username(username),
            form.password_field: password,
        }
        action = self._absolute(form.action, self._absolute(login_src))
        await self.post(action, body)
        menu = await self.get(pages.MENU_PATH, allow_login_page=True)
        if not parsers.menu_signed_in(menu.text):
            raise ConnectorError("auth_failed", MSG_AUTH)
        self.signed_in = True
        self.set_menu(menu.text)

    async def refresh_menu(self) -> None:
        menu = await self.get(pages.MENU_PATH, allow_login_page=True)
        if not parsers.menu_signed_in(menu.text):
            raise SessionExpired()
        self.set_menu(menu.text)

    async def sign_out(self) -> None:
        """Best effort: tell ASC to end the session, then drop everything."""
        try:
            if self.signed_in:
                await self.get(pages.LOGOUT_PATH, allow_login_page=True)
        except ConnectorError:
            pass
        finally:
            self.signed_in = False
            self._links = {}
            await self.aclose()
