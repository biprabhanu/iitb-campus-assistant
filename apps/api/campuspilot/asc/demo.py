"""Demo mode (CONNECTORS_DEMO=true) and the fake ASC server used by the tests.

`DemoPortal` answers ASC requests from the synthetic HTML in `data/fixtures/asc/`, so demo mode
runs the real client, login, menu reading and parsers over made-up pages. Nothing here is real
student data. The tests use the same class as their fake server (`httpx.MockTransport`).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx

from campuspilot.config import REPO_ROOT

FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "asc"
HOST = "asc.iitb.ac.in"
NOTE_DEMO = "Demo data: made-up timetable and courses, not your ASC account."

# year (start of the academic year) -> semester -> fixture for the IE department
_LATEST_AUTUMN = 2026
_LATEST_SPRING = 2025  # Spring 2027 is "not published yet" in the demo


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _html(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text, headers={"content-type": "text/html"})


def _redirect(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": location})


class DemoPortal:
    """A tiny fake of asc.iitb.ac.in. `expect` = (ldap id, password) required to log in, or None
    to accept anything. `registration_open` switches CRFFormInput between the status page and the
    redirect to AcademicRecord.jsp."""

    def __init__(
        self,
        expect: tuple[str, str] | None = None,
        registration_open: bool = False,
    ) -> None:
        self.expect = expect
        self.registration_open = registration_open
        self.logged_in = False
        self.calls: list[tuple[str, str]] = []  # (method, path)
        self.queries: list[str] = []
        self.posted: list[dict[str, str]] = []
        self.overrides: dict[str, httpx.Response] = {}  # last path segment -> canned response

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def expire(self) -> None:
        self.logged_in = False

    def count(self, name: str) -> int:
        return sum(1 for _, path in self.calls if path.rsplit("/", 1)[-1] == name)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        self.calls.append((request.method, url.path))
        self.queries.append(url.query)
        name = url.path.rsplit("/", 1)[-1]
        if url.hostname != HOST:
            return httpx.Response(404)
        if request.method == "POST":
            return self._post(name, request)
        if name in self.overrides:
            return self.overrides[name]
        if url.path == "/acadmenu/":
            return _html(fixture("frameset.html"))
        if name == "Login.jsp":
            return _html(fixture("login.html"))
        if name == "menu.jsp":
            return _html(
                fixture("menu_signed_in.html" if self.logged_in else "menu_signed_out.html")
            )
        if name == "index.jsp" and "logout=yes" in url.query:
            self.logged_in = False
            return _html("<html><body>Signed out</body></html>")
        if not self.logged_in:
            return _redirect("/acadmenu/WebPages/Login.jsp")
        return self._page(name, parse_qs(url.query))

    def _post(self, name: str, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.posted.append(form)
        if name != "ldaplogin.jsp":
            return httpx.Response(404)
        ok = self.expect is None or (
            form.get("UserName") == self.expect[0] and form.get("UserPassword") == self.expect[1]
        )
        if not ok:
            return _html(fixture("login.html"))
        self.logged_in = True
        return _redirect("/acadmenu/menu.jsp")

    def _page(self, name: str, query: dict[str, list[str]]) -> httpx.Response:
        simple = {
            "VenueOccupancy.jsp": "timetable.html",
            "AcademicRecord.jsp": "academic_record.html",
            "allDept.jsp": "all_dept.html",
            "crsedetail.jsp": "crsedetail.html",
            "newallCourse.jsp": "newall_course.html",
            "Prereq": "prereq.html",
            "FeeStatus.jsp": "fee_status.html",
        }
        if name in simple:
            return _html(fixture(simple[name]))
        if name == "CRFFormInput.jsp":
            if self.registration_open:
                return _html(fixture("registration_status.html"))
            return _redirect("/academic/utility/AcademicRecord.jsp?TOKEN_REC_1")
        if name == "RunningCourses.jsp":
            return _html(fixture(self._running(query)))
        return httpx.Response(404)

    @staticmethod
    def _running(query: dict[str, list[str]]) -> str:
        dept = (query.get("deptcd", [""])[0]).upper().split(",")
        year = int((query.get("year", ["0"])[0]) or 0)
        semester = (query.get("semester", ["1"])[0]) or "1"
        if "IE" not in dept:
            return "running_empty.html"
        if semester == "1" and year <= _LATEST_AUTUMN:
            return "running_autumn.html"
        if semester == "2" and year <= _LATEST_SPRING:
            return "running_spring.html"
        return "running_empty.html"


def demo_transport() -> httpx.MockTransport:
    return DemoPortal(registration_open=False).transport()
