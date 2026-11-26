"""HTTP layer: endpoints, SSE, limits, CORS, status, secrets."""

from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from campuspilot.config import get_settings
from campuspilot.main import create_app
from campuspilot.schemas.chat import MoodleTokenResponse
from tests.backend_helpers import (
    OLLAMA,
    answer_text,
    done_of,
    install_fake_tools,
    names,
    ndjson,
    parse_sse,
)

CHAT = {"message": "when does the semester start?"}


def make_client(monkeypatch, **env: str) -> TestClient:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return TestClient(create_app())


def test_health(monkeypatch) -> None:
    client = make_client(monkeypatch)
    assert client.get("/health").json() == {"ok": True}
    assert client.get("/v1/ping").json() == {"ok": True}


def test_mock_chat_streams_sse_in_order(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    client = make_client(monkeypatch, CAMPUSPILOT_MOCK_LLM="true")
    response = client.post("/v1/chat", json={"message": "show the academic calendar"})
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-cache" in response.headers["cache-control"]
    events = parse_sse(response.text)
    order = names(events)
    assert order[0] == "status" and order[-1] == "done"
    assert order.index("tool") < order.index("sources") < order.index("token")
    assert events[0][1]["mode"] == "mock"
    assert done_of(events)["citations"] == ["S1"] and "[S1]" in answer_text(events)


@respx.mock
def test_live_chat_with_ollama_tool_call_and_streaming(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    tool_reply = {
        "message": {
            "content": "",
            "tool_calls": [
                {"function": {"name": "search_campus_docs", "arguments": {"query": "calendar"}}}
            ],
        }
    }
    respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[
            httpx.Response(200, json=tool_reply),
            # after one tool round the answer is a real streaming call (no tools offered)
            httpx.Response(
                200,
                content=ndjson(
                    {"message": {"content": "Classes start 3 Aug [S1] [S5]."}, "done": False},
                    {"message": {"content": ""}, "done": True},
                ),
            ),
        ]
    )
    client = make_client(monkeypatch)
    events = parse_sse(client.post("/v1/chat", json=CHAT).text)
    assert events[0][1]["mode"] == "live"
    assert answer_text(events) == "Classes start 3 Aug [S1] ."
    assert done_of(events)["citations"] == ["S1"]


@respx.mock
def test_tunnel_down_gives_model_offline_event(monkeypatch) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    client = make_client(monkeypatch)
    events = parse_sse(client.post("/v1/chat", json=CHAT).text)
    assert names(events) == ["status", "error"]
    assert events[1][1]["code"] == "MODEL_OFFLINE"
    assert "offline" in events[1][1]["message"]


@respx.mock
def test_slow_model_gives_timeout_event(monkeypatch) -> None:
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=httpx.ReadTimeout("slow"))
    client = make_client(monkeypatch)
    events = parse_sse(client.post("/v1/chat", json=CHAT).text)
    assert events[-1][1]["code"] == "TIMEOUT"


