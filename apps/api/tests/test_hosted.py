"""Hosted mode over HTTP: headers, errors, rate limits, CORS, status, Moodle endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from campuspilot.config import get_settings
from campuspilot.main import create_app
from campuspilot.moodle import tools as moodle_tools
from campuspilot.moodle.errors import MoodleError
from campuspilot.schemas.chat import MoodleTokenResponse
from tests.backend_helpers import done_of, install_fake_tools, names, parse_sse
from tests.hosted_helpers import (
    FAKE_KEY,
    GROQ_URL,
    HEADERS,
    completion,
    hosted_client,
    sse_stream,
    tool_call,
)

CHAT = {"message": "when does the semester start?"}


# ---------- header checks (CONTRACT §10.2) ----------


def test_chat_without_key_is_401_before_any_work(monkeypatch) -> None:
    client = hosted_client(monkeypatch)
    for headers in ({}, {"X-LLM-Provider": "groq"}, {"X-LLM-Key": FAKE_KEY}):
        response = client.post("/v1/chat", json=CHAT, headers=headers)
        assert response.status_code == 401
        assert response.json()["code"] == "MODEL_KEY_REQUIRED"


def test_missing_key_wins_over_a_bad_body(monkeypatch) -> None:
    client = hosted_client(monkeypatch)
    assert client.post("/v1/chat", json={"nope": 1}).status_code == 401


def test_unknown_provider_and_bad_model_are_400(monkeypatch) -> None:
    client = hosted_client(monkeypatch)
    bad_provider = {**HEADERS, "X-LLM-Provider": "evil.example.com"}
    response = client.post("/v1/chat", json=CHAT, headers=bad_provider)
    assert response.status_code == 400 and response.json()["code"] == "BAD_REQUEST"
    bad_model = {**HEADERS, "X-LLM-Model": "../../etc/passwd"}
    assert client.post("/v1/chat", json=CHAT, headers=bad_model).status_code == 400


def test_malformed_key_is_401_key_rejected(monkeypatch) -> None:
    client = hosted_client(monkeypatch)
    bad = {"X-LLM-Provider": "groq", "X-LLM-Key": "too short!"}
    response = client.post("/v1/chat", json=CHAT, headers=bad)
    assert response.status_code == 401 and response.json()["code"] == "PROVIDER_KEY_REJECTED"
    assert "too short" not in response.text


def test_local_mode_ignores_the_headers(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    monkeypatch.setenv("CAMPUSPILOT_MOCK_LLM", "true")
    get_settings.cache_clear()
    client = TestClient(create_app())
    response = client.post("/v1/chat", json=CHAT, headers={"X-LLM-Provider": "nonsense"})
    assert response.status_code == 200


def test_hosted_mock_llm_still_needs_headers(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    client = hosted_client(monkeypatch, CAMPUSPILOT_MOCK_LLM="true")
    assert client.post("/v1/chat", json=CHAT).status_code == 401
    response = client.post("/v1/chat", json=CHAT, headers=HEADERS)
    events = parse_sse(response.text)
    assert events[0][1]["mode"] == "mock" and names(events)[-1] == "done"


# ---------- provider failures arrive as SSE error events ----------


@respx.mock
def test_provider_key_rejected_becomes_sse_error(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    respx.post(GROQ_URL).mock(return_value=httpx.Response(401))
    client = hosted_client(monkeypatch)
    events = parse_sse(client.post("/v1/chat", json=CHAT, headers=HEADERS).text)
    assert events[0][1]["mode"] == "byok"
    error = events[-1][1]
    assert events[-1][0] == "error"
    assert error["code"] == "PROVIDER_KEY_REJECTED" and error["provider"] == "groq"


@respx.mock
def test_provider_rate_limit_error_has_retry_after(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    respx.post(GROQ_URL).mock(return_value=httpx.Response(429, headers={"retry-after": "9"}))
    client = hosted_client(monkeypatch)
    error = parse_sse(client.post("/v1/chat", json=CHAT, headers=HEADERS).text)[-1][1]
    assert error["code"] == "PROVIDER_RATE_LIMITED" and error["retry_after_s"] == 9


@respx.mock
def test_full_hosted_chat_with_a_fake_provider(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    respx.post(GROQ_URL).mock(
        side_effect=[
            completion(tool_calls=[tool_call("search_campus_docs", query="calendar")]),
            sse_stream("Classes start 3 Aug [S1]."),
        ]
    )
    client = hosted_client(monkeypatch)
    events = parse_sse(client.post("/v1/chat", json=CHAT, headers=HEADERS).text)
    assert done_of(events)["citations"] == ["S1"]


# ---------- /v1/llm/check ----------


@respx.mock
def test_llm_check_ok(monkeypatch) -> None:
    respx.post(GROQ_URL).mock(return_value=completion("a"))
    client = hosted_client(monkeypatch)
    response = client.post("/v1/llm/check", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "provider": "groq",
        "model": "llama-3.1-8b-instant",
        "code": None,
        "message": None,
    }


@pytest.mark.parametrize(
    ("upstream", "status", "code"),
    [
        (httpx.Response(401), 401, "PROVIDER_KEY_REJECTED"),
        (httpx.Response(429, headers={"retry-after": "5"}), 429, "PROVIDER_RATE_LIMITED"),
        (httpx.Response(500), 502, "PROVIDER_ERROR"),
        (httpx.ReadTimeout("slow"), 504, "PROVIDER_TIMEOUT"),
    ],
)
@respx.mock
def test_llm_check_failures(monkeypatch, upstream, status, code) -> None:
    effect = upstream if isinstance(upstream, Exception) else None
    route = respx.post(GROQ_URL)
    route.mock(side_effect=effect) if effect else route.mock(return_value=upstream)
    client = hosted_client(monkeypatch)
    response = client.post("/v1/llm/check", headers=HEADERS)
    body = response.json()
    assert response.status_code == status and body["ok"] is False and body["code"] == code
    assert FAKE_KEY not in response.text


def test_llm_check_needs_headers(monkeypatch) -> None:
    client = hosted_client(monkeypatch)
    assert client.post("/v1/llm/check").status_code == 401


# ---------- rate limits ----------


def test_per_minute_limit_with_retry_after(monkeypatch) -> None:
    client = hosted_client(monkeypatch, RATE_LIMIT_PER_MIN="3")
    for _ in range(3):
        assert client.post("/v1/chat", json=CHAT).status_code == 401  # counted, then refused
    response = client.post("/v1/chat", json=CHAT)
    body = response.json()
    assert response.status_code == 429 and body["code"] == "RATE_LIMITED"
    assert 1 <= body["retry_after_s"] <= 60 and response.headers["retry-after"]


def test_per_day_limit(monkeypatch) -> None:
    client = hosted_client(monkeypatch, RATE_LIMIT_PER_MIN="100", RATE_LIMIT_PER_DAY="4")
    codes = [client.post("/v1/llm/check").status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 429]
    assert client.post("/v1/llm/check").json()["retry_after_s"] > 60


def test_limits_apply_to_knowledge_search_and_moodle_check(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    client = hosted_client(monkeypatch, RATE_LIMIT_PER_MIN="1")
    assert client.post("/v1/knowledge/search", json={"query": "fees"}).status_code == 200
    assert client.post("/v1/knowledge/search", json={"query": "fees"}).status_code == 429
    assert client.post("/v1/moodle/check").status_code == 429


def test_hosted_uses_last_forwarded_for_entry(monkeypatch) -> None:
    client = hosted_client(monkeypatch, RATE_LIMIT_PER_MIN="2")
    # The leftmost entry is client-controlled: changing it must not reset the limit.
    for n in range(2):
        client.post("/v1/chat", json=CHAT, headers={"X-Forwarded-For": f"9.9.9.{n}, 5.5.5.5"})
    blocked = client.post("/v1/chat", json=CHAT, headers={"X-Forwarded-For": "1.1.1.1, 5.5.5.5"})
    assert blocked.status_code == 429
    other = client.post("/v1/chat", json=CHAT, headers={"X-Forwarded-For": "1.1.1.1, 6.6.6.6"})
    assert other.status_code == 401


def test_hosted_prefers_cf_connecting_ip(monkeypatch) -> None:
    client = hosted_client(monkeypatch, RATE_LIMIT_PER_MIN="1")
    base = {"X-Forwarded-For": "7.7.7.7"}
    assert (
        client.post("/v1/chat", json=CHAT, headers={**base, "CF-Connecting-IP": "a"}).status_code
        == 401
    )
    assert (
        client.post("/v1/chat", json=CHAT, headers={**base, "CF-Connecting-IP": "a"}).status_code
        == 429
    )
    assert (
        client.post("/v1/chat", json=CHAT, headers={**base, "CF-Connecting-IP": "b"}).status_code
        == 401
    )


def test_local_mode_ignores_forwarded_for(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    get_settings.cache_clear()
    client = TestClient(create_app())
    assert (
        client.post(
            "/v1/knowledge/search", json={"nope": 1}, headers={"X-Forwarded-For": "1.1.1.1"}
        ).status_code
        == 422
    )
    blocked = client.post(
        "/v1/knowledge/search", json={"nope": 1}, headers={"X-Forwarded-For": "2.2.2.2"}
    )
    assert blocked.status_code == 429


def test_body_over_8kb_is_413(monkeypatch) -> None:
    client = hosted_client(monkeypatch)
    response = client.post("/v1/chat", content=b"x" * 9000, headers=HEADERS)
    assert response.status_code == 413


# ---------- CORS ----------


def test_cors_preflight_allows_only_our_headers(monkeypatch) -> None:
    client = hosted_client(monkeypatch, ALLOWED_ORIGINS="https://campuspilot.vercel.app/")
    asked = "content-type,x-llm-provider,x-llm-key,x-llm-model,x-moodle-token,x-moodle-ical-url"
    response = client.options(
        "/v1/chat",
        headers={
            "Origin": "https://campuspilot.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": asked,
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://campuspilot.vercel.app"
    allowed = response.headers["access-control-allow-headers"].lower()
    for name in asked.split(","):
        assert name in allowed
    assert "DELETE" in response.headers["access-control-allow-methods"]


def test_cors_refuses_other_origins_and_headers(monkeypatch) -> None:
    client = hosted_client(monkeypatch)
    other = client.options(
        "/v1/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in other.headers
    odd = client.options(
        "/v1/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert odd.status_code == 400


# ---------- status ----------


def test_hosted_status_has_no_ollama_probe(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    with respx.mock:  # any Ollama call would fail: no route is registered
        body = hosted_client(monkeypatch).get("/v1/status").json()
    assert body["deploy_mode"] == "hosted" and body["mode"] == "byok" and body["model"] == "byok"
    assert body["model_online"] is True and body["model_loaded"] is True
    assert {p["id"] for p in body["providers"]} == {"groq", "gemini", "openai", "openrouter"}
    assert body["index"] in ("local", "missing") and "index_version" in body
    assert FAKE_KEY not in str(body)


def test_local_status_reports_deploy_mode_and_index(monkeypatch) -> None:
    install_fake_tools(monkeypatch)
    monkeypatch.setenv("CAMPUSPILOT_MOCK_LLM", "true")
    get_settings.cache_clear()
    body = TestClient(create_app()).get("/v1/status").json()
    assert body["deploy_mode"] == "local" and body["providers"] == []
    assert body["index"] == "missing"  # the test DB path does not exist


def test_release_index_info_comes_from_prepare_index(monkeypatch, tmp_path) -> None:
    import campuspilot.index_release as index_release

    info = index_release.IndexInfo("release", "index-2026-11-30", tmp_path / "x.db")
    monkeypatch.setattr(index_release, "prepare_index", lambda settings: info)
    install_fake_tools(monkeypatch)
    monkeypatch.setenv("INDEX_SOURCE", "release")
    monkeypatch.setenv("CAMPUSPILOT_MOCK_LLM", "true")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        body = client.get("/v1/status").json()
    assert body["index"] == "release" and body["index_version"] == "index-2026-11-30"


def test_failed_index_download_reports_missing(monkeypatch) -> None:
    import campuspilot.index_release as index_release

    def boom(settings):
        raise RuntimeError("no network")

    monkeypatch.setattr(index_release, "prepare_index", boom)
    install_fake_tools(monkeypatch)
    monkeypatch.setenv("INDEX_SOURCE", "release")
    monkeypatch.setenv("CAMPUSPILOT_MOCK_LLM", "true")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assert client.get("/v1/status").json()["index"] == "missing"


# ---------- Moodle endpoints ----------


def test_token_endpoints_are_404_when_hosted(monkeypatch) -> None:
    client = hosted_client(monkeypatch)
    for response in (
        client.post("/v1/moodle/token", json={"token": "abcdefgh1234"}),
        client.delete("/v1/moodle/token"),
    ):
        assert response.status_code == 404 and response.json()["code"] == "NOT_AVAILABLE"


def test_moodle_check_reads_headers_and_reports(monkeypatch) -> None:
    seen = {}

    async def fake_check() -> MoodleTokenResponse:
        from campuspilot.moodle.credentials import get_request_credentials

        seen["token"] = get_request_credentials().token
        return MoodleTokenResponse(ok=True, mode="rest", message="Connected.")

    monkeypatch.setattr(moodle_tools, "check_credentials", fake_check)
    client = hosted_client(monkeypatch)
    response = client.post("/v1/moodle/check", headers={"X-Moodle-Token": "abcdefgh12345678"})
    assert response.status_code == 200 and response.json()["ok"] is True
    assert seen["token"] == "abcdefgh12345678"
    from campuspilot.moodle.credentials import get_request_credentials

    assert get_request_credentials() is None  # reset after the request


@pytest.mark.parametrize(
    ("code", "status", "api_code"),
    [
        ("invalid_token", 400, "BAD_REQUEST"),
        ("unavailable", 503, "NOT_AVAILABLE"),
        ("timeout", 503, "NOT_AVAILABLE"),
    ],
)
def test_moodle_check_error_mapping(monkeypatch, code, status, api_code) -> None:
    async def failing() -> MoodleTokenResponse:
        raise MoodleError(code, "Some friendly text.")

    monkeypatch.setattr(moodle_tools, "check_credentials", failing)
    client = hosted_client(monkeypatch)
    response = client.post("/v1/moodle/check", headers={"X-Moodle-Token": "abcdefgh12345678"})
    assert response.status_code == status and response.json()["code"] == api_code


def test_moodle_check_bad_header_is_400_even_for_unavailable(monkeypatch) -> None:
    client = hosted_client(monkeypatch)
    response = client.post(
        "/v1/moodle/check", headers={"X-Moodle-Ical-Url": "https://evil.example/x"}
    )
    assert response.status_code == 400 and response.json()["code"] == "BAD_REQUEST"


# ---------- hosted budgets ----------


async def test_hosted_budgets_trim_history_and_evidence(monkeypatch) -> None:
    from campuspilot.agent.orchestrator import RunTrace, run_chat
    from campuspilot.llm.base import LLMReply
    from campuspilot.schemas.chat import ChatRequest, ChatTurn
    from tests.backend_helpers import ScriptedLLM, call, make_hit

    hits = [make_hit(i, text="word " * 1000, url=f"https://www.iitb.ac.in/{i}") for i in range(8)]
    install_fake_tools(monkeypatch, hits=hits)
    monkeypatch.setenv("DEPLOY_MODE", "hosted")
    get_settings.cache_clear()
    history = [ChatTurn(role="user", content=f"turn {n}") for n in range(12)]
    llm = ScriptedLLM(
        [LLMReply(tool_calls=[call("search_campus_docs", query="x")])], stream_pieces=["ok [S1]"]
    )
    request = ChatRequest(message="when does the semester start?", history=history)
    _ = [e async for e in run_chat(request, llm, RunTrace("t"))]
    sent = llm.stream_messages
    assert sum(m["content"].startswith("turn") for m in sent) == 6
    evidence = "".join(m["content"] for m in sent if m["role"] == "tool")
    assert evidence.count("<evidence ") <= 5 and len(evidence) < 2500 * 4 + 1500
    assert len(sent[0]["content"]) < 900  # the short hosted system prompt
