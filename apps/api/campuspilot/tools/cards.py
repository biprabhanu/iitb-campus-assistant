"""Connector tool output -> cards for the `cards` SSE event (CONTRACT §11.3).

Cards go to the browser only. The chat model never sees them; it is told how many there were.
Ids are left empty here and numbered per turn by `number_cards` (W1.. mail, E1.. events,
A1.. ASC), so they are stable within one answer and unique across tools.
"""

from __future__ import annotations

import importlib
from typing import Any

from campuspilot.config import get_settings
from campuspilot.schemas.connectors import (
    AscCourseCard,
    AscCourseDetailsOutput,
    AscCourseHistoryOutput,
    AscCoursesOutput,
    AscDetailCard,
    AscFeeCard,
    AscFeeStatusOutput,
    AscHistoryCard,
    AscOfferedCoursesOutput,
    AscProfileCard,
    AscProfileOutput,
    AscRegistrationOutput,
    AscSlotCard,
    AscTimetableOutput,
    EventCard,
    ListRecentMailOutput,
    MailCard,
    SearchMyMailOutput,
    UpcomingEventsOutput,
)

_PREFIX = {"mail": "W", "event": "E"} | {
    t: "A"
    for t in ("asc_slot", "asc_course", "asc_profile", "asc_fee", "asc_history", "asc_detail")
}


def _calendar_connected() -> bool:
    """Is Google Calendar connected? Keychain only, no network. False on any problem."""
    if not get_settings().gcal_on:
        return False
    try:
        return bool(importlib.import_module("campuspilot.gcal").is_connected())
    except Exception:
        return False


def from_mail_search(output: SearchMyMailOutput) -> list[Any]:
    return [MailCard(id="", demo=output.demo, mail=m) for m in output.messages]


def from_recent_mail(output: ListRecentMailOutput) -> list[Any]:
    return [MailCard(id="", demo=output.demo, mail=m) for m in output.messages]


def from_events(output: UpcomingEventsOutput) -> list[Any]:
    calendar = _calendar_connected()
    return [
        EventCard(
            id="",
            demo=output.demo,
            event=e,
            # Never offer "Add" for a date we are not sure of, or for demo data.
            can_add_to_calendar=calendar
            and not output.demo
            and e.start is not None
            and not e.date_uncertain,
        )
        for e in output.events
    ]


def from_timetable(output: AscTimetableOutput) -> list[Any]:
    # A slot repeats weekly; when the answer covers exactly one day, show that date on the card.
    on_date = output.for_dates[0] if len(output.for_dates) == 1 else None
    return [AscSlotCard(id="", demo=output.demo, slot=s, on_date=on_date) for s in output.slots]


def from_asc_courses(output: AscCoursesOutput) -> list[Any]:
    return [AscCourseCard(id="", demo=output.demo, course=c) for c in output.courses]


def from_asc_profile(output: AscProfileOutput) -> list[Any]:
    return [AscProfileCard(id="", demo=output.demo, profile=output.profile)]


def from_asc_registration(output: AscRegistrationOutput) -> list[Any]:
    return [AscCourseCard(id="", demo=output.demo, course=c) for c in output.courses]


def from_asc_fees(output: AscFeeStatusOutput) -> list[Any]:
    return [AscFeeCard(id="", demo=output.demo, fee=f) for f in output.items]


def from_asc_offered(output: AscOfferedCoursesOutput) -> list[Any]:
    return [AscCourseCard(id="", demo=output.demo, course=c) for c in output.courses]


def from_asc_history(output: AscCourseHistoryOutput) -> list[Any]:
    return [
        AscHistoryCard(
            id="",
            demo=output.demo,
            course_code=output.course_code,
            title=output.title,
            offerings=output.offerings,
        )
    ]


def from_asc_detail(output: AscCourseDetailsOutput) -> list[Any]:
    return [AscDetailCard(id="", demo=output.demo, detail=output.detail)] if output.detail else []


def number_cards(cards: list[Any], counters: dict[str, int]) -> list[Any]:
    """Give each card its per-turn id. `counters` is shared across all tools in a turn."""
    numbered = []
    for card in cards:
        prefix = _PREFIX[card.type]
        counters[prefix] = counters.get(prefix, 0) + 1
        numbered.append(card.model_copy(update={"id": f"{prefix}{counters[prefix]}"}))
    return numbered