def test_rate_limit_returns_429_json(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    client = make_client(monkeypatch, CAMPUSPILOT_MOCK_LLM="true", RATE_LIMIT_PER_MIN="3")
    codes = [client.post("/v1/chat", json=CHAT).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    body = client.post("/v1/chat", json=CHAT).json()
    assert body["code"] == "RATE_LIMITED" and body["message"]


def test_cors_allows_only_configured_origins(monkeypatch) -> None:
    client = make_client(monkeypatch)
    good = client.get("/health", headers={"Origin": "http://localhost:3000"})
    bad = client.get("/health", headers={"Origin": "https://evil.example"})
    assert good.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers
    preflight = client.options(
        "/v1/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 400


def test_body_over_32kb_is_rejected(monkeypatch) -> None:
    client = make_client(monkeypatch)
    response = client.post(
        "/v1/chat", content=b"x" * 40_000, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413 and response.json()["code"] == "BAD_REQUEST"


def test_validation_error_is_friendly_and_does_not_echo_input(monkeypatch) -> None:
    client = make_client(monkeypatch)
    response = client.post("/v1/chat", json={"message": ""})
    assert response.status_code == 422
    assert response.json()["code"] == "BAD_REQUEST" and "message" in response.json()["message"]
    secret_try = client.post("/v1/chat", json={"message": "hi", "extra": "SUPERSECRETVALUE"})
    assert "SUPERSECRETVALUE" not in secret_try.text


def test_unexpected_errors_hide_details(monkeypatch) -> None:
    client_app = create_app()
    monkeypatch.setitem(
        sys.modules,
        "campuspilot.retrieval.tools",
        SimpleNamespace(
            list_sources=lambda db_path=None: (_ for _ in ()).throw(RuntimeError("secret path /x"))
        ),
    )
    client = TestClient(client_app, raise_server_exceptions=False)
    response = client.get("/v1/sources")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL" and "secret" not in response.text


@respx.mock
def test_status_degrades_when_everything_is_down(monkeypatch) -> None:
    respx.get(f"{OLLAMA}/api/tags").mock(side_effect=httpx.ConnectError("down"))
    respx.get(f"{OLLAMA}/api/ps").mock(side_effect=httpx.ConnectError("down"))

    def boom(*a, **k):
        raise RuntimeError("db missing")

    async def moodle_boom():
        raise RuntimeError("moodle down")

    monkeypatch.setitem(
        sys.modules, "campuspilot.retrieval.tools", SimpleNamespace(count_indexed_sources=boom)
    )
    monkeypatch.setitem(
        sys.modules, "campuspilot.moodle.tools", SimpleNamespace(moodle_status=moodle_boom)
    )
    body = make_client(monkeypatch).get("/v1/status").json()
    assert body["model_online"] is False and body["model_loaded"] is False
    assert body["moodle"] == "error" and body["sources_indexed"] == 0 and body["mode"] == "live"


@respx.mock
def test_status_when_all_is_well(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    model = get_settings().ollama_model
    respx.get(f"{OLLAMA}/api/tags").respond(json={"models": [{"name": model}]})
    respx.get(f"{OLLAMA}/api/ps").respond(json={"models": [{"name": model}]})
    body = make_client(monkeypatch).get("/v1/status").json()
    assert body["model_online"] and body["model_loaded"]
    assert body["moodle"] == "connected" and body["sources_indexed"] == 7


def test_moodle_token_is_never_echoed_or_logged(monkeypatch, caplog) -> None:
    token = "tok_ABCDEF1234567890"

    async def save_credentials(req):
        return MoodleTokenResponse(
            ok=True,
            mode="rest",
            site_name="IITB Moodle",
            user_fullname="A Student",
            message="Connected.",
        )

    monkeypatch.setitem(
        sys.modules,
        "campuspilot.moodle.tools",
        SimpleNamespace(
            save_credentials=save_credentials,
            MoodleError=Exception,
            delete_credentials=lambda: MoodleTokenResponse(
                ok=True, mode="none", message="Removed."
            ),
        ),
    )
    client = make_client(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        saved = client.post("/v1/moodle/token", json={"token": token})
        bad = client.post(
            "/v1/moodle/token", json={"token": token, "ical_url": "https://x.example/ical"}
        )
        invalid = client.post("/v1/moodle/token", json={"token": "short"})
        removed = client.delete("/v1/moodle/token")
    assert saved.json()["ok"] is True and removed.json()["message"] == "Removed."
    assert bad.status_code == 400
    for response in (saved, bad, invalid, removed):
        assert token not in response.text
    assert token not in caplog.text


def test_token_never_logged_on_unexpected_failure(monkeypatch, caplog) -> None:
    token = "tok_ABCDEF1234567890"

    async def explode(req):
        raise RuntimeError(f"failed with {req.token}")

    monkeypatch.setitem(
        sys.modules,
        "campuspilot.moodle.tools",
        SimpleNamespace(save_credentials=explode, MoodleError=ValueError),
    )
    client = TestClient(create_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        response = client.post("/v1/moodle/token", json={"token": token})
    assert response.status_code == 500 and token not in response.text
    assert token not in caplog.text


def test_chat_log_line_has_no_message_text(monkeypatch, caplog) -> None:
    install_fake_tools(monkeypatch)
    client = make_client(monkeypatch, CAMPUSPILOT_MOCK_LLM="true")
    with caplog.at_level(logging.INFO, logger="campuspilot.request"):
        client.post("/v1/chat", json={"message": "calendar for PRIVATEWORD"})
    assert "PRIVATEWORD" not in caplog.text
    line = next(r.getMessage() for r in caplog.records if "request_id=" in r.getMessage())
    assert "mode=mock" in line and "search_campus_docs" in line and "latency_ms=" in line


def test_knowledge_search_and_sources(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    client = make_client(monkeypatch)
    hits = client.post("/v1/knowledge/search", json={"query": "calendar"}).json()["hits"]
    assert hits[0]["chunk_id"] == 1
    assert client.get("/v1/sources").json() == []


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_docs_are_not_exposed(monkeypatch, path) -> None:
    assert make_client(monkeypatch).get(path).status_code == 404
