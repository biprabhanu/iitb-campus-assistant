"""Phase-0 provider probe: list models and test tool calling with the owner's TEST key.

python scripts/probe_provider.py [--models a,b,c]

Reads TEST_LLM_PROVIDER and TEST_LLM_KEY from the repo `.env` itself. Prints only model
ids, pass/fail, and the provider's public rate-limit numbers. Never prints the key.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from campuspilot.llm.providers import get_provider  # noqa: E402

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

TOOL = {
    "type": "function",
    "function": {
        "name": "search_campus_docs",
        "description": "Search official IIT Bombay pages.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}
PROMPT = "Use the search tool to find where the IIT Bombay academic calendar is published."
LIMIT_HEADERS = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
)


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def probe(client: httpx.Client, base: str, model: str) -> tuple[str, float, dict[str, str]]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "tools": [TOOL],
        "temperature": 0,
        "max_tokens": 100,
    }
    started = time.monotonic()
    res = client.post(f"{base}/chat/completions", json=body)
    seconds = time.monotonic() - started
    limits = {h: res.headers.get(h, "") for h in LIMIT_HEADERS if res.headers.get(h)}
    if res.status_code != 200:
        return f"FAIL http {res.status_code}", seconds, limits
    message = (res.json().get("choices") or [{}])[0].get("message") or {}
    calls = message.get("tool_calls") or []
    ok = any((c.get("function") or {}).get("name") == "search_campus_docs" for c in calls)
    return ("pass" if ok else "FAIL no tool call"), seconds, limits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", help="comma-separated model ids to probe")
    args = parser.parse_args()

    env = read_env()
    provider = get_provider(env.get("TEST_LLM_PROVIDER", ""))
    key = env.get("TEST_LLM_KEY", "")
    if provider is None or not key:
        print("TEST_LLM_PROVIDER / TEST_LLM_KEY are not set in .env; nothing to probe.")
        return 1

    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=30, headers=headers) as client:
        res = client.get(f"{provider.base_url}/models")
        if res.status_code != 200:
            print(f"{provider.id}: /models returned HTTP {res.status_code}")
            return 1
        ids = sorted(m.get("id", "") for m in res.json().get("data", []))
        print(f"{provider.id}: {len(ids)} models: {', '.join(ids)}")
        wanted = (
            args.models.split(",")
            if args.models
            else [
                provider.router_model,
                provider.answer_model,
            ]
        )
        for model in dict.fromkeys(wanted):
            if model not in ids:
                print(f"  {model:45} not listed")
                continue
            result, seconds, limits = probe(client, provider.base_url, model)
            extra = " ".join(f"{k.removeprefix('x-ratelimit-')}={v}" for k, v in limits.items())
            print(f"  {model:45} {result:18} {seconds:5.1f}s  {extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
