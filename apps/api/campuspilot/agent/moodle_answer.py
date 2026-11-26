"""Template sentences for Moodle results (CONTRACT §10.4).

Our code writes these, not the model, so the student's Moodle data never has to be sent to
an LLM. The data itself reaches the UI as `sources` cards.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from campuspilot.schemas.tools import (
    GetCourseContentsOutput,
    GetMyDeadlinesInput,
    GetMyDeadlinesOutput,
    ListMyCoursesOutput,
)

DEMO_NOTE = "These are demo {what}."


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def time_until(due: datetime, now: datetime) -> str:
    """'due in 20 hours', 'due in 3 days', 'overdue'."""
    seconds = int((due - now).total_seconds())
    if seconds < 0:
        return "already past due"
    if seconds < 3600:
        return f"due in {_plural(max(seconds // 60, 1), 'minute')}"
    if seconds < 2 * 86400:
        return f"due in {_plural(seconds // 3600, 'hour')}"
    return f"due in {_plural(seconds // 86400, 'day')}"


def deadlines_sentence(args: GetMyDeadlinesInput, out: GetMyDeadlinesOutput, now: datetime) -> str:
    scope = f" for {args.course_code}" if args.course_code else ""
    window = f"in the next {_plural(args.days_ahead, 'day')}"
    if not out.deadlines:
        return f"I found no deadlines{scope} {window}."
    first = out.deadlines[0]
    return (
        f"You have {_plural(len(out.deadlines), 'deadline')}{scope} {window}. "
        f"The nearest is {first.course} {first.title}, {time_until(first.due_at, now)}."
    )


def courses_sentence(out: ListMyCoursesOutput) -> str:
    if not out.courses:
        return "I found no courses on your Moodle."
    return f"You are enrolled in {_plural(len(out.courses), 'course')}."


def contents_sentence(out: GetCourseContentsOutput) -> str:
    if out.course is None:
        return "I couldn't find that course on your Moodle."
    count = sum(len(s.resources) for s in out.sections)
    return f"{out.course.short_name} has {_plural(count, 'resource')} listed."


def moodle_sentence(tool_name: str, args: Any, output: Any, now: datetime) -> str:
    """The answer sentence for one Moodle tool result (plus its note and the demo label)."""
    if tool_name == "get_my_deadlines":
        text, what = deadlines_sentence(args, output, now), "deadlines"
    elif tool_name == "list_my_courses":
        text, what = courses_sentence(output), "courses"
    else:
        text, what = contents_sentence(output), "course contents"
    parts = [text]
    if output.note:
        parts.append(output.note)
    if output.demo:
        parts.append(DEMO_NOTE.format(what=what))
    return " ".join(parts)
