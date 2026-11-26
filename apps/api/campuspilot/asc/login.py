"""IITB SSO login for ASC: find the login form, post the credentials, handle OTP / CAPTCHA.

The flow is generic on purpose (look at the page, find the form, post it) because the real SSO
page is only checked live in Phase 2. Page-specific hints live in `pages.py`.

Nothing secret is logged or put in an error message. The only POSTs ever sent are the SSO
login form and the OTP form, both before the session is marked `logged_in`.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from campuspilot.asc import pages
from campuspilot.asc.client import AscSession
from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError

log = logging.getLogger(__name__)

_TEXT_TYPES = {"text", "email", "tel", "number", "search", ""}


# ---------- reading login pages ----------


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


@dataclass
class FormSpec:
    """A form we are allowed to submit: where to, and what to send."""

    action: str
    fields: dict[str, str] = field(default_factory=dict)  # hidden inputs and the submit button
    user_field: str | None = None
    pass_field: str | None = None
    code_field: str | None = None


def has_captcha(soup: BeautifulSoup) -> bool:
    return any(soup.select_one(sel) for sel in pages.CAPTCHA_SELECTORS)


def _visible_text_inputs(form: Tag) -> list[Tag]:
    return [
        i
        for i in form.find_all("input")
        if i.get("name") and (i.get("type") or "text").lower() in _TEXT_TYPES
    ]


def find_password_form(soup: BeautifulSoup) -> Tag | None:
    for form in soup.find_all("form"):
        if form.find("input", attrs={"type": "password"}):
            return form
    return None


def find_otp_form(soup: BeautifulSoup) -> Tag | None:
    """A form without a password field that asks for a one-time code."""
    text = soup.get_text(" ").lower()
    text_hint = any(h in text for h in pages.OTP_TEXT_HINTS)
    for form in soup.find_all("form"):
        if form.find("input", attrs={"type": "password"}):
            continue
        inputs = _visible_text_inputs(form)
        named = [
            i
            for i in inputs
            if any(
                h in (i.get("name", "") + i.get("id", "")).lower() for h in pages.OTP_FIELD_HINTS
            )
        ]
        if named or (text_hint and len(inputs) == 1):
            return form
    return None


def parse_form(form: Tag, page_url: str, *, kind: str) -> FormSpec:
    """Read a login (kind="login") or OTP (kind="otp") form into a FormSpec."""
    action = urljoin(page_url, form.get("action") or page_url)
    spec = FormSpec(action=action)
    inputs = form.find_all("input")
    text_inputs = _visible_text_inputs(form)
    if kind == "login":
        password = form.find("input", attrs={"type": "password"})
        spec.pass_field = password.get("name") if password else None
        # Username = a text input whose name looks right, else the first text input.
        named = [
            i
            for i in text_inputs
            if any(h in i.get("name", "").lower() for h in pages.USERNAME_NAME_HINTS)
        ]
        picked = (named or text_inputs or [None])[0]
        spec.user_field = picked.get("name") if picked else None
        if not spec.user_field or not spec.pass_field:
            raise ConnectorError(
                "parse_failed", "The ASC login page looks different than expected."
            )
        skip = {spec.user_field, spec.pass_field}
    else:
        named = [
            i
            for i in text_inputs
            if any(
                h in (i.get("name", "") + i.get("id", "")).lower() for h in pages.OTP_FIELD_HINTS
            )
        ]
        picked = (named or text_inputs or [None])[0]
        spec.code_field = picked.get("name") if picked else None
        if not spec.code_field:
            raise ConnectorError("parse_failed", "The ASC verification page looks different.")
        skip = {spec.code_field}
    submit_seen = False
    for inp in inputs:
        name, kind_ = inp.get("name"), (inp.get("type") or "text").lower()
        if not name or name in skip:
            continue
        if kind_ == "hidden":
            spec.fields[name] = inp.get("value", "")
        elif kind_ == "submit" and not submit_seen:
            spec.fields[name] = inp.get("value", "")  # some SSO forms need the button's value
            submit_seen = True
    return spec


def looks_like_login(html: str) -> bool:
    """True when a page is a login or OTP form (so a read was bounced to the login)."""
    soup = make_soup(html)
    return find_password_form(soup) is not None or find_otp_form(soup) is not None


def is_asc_host(url: str) -> bool:
    base = urlsplit(get_settings().asc_base_url).hostname
    return urlsplit(url).hostname == base


# ---------- login state (memory only) ----------


@dataclass
class Pending:
    """A login waiting for the OTP. Holds the credentials in memory for a few minutes so they
    can go to the Keychain once the code works."""

    session: AscSession
    spec: FormSpec
    username: str
    password: str = field(repr=False)
    expires: float = 0.0
    tries: int = 0


class _State:
    def __init__(self) -> None:
        self.session: AscSession | None = None
        self.pending: dict[str, Pending] = {}
        self.cache: dict[str, tuple[float, str]] = {}  # path -> (expires, html); sensitive
        self.last_error: str | None = None


STATE = _State()
_GATES: dict[int, asyncio.Lock] = {}


def gate() -> asyncio.Lock:
    """One lock for all ASC work (login, reading). Kept per event loop."""
    loop_id = id(asyncio.get_running_loop())
    return _GATES.setdefault(loop_id, asyncio.Lock())


def forget() -> list[AscSession]:
    """Drop every session and cached page right now; returns the sessions still to close."""
    sessions = [p.session for p in STATE.pending.values()]
    if STATE.session:
        sessions.append(STATE.session)
    STATE.session, STATE.pending, STATE.cache, STATE.last_error = None, {}, {}, None
    return sessions


async def reset() -> None:
    """forget() and close everything (tests)."""
    for session in forget():
        await session.aclose()


async def _prune_pending() -> None:
    now = time.monotonic()
    for cid in [c for c, p in STATE.pending.items() if p.expires < now]:
        await STATE.pending.pop(cid).session.aclose()


# ---------- the flow ----------


def _check_status(response: httpx.Response) -> None:
    if response.status_code >= 500:
        raise ConnectorError(
            "unreachable", "ASC or the IITB login is having trouble right now. Try again later."
        )


async def _interpret(
    session: AscSession, response: httpx.Response, username: str, password: str
) -> Pending | None:
    """Decide what a post-login page means. None = logged in; Pending = OTP needed."""
    _check_status(response)
    soup = make_soup(response.text)
    if has_captcha(soup):
        raise ConnectorError(
            "blocked",
            "ASC asks for a CAPTCHA, so CampusPilot can't log in for you. Use ASC in your browser.",
        )
    otp_form = find_otp_form(soup)
    if otp_form is not None:
        spec = parse_form(otp_form, str(response.url), kind="otp")
        return Pending(
            session=session,
            spec=spec,
            username=username,
            password=password,
            expires=time.monotonic() + pages.PENDING_TTL_S,
        )
    if find_password_form(soup) is not None:
        # The login form came back: the SSO refused the username or password.
        raise ConnectorError("auth_failed", "ASC didn't accept that username and password.")
    if is_asc_host(str(response.url)) and soup.select_one(pages.HOME_LINK_SELECTOR):
        session.logged_in = True
        return None
    raise ConnectorError(
        "parse_failed", "CampusPilot couldn't tell whether the ASC login worked, so it stopped."
    )


async def authenticate(username: str, password: str) -> AscSession | Pending:
    """Log in from scratch. Returns a ready session, or a Pending that needs an OTP."""
    session = AscSession()
    try:
        first = await session.request("GET", get_settings().asc_base_url)
        _check_status(first)
        soup = make_soup(first.text)
        if has_captcha(soup):
            raise ConnectorError(
                "blocked",
                "ASC asks for a CAPTCHA, so CampusPilot can't log in for you. "
                "Use ASC in your browser.",
            )
        form = find_password_form(soup)
        if form is None:
            raise ConnectorError(
                "parse_failed", "The ASC login page looks different than expected."
            )
        spec = parse_form(form, str(first.url), kind="login")
        data = dict(spec.fields)
        data[spec.user_field or ""] = username
        data[spec.pass_field or ""] = password
        response = await session.request("POST", spec.action, data=data)
        pending = await _interpret(session, response, username, password)
    except BaseException:
        await session.aclose()
        raise
    return pending if pending is not None else session


async def login(username: str, password: str) -> tuple[AscSession | None, str | None]:
    """Full login for the Settings UI. Returns (session, None) or (None, challenge_id)."""
    await _prune_pending()
    result = await authenticate(username, password)
    if isinstance(result, Pending):
        challenge_id = secrets.token_urlsafe(16)
        STATE.pending[challenge_id] = result
        return None, challenge_id
    return result, None


async def submit_otp(challenge_id: str, code: str) -> tuple[AscSession, str, str]:
    """Send the OTP. Returns (session, username, password) so the caller can save them."""
    await _prune_pending()
    pending = STATE.pending.get(challenge_id)
    if pending is None:
        raise ConnectorError(
            "otp_invalid", "That login timed out. Connect ASC again to get a new code."
        )
    data = dict(pending.spec.fields)
    data[pending.spec.code_field or ""] = code
    try:
        response = await pending.session.request("POST", pending.spec.action, data=data)
        again = await _interpret(pending.session, response, pending.username, pending.password)
    except ConnectorError as exc:
        if exc.code in ("auth_failed", "blocked", "parse_failed", "unreachable", "timeout"):
            STATE.pending.pop(challenge_id, None)
            await pending.session.aclose()
        raise
    if again is None:
        STATE.pending.pop(challenge_id, None)
        return pending.session, pending.username, pending.password
    # The OTP page came back: the code was wrong. Allow a few tries on the same login.
    pending.tries += 1
    pending.spec = again.spec
    if pending.tries >= pages.MAX_OTP_TRIES:
        STATE.pending.pop(challenge_id, None)
        await pending.session.aclose()
        raise ConnectorError("otp_invalid", "Too many wrong codes. Connect ASC again.")
    raise ConnectorError("otp_invalid", "That code didn't work. Check it and try again.")
