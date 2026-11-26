"""A fake LLM key and a fake Moodle token must never appear in logs or response bodies."""

from __future__ import annotations

import logging

import httpx
import respx

from campuspilot.moodle import client as moodle_client
from tests.hosted_helpers import FAKE_KEY, GROQ_URL, completion, hosted_client, tool_call
from tests.moodle_helpers import COURSES, REST_URL, SITE_INFO, assignments_payload, form_of

MOODLE_TOKEN = "fakemoodletoken0123456789"
HEADERS = {
    "X-LLM-Provider": "groq",
    "X-LLM-Key": FAKE_KEY,
    "X-Moodle-Token": MOODLE_TOKEN,
}
SECRETS = [FAKE_KEY, MOODLE_TOKEN]


def moodle_answers(request: httpx.Request) -> httpx.Response:
    """A tiny fake Moodle REST server."""
    data = {
        "core_webservice_get_site_info": SITE_INFO,
        "core_enrol_get_users_courses": COURSES,
        "mod_assign_get_assignments": assignments_payload([("Quiz 2", 1, 30)]),
        "core_calendar_get_action_events_by_timesort": {"events": []},
    }
    return httpx.Response(200, json=data[form_of(request)["wsfunction"]])


def assert_no_secrets(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


@respx.mock
def test_keys_never_reach_logs_or_responses(monkeypatch, caplog) -> None:
    moodle_client.clear_cache()
    for name in ("campuspilot", "httpx", "httpcore"):
        logging.getLogger(name).addHandler(caplog.handler)
        logging.getLogger(name).setLevel(logging.DEBUG)
    caplog.set_level(logging.DEBUG)

    respx.post(REST_URL).mock(side_effect=moodle_answers)

    def groq(request: httpx.Request) -> httpx.Response:
        if b"hello fail" in request.content:
            return httpx.Response(401, text=request.headers["authorization"])
        return completion(tool_calls=[tool_call("get_my_deadlines", days_ahead=7)])

    respx.post(GROQ_URL).mock(side_effect=groq)
    client = hosted_client(monkeypatch)

    answers = [
        client.post("/v1/chat", json={"message": "what is due this week?"}, headers=HEADERS),
        client.post("/v1/chat", json={"message": "hello fail"}, headers=HEADERS),
        client.post("/v1/llm/check", headers=HEADERS),
        client.post("/v1/moodle/check", headers=HEADERS),
        client.post(
            "/v1/chat", json={"message": "x"}, headers={**HEADERS, "X-LLM-Key": "bad key!"}
        ),
        client.post("/v1/chat", json={"message": "x"}, headers={**HEADERS, "X-Moodle-Token": "no"}),
        client.get("/v1/status", headers=HEADERS),
        client.options(
            "/v1/chat",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
        ),
    ]
    bodies = [r.text + str(dict(r.headers)) for r in answers]
    assert "Quiz 2" in bodies[0]  # the real Moodle path ran
    for body in bodies:
        assert_no_secrets(body)
    assert_no_secrets(caplog.text)
    assert "bad key!" not in caplog.text and "bad key!" not in "".join(bodies)
    assert len(caplog.records) > 0  # we really did capture something
