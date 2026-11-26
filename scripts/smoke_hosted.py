#!/usr/bin/env python3
"""Smoke-test a deployed CampusPilot API.

Usage: python scripts/smoke_hosted.py URL [--origin ORIGIN]

Reads TEST_LLM_PROVIDER / TEST_LLM_KEY from the repo `.env` (never printed). Without a key the
live-answer and bad-key checks are skipped and the script says so. Exit code 1 on any failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "Where can I find the academic calendar?"


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        out[name.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return out


def sse_events(resp: httpx.Response):
    """Yield (event, data_json, seconds_since_start) from an SSE response."""
    start = time.monotonic()
    event = "message"
    for line in resp.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
            except ValueError:
                data = None
            yield event, data, time.monotonic() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--origin", default="")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    env = read_env(ROOT / ".env")
    provider = env.get("TEST_LLM_PROVIDER", "")
    key = env.get("TEST_LLM_KEY", "")
    have_key = bool(provider and key)
    results: list[tuple[str, str, str]] = []  # name, PASS/FAIL/SKIP, detail

    def record(name: str, ok: bool | None, detail: str = "") -> None:
        results.append((name, "SKIP" if ok is None else ("PASS" if ok else "FAIL"), detail))

    # Generous first timeout: a sleeping free instance takes about a minute to wake.
    with httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
        try:
            r = client.get(f"{base}/health")
            record("health", r.status_code == 200, f"HTTP {r.status_code}")
        except httpx.HTTPError as exc:
            record("health", False, type(exc).__name__)

        try:
            r = client.get(f"{base}/v1/status")
            body = r.json()
            ok = r.status_code == 200 and body.get("deploy_mode") == "hosted"
            record(
                "status",
                ok,
                f"mode={body.get('deploy_mode')} index={body.get('index')} "
                f"index_version={body.get('index_version')}",
            )
        except (httpx.HTTPError, ValueError) as exc:
            record("status", False, type(exc).__name__)

        try:
            r = client.post(f"{base}/v1/chat", json={"message": QUESTION})
            code = r.json().get("code") if r.status_code == 401 else None
            record(
                "chat without key",
                r.status_code == 401 and code == "MODEL_KEY_REQUIRED",
                f"HTTP {r.status_code} {code or ''}".strip(),
            )
        except (httpx.HTTPError, ValueError) as exc:
            record("chat without key", False, type(exc).__name__)

        if have_key:
            headers = {"X-LLM-Provider": provider, "X-LLM-Key": key}
            try:
                with client.stream(
                    "POST", f"{base}/v1/chat", json={"message": QUESTION}, headers=headers
                ) as r:
                    first_token = None
                    done = None
                    error = None
                    if r.status_code != 200:
                        record("chat with key", False, f"HTTP {r.status_code}")
                    else:
                        for event, data, t in sse_events(r):
                            if event == "token" and first_token is None:
                                first_token = t
                            elif event == "done":
                                done = data
                            elif event == "error":
                                error = (data or {}).get("code")
                        citations = (done or {}).get("citations") or []
                        ok = first_token is not None and bool(citations) and error is None
                        kind = (done or {}).get("answer_kind")
                        detail = (
                            f"first token {first_token:.1f}s, "
                            if first_token is not None
                            else "no token, "
                        ) + f"citations={len(citations)}, answer_kind={kind}"
                        if error:
                            detail += f", error={error}"
                        record("chat with key", ok, detail)
            except httpx.HTTPError as exc:
                record("chat with key", False, type(exc).__name__)

            fake = "x" * 8 + "fake-key-for-smoke-test-0123456789"
            try:
                bad_headers = {"X-LLM-Provider": provider, "X-LLM-Key": fake}
                code = None
                with client.stream(
                    "POST", f"{base}/v1/chat", json={"message": QUESTION}, headers=bad_headers
                ) as r:
                    if r.status_code == 200:
                        for event, data, _ in sse_events(r):
                            if event == "error":
                                code = (data or {}).get("code")
                    else:
                        r.read()
                        try:
                            code = r.json().get("code")
                        except ValueError:
                            code = None
                record("bad key rejected", code == "PROVIDER_KEY_REJECTED", f"code={code}")
            except httpx.HTTPError as exc:
                record("bad key rejected", False, type(exc).__name__)
        else:
            record("chat with key", None, "no TEST_LLM_PROVIDER/TEST_LLM_KEY in .env")
            record("bad key rejected", None, "no TEST_LLM_PROVIDER/TEST_LLM_KEY in .env")

        if args.origin:
            try:
                r = client.options(
                    f"{base}/v1/chat",
                    headers={
                        "Origin": args.origin,
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "content-type,x-llm-provider,x-llm-key",
                    },
                )
                got = r.headers.get("access-control-allow-origin")
                record("CORS preflight", got == args.origin, f"allow-origin={got}")
            except httpx.HTTPError as exc:
                record("CORS preflight", False, type(exc).__name__)
        else:
            record("CORS preflight", None, "no --origin given")

    width = max(len(n) for n, _, _ in results)
    for name, state, detail in results:
        print(f"{name:<{width}}  {state:<4}  {detail}")
    failed = [n for n, s, _ in results if s == "FAIL"]
    print("FAILED: " + ", ".join(failed) if failed else "all checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
