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
    AscCourseDetailsInput,
    AscCourseHistoryInput,
    AscCurrentCoursesInput,
    AscFeeStatusInput,
    AscMyTimetableInput,
    AscOfferedCoursesInput,
    AscProfileInput,
    AscRegistrationStatusInput,
    ListRecentMailInput,
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
    # The student's own ASC data: offered only when the chat model is local (CONTRACT §11.8).
    local_only: bool = False
    # Overrides Settings.tool_timeout_s (ASC reads several slow pages, ~1 s apart).
    timeout_s: float | None = None


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


async def _recent_mail(args: ListRecentMailInput) -> Any:
    return await _call_connector("mail", "list_recent_mail", args)


async def _upcoming_events(args: UpcomingEventsInput) -> Any:
    return await _call_connector("mail", "get_upcoming_institute_events", args)


def _asc(name: str) -> Callable[[Any], Awaitable[Any]]:
    async def run(args: Any) -> Any:
        return await _call_connector("asc", name, args)

    return run


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
        "list_recent_mail",
        "List the newest mails in the student's IITB webmail inbox (read-only): sender, "
        "subject, date and a short snippet. Use for 'latest', 'new' or 'unread' mail questions; "
        "set unread_only=true for unread.",
        ListRecentMailInput,
        "Reading your latest mail",
        "mail",
        _recent_mail,
        to_cards=cd.from_recent_mail,
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
    # ASC (CONTRACT §11.8). local_only = the student's own data: offered only when the chat
    # model is the local one (Ollama/Gemma, or the offline mock). Public course data: any model.
    ToolSpec(
        "asc_profile",
        "The student's ASC profile: department, program, status, validity, academic standing "
        "and faculty advisors (read-only).",
        AscProfileInput,
        "Reading your ASC profile",
        "asc",
        _asc("asc_profile"),
        to_cards=cd.from_asc_profile,
        local_only=True,
        timeout_s=45.0,
    ),
    ToolSpec(
        "asc_my_timetable",
        "The student's class timetable from ASC. day: today, tomorrow, Mon..Sun, or omit for "
        "the whole week (read-only).",
        AscMyTimetableInput,
        "Reading your ASC timetable",
        "asc",
        _asc("asc_my_timetable"),
        to_cards=cd.from_timetable,
        local_only=True,
        timeout_s=45.0,
    ),
    ToolSpec(
        "asc_my_current_courses",
        "The student's current-semester courses from ASC (read-only).",
        AscCurrentCoursesInput,
        "Reading your ASC courses",
        "asc",
        _asc("asc_my_current_courses"),
        to_cards=cd.from_asc_courses,
        local_only=True,
        timeout_s=45.0,
    ),
    ToolSpec(
        "asc_registration_status",
        "The student's course registration status on ASC, or this semester's registered courses "
        "when the registration window is closed (read-only).",
        AscRegistrationStatusInput,
        "Checking your ASC registration",
        "asc",
        _asc("asc_registration_status"),
        to_cards=cd.from_asc_registration,
        local_only=True,
        timeout_s=45.0,
    ),
    ToolSpec(
        "asc_fee_status",
        "Scholarship month view (ASC). ASC's 'Fees Status/Scholarship' page is only a month and "
        "year picker for scholarship payments: there is no fee table, so this tool usually "
        "returns no rows and fee dues must be checked on ASC itself (read-only; never pays).",
        AscFeeStatusInput,
        "Checking the ASC scholarship month view",
        "asc",
        _asc("asc_fee_status"),
        to_cards=cd.from_asc_fees,
        local_only=True,
        timeout_s=45.0,
    ),
    ToolSpec(
        "asc_offered_courses",
        "Courses running in a department in a semester, from ASC. dept: prefix like IE; year: "
        "start year of the academic year (2026 = 2026-27); semester: autumn/spring/summer/winter.",
        AscOfferedCoursesInput,
        "Reading ASC running courses",
        "asc",
        _asc("asc_offered_courses"),
        to_cards=cd.from_asc_offered,
        timeout_s=40.0,
    ),
    ToolSpec(
        "asc_course_offering_history",
        "In which semesters a course ran over the last 3 academic years (Autumn and Spring), "
        "from ASC. Use for 'when is course X usually offered?'.",
        AscCourseHistoryInput,
        "Checking when the course runs",
        "asc",
        _asc("asc_course_offering_history"),
        to_cards=cd.from_asc_history,
        timeout_s=75.0,
    ),
    ToolSpec(
        "asc_course_details",
        "Details of one course from ASC: title, credits, prerequisites and syllabus.",
        AscCourseDetailsInput,
        "Reading the course details on ASC",
        "asc",
        _asc("asc_course_details"),
        to_cards=cd.from_asc_detail,
        timeout_s=40.0,
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


def offered_tools(settings: Settings | None = None, *, local_model: bool = True) -> list[ToolSpec]:
    """Tools the model may see.

    Moodle tools are always offered: the model only routes, and Moodle results never go back to
    it (CONTRACT §10.4). Mail and ASC tools are offered only when their connector is on, which
    is never in hosted mode (Settings.webmail_on / asc_on). Google Calendar has no tool at all.
    `local_only` tools (the student's own ASC data) are hidden unless the chat model is local
    (CONTRACT §11.8).
    """
    settings = settings or get_settings()
    hidden = set()
    if not settings.webmail_on:
        hidden.add("mail")
    if not settings.asc_on:
        hidden.add("asc")
    return [
        spec
        for spec in TOOLS.values()
        if spec.kind not in hidden and (local_model or not spec.local_only)
    ]


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
