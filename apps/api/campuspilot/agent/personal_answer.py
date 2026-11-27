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


_SEMESTER_WORD = {"autumn": "Autumn", "spring": "Spring", "summer": "Summer", "winter": "Winter"}
_DAY_NAME = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
    "Sat": "Saturday",
    "Sun": "Sunday",
}
_DUE_WORDS = ("due", "pending", "unpaid", "not paid", "overdue", "outstanding")


def _year_label(year: int) -> str:
    return f"{year}-{(year + 1) % 100:02d}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _timetable_sentence(args: Any, out: Any) -> str:
    n = len(out.slots)
    if len(out.for_dates) == 1:
        when = f"{args.day or 'on that day'} ({_day(out.for_dates[0])})"
    elif args.day:
        when = f"on {_DAY_NAME.get(args.day, args.day)}"
    else:
        when = "this week"
    if n == 0:
        return f"Your ASC timetable shows no classes {when}."
    return f"You have {_plural(n, 'class', 'classes')} {when}."


def _registration_sentence(out: Any) -> str:
    semester = f" for {out.semester}" if out.semester else ""
    n = len(out.courses)
    if not out.window_open:
        if n == 0:
            return f"ASC shows no registered courses{semester}."
        return f"ASC shows {_plural(n, 'registered course')}{semester}."
    if n == 0:
        return "Registration is open. ASC shows no courses on your registration yet."
    counts: dict[str, int] = {}
    for course in out.courses:
        counts[course.status] = counts.get(course.status, 0) + 1
    split = ", ".join(f"{k} {v}" for k, v in counts.items())
    return f"Registration is open. ASC shows {_plural(n, 'course')}{semester}: {split}."


def _fee_sentence(out: Any) -> str:
    n = len(out.items)
    if n == 0:
        return (
            "ASC shows only a scholarship-payment month picker here, not a fee table. "
            "Check your fee dues on ASC itself."
        )
    due = sum(1 for i in out.items if i.status and any(w in i.status.lower() for w in _DUE_WORDS))
    entries = _plural(n, "fee entry", "fee entries")
    if due == 0:
        return f"ASC shows {entries}; none is due."
    return f"ASC shows {entries}; {due} {'is' if due == 1 else 'are'} due."


def _history_sentence(out: Any) -> str:
    code = out.course_code
    ran: dict[str, list[int]] = {}
    never: list[str] = []
    for sem in dict.fromkeys(o.semester for o in out.offerings):
        years = sorted({o.year for o in out.offerings if o.semester == sem and o.offered})
        if years:
            ran[sem] = years
        else:
            never.append(_SEMESTER_WORD[sem])
    if not ran:
        return f"ASC shows no runs of {code} in the last 3 years."
    parts = [f"{_SEMESTER_WORD[s]} {_join([_year_label(y) for y in ys])}" for s, ys in ran.items()]
    text = f"{code} ran in {', and in '.join(parts)}"
    if never:
        text += f"; not in {' or '.join(never)}"
    return text + "."


def asc_sentence(tool_name: str, args: Any, out: Any) -> str:
    """One template sentence per ASC tool (CONTRACT §11.8). No model writes it."""
    if tool_name == "asc_my_timetable":
        return _timetable_sentence(args, out)
    if tool_name == "asc_my_current_courses":
        n = len(out.courses)
        where = f"for {out.semester}" if out.semester else "for this semester"
        return (
            f"ASC shows {_plural(n, 'course')} {where}." if n else "ASC shows no current courses."
        )
    if tool_name == "asc_registration_status":
        return _registration_sentence(out)
    if tool_name == "asc_fee_status":
        return _fee_sentence(out)
    if tool_name == "asc_profile":
        return "Here is your ASC profile."
    if tool_name == "asc_offered_courses":
        where = f"{_SEMESTER_WORD[out.semester]} {_year_label(out.year)}"
        if not out.courses:
            return f"ASC lists no {out.dept.upper()} courses running in {where}."
        count = _plural(len(out.courses), f"{out.dept.upper()} course")
        return f"ASC lists {count} running in {where}."
    if tool_name == "asc_course_offering_history":
        return _history_sentence(out)
    code = out.detail.code if out.detail else args.course_code.upper()
    if out.detail is None:
        return f"ASC has no details for {code}."
    return f"Here are the ASC details for {code}."


_DEMO = {
    "search_my_mail": "mails",
    "list_recent_mail": "mails",
    "get_upcoming_institute_events": "events",
    "asc_profile": "ASC data",
    "asc_my_timetable": "timetable entries",
    "asc_my_current_courses": "courses",
    "asc_registration_status": "courses",
    "asc_fee_status": "fee entries",
    "asc_offered_courses": "courses",
    "asc_course_offering_history": "course runs",
    "asc_course_details": "course details",
}


def personal_sentence(tool_name: str, args: Any, output: Any) -> str:
    """The answer sentence for one Webmail or ASC tool result (plus its note and demo label)."""
    if tool_name == "search_my_mail":
        text = mail_search_sentence(args, output)
    elif tool_name == "list_recent_mail":
        text = recent_mail_sentence(args, output)
    elif tool_name == "get_upcoming_institute_events":
        text = events_sentence(args, output)
    else:
        text = asc_sentence(tool_name, args, output)
    parts = [text]
    if output.note:
        parts.append(output.note)
    if output.demo:
        parts.append(f"These are demo {_DEMO[tool_name]}.")
    return " ".join(parts)
