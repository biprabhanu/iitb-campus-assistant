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

from campuspilot.config import Settings, get_settings
from campuspilot.schemas.connectors import (
    GetMyGradesInput,
    GetMyRegisteredCoursesInput,
    GetMyTimetableInput,
    SearchMyMailInput,
    UpcomingEventsInput,
)
from campuspilot.schemas.tools import (
    GetCourseContentsInput,
    GetMyDeadlinesInput,
    GetOfficialLinkInput,
    ListMyCoursesInput,
    SearchCampusDocsInput,
)
from campuspilot.tools import cards as cd
from campuspilot.tools import evidence as ev

# doc = public documents (evidence goes to the model); control = ask_clarification;
# moodle / mail / asc = the student's own data: shown as cards, the model only sees a count.
ToolKind = Literal["doc", "moodle", "mail", "asc", "control"]
PERSONAL_KINDS = frozenset({"moodle", "mail", "asc"})


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
    # v2 connectors (mail / asc): output -> cards for the UI (ids are filled in per turn).
    to_cards: Callable[[Any], list[Any]] | None = None


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


async def _call_connector(module_name: str, func_name: str, args: BaseModel) -> Any:
    """Run a v2 connector tool. Its ConnectorError has a friendly, secret-free message."""
    module = importlib.import_module(f"campuspilot.{module_name}")
    try:
        return await getattr(module, func_name)(args)
    except module.ConnectorError as exc:
        raise ToolFailure(exc.message) from exc


async def _search_mail(args: SearchMyMailInput) -> Any:
    return await _call_connector("mail", "search_my_mail", args)


async def _upcoming_events(args: UpcomingEventsInput) -> Any:
    return await _call_connector("mail", "get_upcoming_institute_events", args)


async def _timetable(args: GetMyTimetableInput) -> Any:
    return await _call_connector("asc", "get_my_timetable", args)


async def _asc_courses(args: GetMyRegisteredCoursesInput) -> Any:
    return await _call_connector("asc", "get_my_registered_courses", args)


async def _grades(args: GetMyGradesInput) -> Any:
    return await _call_connector("asc", "get_my_grades", args)


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
    # ---- v2 connectors (local only; offered only when their flag is on, CONTRACT §11) ----
    ToolSpec(
        "search_my_mail",
        "Search the student's own IITB webmail inbox (read-only). Set summarize=true only when "
        "the student asks for a summary.",
        SearchMyMailInput,
        "Searching your mail",
        "mail",
        _search_mail,
        to_cards=cd.from_mail_search,
    ),
    ToolSpec(
        "get_upcoming_institute_events",
        "Find institute events (talks, workshops, fests, exams) and deadlines announced in the "
        "student's mail. Set only_deadlines=true for 'what is due' questions.",
        UpcomingEventsInput,
        "Finding events in your mail",
        "mail",
        _upcoming_events,
        to_cards=cd.from_events,
    ),
    ToolSpec(
        "get_my_timetable",
        "The student's class timetable from ASC (read-only).",
        GetMyTimetableInput,
        "Reading your ASC timetable",
        "asc",
        _timetable,
        to_cards=cd.from_timetable,
    ),
    ToolSpec(
        "get_my_registered_courses",
        "The student's registered courses and registration status from ASC (read-only).",
        GetMyRegisteredCoursesInput,
        "Reading your ASC courses",
        "asc",
        _asc_courses,
        to_cards=cd.from_asc_courses,
    ),
    ToolSpec(
        "get_my_grades",
        "The student's grades from ASC (read-only). Only when the student asks for grades.",
        GetMyGradesInput,
        "Reading your ASC grades",
        "asc",
        _grades,
        to_cards=cd.from_grades,
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


def offered_tools(settings: Settings | None = None) -> list[ToolSpec]:
    """Tools the model may see.

    Moodle tools are always offered: the model only routes, and Moodle results never go back to
    it (CONTRACT §10.4). Mail and ASC tools are offered only when their connector is on, which
    is never in hosted mode (Settings.webmail_on / asc_on). Google Calendar has no tool at all.
    """
    settings = settings or get_settings()
    hidden = set()
    if not settings.webmail_on:
        hidden.add("mail")
    if not settings.asc_on:
        hidden.add("asc")
    return [spec for spec in TOOLS.values() if spec.kind not in hidden]


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
