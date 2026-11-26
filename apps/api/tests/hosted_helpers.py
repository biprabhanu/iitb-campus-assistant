"""Shared helpers for the hosted-mode tests: an app client, fake keys, a fake Groq."""

from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from campuspilot.config import get_settings
from campuspilot.main import create_app

FAKE_KEY = "FAKEKEY_test_0123456789abcdefXYZ"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
HEADERS = {"X-LLM-Provider": "groq", "X-LLM-Key": FAKE_KEY}


def hosted_client(monkeypatch, **env: str) -> TestClient:
    monkeypatch.setenv("DEPLOY_MODE", "hosted")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    return TestClient(create_app())


def completion(content: str = "", tool_calls: list[dict] | None = None) -> httpx.Response:
    message: dict = {"content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return httpx.Response(200, json={"choices": [{"message": message}]})


def tool_call(name: str, **arguments: object) -> dict:
    return {"function": {"name": name, "arguments": json.dumps(arguments)}}


def sse_stream(*pieces: str) -> httpx.Response:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}" for p in pieces]
    return httpx.Response(200, content="\n\n".join([*lines, "data: [DONE]"]) + "\n\n")
