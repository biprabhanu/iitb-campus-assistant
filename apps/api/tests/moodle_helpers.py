"""Shared fake data and respx helpers for the Moodle tests. Everything here is fake."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import respx

BASE = "https://moodle.iitb.ac.in"
REST_URL = f"{BASE}/webservice/rest/server.php"
FAKE_TOKEN = "faketoken0123456789abcdef"
FAKE_ICAL_URL = f"{BASE}/calendar/export_execute.php?userid=1&authtoken=fakeauth99&preset_what=all"


def form_of(request: httpx.Request) -> dict[str, str]:
    """The form fields of a request, as a plain dict."""
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def unix_in(hours: float) -> int:
    return int((datetime.now(UTC) + timedelta(hours=hours)).timestamp())


def mock_rest(router: respx.MockRouter, responses: dict[str, object]) -> respx.Route:
    """Answer REST calls by wsfunction name. Dict values are returned as JSON (HTTP 200)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses[form_of(request)["wsfunction"]])

    return router.post(REST_URL).mock(side_effect=handler)


SITE_INFO = {"sitename": "Fake IITB Moodle", "fullname": "Test Student", "userid": 42}
COURSES = [
    {"id": 11, "shortname": "IE624", "fullname": "Decision Analytics"},
    {"id": 12, "shortname": "HS101", "fullname": "Economics"},
]


def assignments_payload(hours_list: list[tuple[str, int, float]]) -> dict:
    """hours_list: (title, id, due hours from now), all in course IE624."""
    items = [{"id": i, "cmid": 900 + i, "name": t, "duedate": unix_in(h)} for t, i, h in hours_list]
    return {"courses": [{"id": 11, "shortname": "IE624", "assignments": items}]}


def events_payload(rows: list[tuple[str, int, float, str, str]]) -> dict:
    """rows: (name, id, due hours, course shortname, url)."""
    return {
        "events": [
            {"id": i, "name": n, "timesort": unix_in(h), "course": {"shortname": c}, "url": u}
            for n, i, h, c, u in rows
        ]
    }


def ics_text(events: list[tuple[str, float, str]]) -> str:
    """Build a tiny .ics. events: (summary, due hours from now, categories)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN"]
    for n, (summary, hours, cat) in enumerate(events):
        start = (datetime.now(UTC) + timedelta(hours=hours)).strftime("%Y%m%dT%H%M%SZ")
        lines += ["BEGIN:VEVENT", f"UID:t{n}@x", "DTSTAMP:20300101T000000Z", f"DTSTART:{start}"]
        lines.append(f"SUMMARY:{summary}")
        if cat:
            lines.append(f"CATEGORIES:{cat}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def dumps(data: object) -> str:
    return json.dumps(data)
