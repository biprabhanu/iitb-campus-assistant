"""A fake ASC + SSO portal for the ASC tests, driven by respx. Everything here is synthetic.

`FakePortal.handle` answers every request, so tests can count calls and switch behaviour
(`mode`) without wiring individual routes.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from campuspilot.asc import login as login_module
from campuspilot.config import REPO_ROOT

FIXTURES = REPO_ROOT / "data" / "fixtures" / "asc"
ASC = "https://asc.iitb.ac.in"
SSO = "https://sso.iitb.ac.in"
USER, PASSWORD, OTP = "fakeuser", "fake-password-123", "123456"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def redirect(url: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": url})


class FakePortal:
    """mode: ok | otp | captcha | offsite_redirect | http_redirect"""

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.logged_in = False
        self.pages = {
            "/courses": fixture("courses.html"),
            "/timetable": fixture("timetable.html"),
            "/grades": fixture("grades.html"),
        }
        self.calls: list[tuple[str, str]] = []  # (method, "host/path")
        self.posted: list[dict[str, str]] = []  # form bodies of POSTs

    def expire(self) -> None:
        self.logged_in = False

    def count(self, method: str, path: str) -> int:
        return sum(1 for m, p in self.calls if m == method and p.endswith(path))

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        host = f"{url.scheme}://{url.netloc}"
        self.calls.append((request.method, f"{url.netloc}{url.path}"))
        if request.method == "POST":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.posted.append(form)
            return self._post(url.path, form)
        if host == SSO and url.path == "/login":
            page = "sso_captcha.html" if self.mode == "captcha" else "sso_login.html"
            return httpx.Response(200, text=fixture(page))
        if host == ASC:
            return self._asc_get(url.path)
        return httpx.Response(404)

    def _asc_get(self, path: str) -> httpx.Response:
        if path == "/home":  # the SSO sends the browser back here with a ticket
            self.logged_in = True
            return httpx.Response(200, text=fixture("asc_home.html"))
        if self.mode == "offsite_redirect":
            return redirect("https://evil.example.com/login")
        if self.mode == "http_redirect":
            return redirect("http://sso.iitb.ac.in/login")
        if not self.logged_in:
            return redirect(f"{SSO}/login?service=asc")
        if path in ("", "/"):
            return httpx.Response(200, text=fixture("asc_home.html"))
        if path in self.pages:
            return httpx.Response(200, text=self.pages[path])
        return httpx.Response(404)

    def _post(self, path: str, form: dict[str, str]) -> httpx.Response:
        if path == "/login/otp":
            if form.get("otp_code") == OTP:
                return redirect(f"{ASC}/home?ticket=ST-FAKE")
            return httpx.Response(200, text=fixture("sso_otp.html"))
        if path == "/login":
            if form.get("uname") != USER or form.get("pwd") != PASSWORD:
                return httpx.Response(200, text=fixture("sso_login_error.html"))
            if self.mode == "otp":
                return httpx.Response(200, text=fixture("sso_otp.html"))
            return redirect(f"{ASC}/home?ticket=ST-FAKE")
        return httpx.Response(404)


@pytest.fixture
def portal(respx_mock) -> FakePortal:
    fake = FakePortal()
    respx_mock.route().mock(side_effect=fake.handle)
    return fake


@pytest.fixture(autouse=True)
async def clean_asc_state():
    """Each test starts and ends with no ASC session, pending login or cached page."""
    await login_module.reset()
    yield
    await login_module.reset()
