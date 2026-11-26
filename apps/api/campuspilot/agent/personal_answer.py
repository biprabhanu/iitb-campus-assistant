"""Template sentences for Webmail and ASC results (CONTRACT §11.4), like moodle_answer.py.

Our code writes these, not the chat model, so the student's mail and ASC data never has to be
sent to it. The data itself reaches the UI as `cards`. The one exception is a mail summary the
student asked for: the *local* model writes it in a separate call with no tools
(llm/personal.py), and we show it clearly labelled.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from campuspilot.schemas.connectors import (
    AscCoursesOutput,
    AscGradesOutput,
    AscTimetableOutput,
    GetMyTimetableInput,
    ListRecentMailInput,
    ListRecentMailOutput,
    SearchMyMailInput,
    SearchMyMailOutput,
    UpcomingEventsInput,
    UpcomingEventsOutput,
)

IST = ZoneInfo("Asia/Kolkata")


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {many or word + 's'}"


def _when(moment: datetime, all_day: bool = False) -> str:
    """'Tue 2 Dec, 4:00 pm' in IST, or 'Tue 2 Dec' for all-day events."""
    local = moment.astimezone(IST)
    day = f"{local:%a} {local.day} {local:%b}"
    if all_day:
        return day
    hour = local.hour % 12 or 12
    return f"{day}, {hour}:{local:%M} {'am' if local.hour < 12 else 'pm'}"


def _day(value: date) -> str:
    return f"{value:%a} {value.day} {value:%b}"


def mail_search_sentence(args: SearchMyMailInput, out: SearchMyMailOutput) -> str:
    window = f"from the last {_plural(args.days, 'day')}"
    if not out.messages:
        return f'I found no mails matching "{args.query}" {window}.'
    text = f'I found {_plural(len(out.messages), "mail")} matching "{args.query}" {window}.'
    if out.summary:
        text += f"\n\nSummary, written by the local model from these mails:\n{out.summary}"
    return text


def recent_mail_sentence(args: ListRecentMailInput, out: ListRecentMailOutput) -> str:
    what = "unread mail" if args.unread_only else "mail"
    if not out.messages:
        return f"You have no {what} in your inbox." if args.unread_only else "Your inbox is empty."
    many = "unread mails" if args.unread_only else "mails"
    count = _plural(len(out.messages), what, many)
    return f"Here {'is' if len(out.messages) == 1 else 'are'} your {count}, newest first."


def events_sentence(args: UpcomingEventsInput, out: UpcomingEventsOutput) -> str:
    what = "deadline" if args.only_deadlines else "institute event"
    window = f"in the next {_plural(args.days, 'day')}"
    if not out.events:
        return f"I found no {what}s in your mail {window}."
    text = f"I found {_plural(len(out.events), what)} in your mail {window}."
    dated = [e for e in out.events if e.start is not None and not e.date_uncertain]
    if dated:
        first = dated[0]
        text += f" The nearest is {first.title}, {_when(first.start, first.all_day)}."  # type: ignore[arg-type]
    unclear = len(out.events) - len(dated)
    if unclear:
        text += (
            f" {_plural(unclear, 'item has', 'items have')} an unclear date; check the source mail."
        )
    if out.events and not args.only_deadlines:
        text += " Use Add on a card to put it in your Google Calendar."
    return text


def timetable_sentence(args: GetMyTimetableInput, out: AscTimetableOutput) -> str:
    if args.on_date is not None:
        scope = f"on {_day(args.on_date)}"
    elif args.when == "this_week":
        scope = "this week"
    else:
        day = f" ({_day(out.for_dates[0])})" if len(out.for_dates) == 1 else ""
        scope = f"{args.when}{day}"
    if not out.slots:
        return f"Your ASC timetable shows no classes {scope}."
    return f"You have {_plural(len(out.slots), 'class', 'classes')} {scope}."


def asc_courses_sentence(out: AscCoursesOutput) -> str:
    sem = f" for {out.semester}" if out.semester else ""
    if not out.courses:
        text = f"ASC shows no registered courses{sem}."
    else:
        text = f"ASC shows {_plural(len(out.courses), 'course')}{sem}."
    if out.registration_note:
        text += f" {out.registration_note}"
    return text


def grades_sentence(out: AscGradesOutput) -> str:
    if not out.grades:
        return "ASC shows no grades yet."
    text = f"Here are your grades from ASC ({_plural(len(out.grades), 'course')})."
    scores = [f"{k} {v}" for k, v in (("SPI", out.spi), ("CPI", out.cpi)) if v]
    if scores:
        text += f" {', '.join(scores)} (as shown on ASC)."
    return text


_DEMO = {
    "search_my_mail": "mails",
    "list_recent_mail": "mails",
    "get_upcoming_institute_events": "events",
    "get_my_timetable": "timetable entries",
    "get_my_registered_courses": "courses",
    "get_my_grades": "grades",
}


def personal_sentence(tool_name: str, args: Any, output: Any) -> str:
    """The answer sentence for one Webmail or ASC tool result (plus its note and demo label)."""
    if tool_name == "search_my_mail":
        text = mail_search_sentence(args, output)
    elif tool_name == "list_recent_mail":
        text = recent_mail_sentence(args, output)
    elif tool_name == "get_upcoming_institute_events":
        text = events_sentence(args, output)
    elif tool_name == "get_my_timetable":
        text = timetable_sentence(args, output)
    elif tool_name == "get_my_registered_courses":
        text = asc_courses_sentence(output)
    else:
        text = grades_sentence(output)
    parts = [text]
    if output.note:
        parts.append(output.note)
    if output.demo:
        parts.append(f"These are demo {_DEMO[tool_name]}.")
    return " ".join(parts)
