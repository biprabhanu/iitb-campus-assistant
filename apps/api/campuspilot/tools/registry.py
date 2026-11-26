"""Tool registry: name -> (input model, label, async function, kind).

The model may only *request* tools listed here; arguments are validated with the
input model before anything runs. Tool implementations from `retrieval` and `moodle`
are imported lazily so this module loads even if they are missing (and so tests can
swap in fakes via sys.modules or monkeypatch).
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from campuspilot.schemas.tools import (
    GetCourseContentsInput,
    GetMyDeadlinesInput,
    GetOfficialLinkInput,
    ListMyCoursesInput,
    SearchCampusDocsInput,
)
from campuspilot.tools import evidence as ev

ToolKind = Literal["doc", "moodle", "control"]


class ToolFailure(Exception):
    """A tool could not finish; the message is friendly and safe to show the model."""


class AskClarificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(default_factory=list, max_length=4)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    label: str
    kind: ToolKind
    run: Callable[[Any], Awaitable[Any]]
    to_evidence: Callable[[Any], ev.ToolEvidence] | None = None


# ---------- lazy callers ----------


def _retrieval() -> Any:
    return importlib.import_module("campuspilot.retrieval.tools")


def _moodle() -> Any:
    return importlib.import_module("campuspilot.moodle.tools")


async def _search_docs(args: SearchCampusDocsInput) -> Any:
    return await asyncio.to_thread(_retrieval().search_campus_docs, args)  # sync tool


async def _official_link(args: GetOfficialLinkInput) -> Any:
    return await asyncio.to_thread(_retrieval().get_official_link, args)


async def _call_moodle(func_name: str, args: BaseModel) -> Any:
    module = _moodle()
    try:
        return await getattr(module, func_name)(args)
    except module.MoodleError as exc:  # friendly message from the Moodle layer
        raise ToolFailure(exc.message) from exc


async def _my_courses(args: ListMyCoursesInput) -> Any:
    return await _call_moodle("list_my_courses", args)


async def _my_deadlines(args: GetMyDeadlinesInput) -> Any:
    return await _call_moodle("get_my_deadlines", args)


async def _course_contents(args: GetCourseContentsInput) -> Any:
    return await _call_moodle("get_course_contents", args)


async def _clarify(args: AskClarificationInput) -> AskClarificationInput:
    return args  # control tool: the orchestrator turns it into a follow-up


_SPECS = [
    ToolSpec(
        "search_campus_docs",
        "Search official IIT Bombay documents (rules, calendar, hostel, fees, forms). "
        "Use for any institutional question.",
        SearchCampusDocsInput,
        "Searching campus documents",
        "doc",
        _search_docs,
        ev.from_search,
    ),
    ToolSpec(
        "get_official_link",
        "Find the official page or portal for a topic. Use when the user needs the office "
        "or portal to contact.",
        GetOfficialLinkInput,
        "Finding the official page",
        "doc",
        _official_link,
        ev.from_links,
    ),
    ToolSpec(
        "list_my_courses",
        "List the student's Moodle courses (read-only).",
        ListMyCoursesInput,
        "Reading your Moodle courses",
        "moodle",
        _my_courses,
        ev.from_courses,
    ),
    ToolSpec(
        "get_my_deadlines",
        "List the student's upcoming Moodle deadlines (read-only).",
        GetMyDeadlinesInput,
        "Checking your Moodle deadlines",
        "moodle",
        _my_deadlines,
        ev.from_deadlines,
    ),
    ToolSpec(
        "get_course_contents",
        "List the sections and resources of one Moodle course (read-only).",
        GetCourseContentsInput,
        "Opening course contents",
        "moodle",
        _course_contents,
        ev.from_contents,
    ),
    ToolSpec(
        "ask_clarification",
        "Ask the student ONE short question when the answer depends on cohort, programme, "
        "semester, hostel or date. Give up to 4 quick-reply options.",
        AskClarificationInput,
        "Asking a clarifying question",
        "control",
        _clarify,
    ),
]

TOOLS: dict[str, ToolSpec] = {spec.name: spec for spec in _SPECS}


def offered_tools(mode: str, allow_personal_data_to_cloud: bool) -> list[ToolSpec]:
    """Tools the model may see. Moodle is hidden from a cloud fallback without consent."""
    hide_moodle = mode == "fallback" and not allow_personal_data_to_cloud
    return [t for t in TOOLS.values() if not (hide_moodle and t.kind == "moodle")]


def _strip_titles(node: Any) -> Any:
    """Pydantic adds noisy 'title' keys; the model doesn't need them."""
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def tool_schemas(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """Build the `tools` JSON for Ollama / OpenAI-style APIs from the Input models."""
    return [
        {
            "type": "function",
            "function": {
                "name": s.name,
                "description": s.description,
                "parameters": _strip_titles(s.input_model.model_json_schema()),
            },
        }
        for s in specs
    ]
