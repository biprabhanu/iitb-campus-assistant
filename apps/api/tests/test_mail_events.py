"""Rule-based event detection: dates, times, venues, senders, and what is NOT an event."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from campuspilot.mail.events import (
    IST,
    categorise,
    detect_event,
    find_dates,
    find_times,
    find_venue,
    is_institute_sender,
)
from campuspilot.mail.parsing import parse_message
from tests.mail_helpers import FRIEND, make_eml

REF = date(2026, 11, 27)  # a Friday


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("on 2nd Dec at the hall", date(2026, 12, 2)),
        ("Dec 2, 2026", date(2026, 12, 2)),
        ("December 2", date(2026, 12, 2)),
        ("02/12/2026", date(2026, 12, 2)),  # day first, Indian style
        ("2-12-26", date(2026, 12, 2)),
        ("Tuesday, 2 December", date(2026, 12, 2)),
        ("3rd of January 2027", date(2027, 1, 3)),
        ("tomorrow", date(2026, 11, 28)),
        ("day after tomorrow", date(2026, 11, 29)),
        ("today", REF),
        ("on Monday", date(2026, 11, 30)),
        ("this Friday", date(2026, 12, 4)),  # the mail was sent on a Friday: next one
    ],
)
def test_find_dates(text: str, expected: date) -> None:
    hits = find_dates(text, REF)
    assert hits and hits[0].day == expected


def test_a_date_without_a_year_rolls_into_next_year_when_it_is_long_past() -> None:
    assert find_dates("5 Jan", date(2026, 12, 20))[0].day == date(2027, 1, 5)


@pytest.mark.parametrize("text", ["31 Feb", "32/13/2026", "no date here", "room 2 on level 3"])
def test_impossible_or_missing_dates_are_not_dates(text: str) -> None:
    assert find_dates(text, REF) == []


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("at 4 PM", time(16, 0), None),
        ("at 4:15 p.m.", time(16, 15), None),
        ("at 16:00 hrs", time(16, 0), None),
        ("4:30-6 pm", time(16, 30), time(18, 0)),
        ("4 to 6 PM", time(16, 0), time(18, 0)),
        ("11-1 pm", time(11, 0), time(13, 0)),  # 11 am to 1 pm, not 11 pm
        ("9:30 AM - 11 AM", time(9, 30), time(11, 0)),
        ("12 am", time(0, 0), None),
    ],
)
def test_find_times(text: str, start: time, end: time | None) -> None:
    hits = find_times(text)
    assert hits and (hits[0].start, hits[0].end) == (start, end)


def test_no_times_in_plain_numbers() -> None:
    assert find_times("room 101, 25 students, 2026") == []


@pytest.mark.parametrize(
    ("text", "venue"),
    [
        ("held in LH 101 tonight", "LH 101"),
        ("LT-2", "LT-2"),
        ("at VMCC", "VMCC"),
        ("in KReSIT seminar hall", "KReSIT"),
        ("at the Convocation Hall", "Convocation Hall"),
        ("meet in Room 101", "Room 101"),
        ("Venue: Main Auditorium, near gate 2.", "Main Auditorium, near gate 2"),
    ],
)
def test_find_venue(text: str, venue: str) -> None:
    assert find_venue(text) == venue


def test_no_venue() -> None:
    assert find_venue("see you soon") is None


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("someone@lists.iitb.ac.in", True),
        ("x@iitb.ac.in", True),
        ("gymkhana-events@example.org", True),
        ("dean_acad@example.org", True),
        ("placement.cell@example.org", True),
        ("friend@example.com", False),
        ("academy@example.com", False),
        ("x@notiitb.ac.in", False),
    ],
)
def test_institute_senders(email: str, expected: bool) -> None:
    assert is_institute_sender(email) is expected


@pytest.mark.parametrize(
    ("subject", "category"),
    [
        ("Last date to submit the form", "deadline"),
        ("Quiz 2 schedule", "exam"),
        ("Workshop on Git", "workshop"),
        ("Guest talk on AI", "talk"),
        ("Fest volunteers", "fest"),
        ("Hello there", "other"),
    ],
)
def test_category(subject: str, category: str) -> None:
    assert categorise(subject, "") == category


def _mail(subject: str, body: str, sender: str | None = None, when: datetime | None = None):
    kwargs = {"date": when or datetime(2026, 11, 27, 9, 0, tzinfo=UTC)}
    if sender:
        kwargs["sender"] = sender
    return parse_message(make_eml(subject, body, **kwargs), uid="1")


def test_dated_event_with_time_and_venue() -> None:
    mail = _mail("Guest Talk: Robots", "Date: 2 December 2026\nTime: 4:30-6 PM\nVenue: LH 101")
    event = detect_event(mail)
    assert event is not None
    assert event.start == datetime(2026, 12, 2, 16, 30, tzinfo=IST)
    assert event.end == datetime(2026, 12, 2, 18, 0, tzinfo=IST)
    assert (event.category, event.venue, event.all_day) == ("talk", "LH 101", False)
    assert not event.date_uncertain
    assert event.detected_by == "rules"
    assert event.date_text == "2 December 2026"
    assert event.message_id == mail.message.message_id
    assert event.organizer == "Gymkhana Events"
    assert 0.0 <= event.confidence <= 1.0


def test_date_without_a_time_is_all_day() -> None:
    event = detect_event(_mail("Last date for course drop", "Deadline is 02/12/2026."))
    assert event is not None and event.all_day and event.category == "deadline"
    assert event.start == datetime(2026, 12, 2, 0, 0, tzinfo=IST)


def test_tomorrow_is_relative_to_the_mails_own_date() -> None:
    mail = _mail(
        "Pre-placement talk tomorrow", "At 4 PM in SOM.", when=datetime(2026, 11, 20, tzinfo=UTC)
    )
    event = detect_event(mail)
    assert event is not None
    assert event.start == datetime(2026, 11, 21, 16, 0, tzinfo=IST)


def test_institute_mail_without_a_clear_date_is_uncertain_not_invented() -> None:
    event = detect_event(_mail("Fest volunteers needed", "The schedule will be announced later."))
    assert event is not None
    assert event.start is None and event.date_uncertain and event.date_text == ""
    assert event.confidence < 0.5


def test_non_institute_mail_without_a_date_is_not_an_event() -> None:
    assert detect_event(_mail("Fest volunteers needed", "Schedule later.", sender=FRIEND)) is None


def test_ordinary_mail_is_not_an_event() -> None:
    assert detect_event(_mail("Lunch?", "Are you free on 2 December?", sender=FRIEND)) is None


def test_html_mail_is_read_as_text() -> None:
    raw = make_eml("Workshop on Git", "<p>On <b>3 Dec</b> at <i>10 AM</i></p>", html=True)
    event = detect_event(parse_message(raw, uid="1"))
    assert event is not None and event.start == datetime(2026, 12, 3, 10, 0, tzinfo=IST)


def test_one_mail_gives_one_event_even_with_many_dates() -> None:
    body = "Talks on 2 Dec, 3 Dec, 4 Dec, 5 Dec and 6 Dec."
    mail = _mail("Seminar series", body)
    assert detect_event(mail) is not None  # a single event, not five
