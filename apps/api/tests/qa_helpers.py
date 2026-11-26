"""Helpers shared by the journey, injection and failure tests.

The ScriptedLLM, fake tools and SSE parser live in backend_helpers.py; this file only
adds the small `run()` wrapper and a few readers so each test file stays short.
"""

from __future__ import annotations

from typing import Any

from campuspilot.agent.orchestrator import RunTrace, run_chat
from campuspilot.schemas.chat import ChatRequest


async def run(llm: Any, message: str = "when does the semester start?", history=None):
    """Run one chat turn and return (events, trace). Events are (name, data) pairs."""
    trace = RunTrace(request_id="qa")
    request = ChatRequest(message=message, history=history or [])
    events = [e async for e in run_chat(request, llm, trace)]
    return events, trace


def tool_states(events) -> list[tuple[str, str]]:
    return [(d["name"], d["state"]) for n, d in events if n == "tool"]


def sources_of(events) -> list[dict[str, Any]]:
    return next((d for n, d in events if n == "sources"), [])
