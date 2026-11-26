"""v2 connector models: Webmail, ASC and Google Calendar (docs/CONTRACT.md §11).

Local mode only. Webmail and ASC are read-only; the one write in the whole app is a Google
Calendar event the student clicked "Add" on (`POST /v1/calendar/events`), which is never a
tool the model can call.

Privacy rules these models are designed around:
- Mail bodies, ASC pages and grades never leave the API except as these card fields, and are
  never logged. The chat model only learns how many items a tool found (like Moodle, §10.4).
- Nothing here carries a password, OTP, session cookie or OAuth token.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConnectorName = Literal["webmail", "asc", "gcal"]
# disabled      = the *_ENABLED flag is off (or hosted mode); the UI explains how to turn it on
# not_connected = enabled, but no credentials saved yet
# needs_otp     = a login is waiting for the one-time code the student types in the UI
# connected     = credentials saved and the last check worked
# error         = credentials saved but the last check failed (see `message`)
ConnectorState = Literal["disabled", "not_connected", "needs_otp", "connected", "error"]
# The label every card shows, so the student always knows where an item came from.
SourceLabel = Literal["Webmail", "ASC", "Moodle", "Official page"]


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- connector status and login (Settings UI) ----------


class ConnectorStatus(BaseModel):
    name: ConnectorName
    enabled: bool
    state: ConnectorState
    # The account the student connected (an LDAP id or Google email), shown in Settings so they
    # know which account is linked. Never a password or token.
    account: str | None = None
    message: str | None = None  # friendly text for "error" / "needs_otp"
    challenge_id: str | None = None  # set with state="needs_otp"; send back with the code
    demo: bool = False  # CONNECTORS_DEMO=true: fixture data, labelled "Demo data" in the UI


class ConnectorsResponse(BaseModel):
    """GET /v1/connectors (local only)."""

    webmail: ConnectorStatus
    asc: ConnectorStatus
    gcal: ConnectorStatus


class ConnectorLoginRequest(_StrictInput):
    """POST /v1/connectors/{webmail|asc}/login. Stored in the macOS Keychain after a
    successful check; never echoed, logged or put in an error message."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200, repr=False)


class ConnectorOtpRequest(_StrictInput):
    """POST /v1/connectors/asc/otp: the code the student typed for a pending login."""

    challenge_id: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=4, max_length=12, pattern=r"^[0-9A-Za-z]+$", repr=False)


class GcalConnectStart(BaseModel):
    """POST /v1/connectors/gcal/connect: open `auth_url` in the browser. Google then redirects
    to the API's loopback callback (`GET /v1/connectors/gcal/callback`)."""

    auth_url: str


# ---------- Webmail ----------


class MailMessage(BaseModel):
    """One mail, as a card. Never the full body (only a short snippet)."""

    uid: str  # IMAP UID inside `folder`
    folder: str = "INBOX"
    message_id: str  # the RFC 5322 Message-ID header; the stable id used everywhere else
    sender_name: str = ""
    sender_email: str = ""
    subject: str = ""
    date: datetime  # timezone-aware
    snippet: str = Field(default="", max_length=300)
    has_attachments: bool = False
    # A link that opens the mail in IITB webmail, when the mail module can build one.
    open_url: str | None = None


EventCategory = Literal["talk", "workshop", "fest", "deadline", "exam", "other"]


def event_key(message_id: str, start: datetime | None) -> str:
    """Stable id for a detected event: hash of the source mail and the start time.

    The same value is stored in the Google event's `extendedProperties.private` so that a
    second click finds the first event instead of creating a duplicate."""
    raw = f"{message_id}|{start.isoformat() if start else 'no-date'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class DetectedEvent(BaseModel):
    """An institute event (or deadline) found in the student's mail. A *suggestion* only."""

    id: str  # event_key(message_id, start)
    message_id: str
    title: str = Field(max_length=200)
    category: EventCategory = "other"
    start: datetime | None = None  # None when the date is unclear; never invented
    end: datetime | None = None
    all_day: bool = False
    # True when the rules and the model could not pin the date down; the card says so and the
    # Add button is disabled.
    date_uncertain: bool = False
    date_text: str = Field(default="", max_length=200)  # the phrase the date came from
    venue: str | None = Field(default=None, max_length=200)
    organizer: str | None = Field(default=None, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    detected_by: Literal["rules", "rules+llm"] = "rules"
    # The source mail, so the card can show and link it:
    mail_subject: str = ""
    mail_sender: str = ""
    mail_date: datetime | None = None
    open_url: str | None = None


class SearchMyMailInput(_StrictInput):
    query: str = Field(min_length=1, max_length=200)
    days: int = Field(default=14, ge=1, le=60)
    # True when the student asked for a summary. The summary is written by the *local* model in
    # a separate call with no tools (see llm/personal.py), never by the chat model.
    summarize: bool = False


class SearchMyMailOutput(BaseModel):
    messages: list[MailMessage] = Field(default_factory=list, max_length=20)  # newest first
    summary: str | None = None
    scanned: int = 0  # how many mails were looked at
    demo: bool = False
    note: str = ""


class ListRecentMailInput(_StrictInput):
    """ "What's my latest mail?" The newest messages, headers and a short snippet only."""

    limit: int = Field(default=10, ge=1, le=20)
    unread_only: bool = False


class ListRecentMailOutput(BaseModel):
    messages: list[MailMessage] = Field(default_factory=list, max_length=20)  # newest first
    unread_only: bool = False
    demo: bool = False
    note: str = ""


class UpcomingEventsInput(_StrictInput):
    days: int = Field(default=7, ge=1, le=30)
    only_deadlines: bool = False  # "what's due" questions: deadlines only


class UpcomingEventsOutput(BaseModel):
    events: list[DetectedEvent] = Field(default_factory=list)  # sorted by start, unclear last
    scanned: int = 0
    used_model: bool = False  # False = rules only (tunnel down or no local model)
    demo: bool = False
    note: str = ""


# ---------- ASC ----------

Weekday = Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class AscCourse(BaseModel):
    code: str  # e.g. "IE 624"
    title: str = ""
    credits: float | None = None
    slot: str | None = None
    instructor: str | None = None
    status: Literal["registered", "approved", "pending", "dropped", "audit", "other"] = "other"
    semester: str = ""  # as ASC writes it, e.g. "2026-27 Autumn"


class AscTimetableSlot(BaseModel):
    course_code: str
    course_title: str = ""
    day: Weekday
    start: str = Field(pattern=r"^\d{2}:\d{2}$")  # "HH:MM", Asia/Kolkata
    end: str = Field(pattern=r"^\d{2}:\d{2}$")
    venue: str | None = None
    slot: str | None = None
    kind: Literal["lecture", "tutorial", "lab", "other"] = "lecture"


class AscGrade(BaseModel):
    """Sensitive. Shown only when the student asks; never logged, never sent to a model."""

    course_code: str
    course_title: str = ""
    credits: float | None = None
    grade: str
    semester: str = ""


class GetMyTimetableInput(_StrictInput):
    when: Literal["today", "tomorrow", "this_week"] = "today"
    on_date: date | None = None  # a specific day; overrides `when`


class AscTimetableOutput(BaseModel):
    slots: list[AscTimetableSlot] = Field(default_factory=list)  # sorted by day then start
    for_dates: list[date] = Field(default_factory=list)  # the days the slots cover
    demo: bool = False
    note: str = ""


class GetMyRegisteredCoursesInput(_StrictInput):
    semester: str | None = Field(default=None, max_length=40)  # None = current semester


class AscCoursesOutput(BaseModel):
    courses: list[AscCourse] = Field(default_factory=list)
    semester: str = ""
    registration_note: str = ""  # e.g. "Registration is open until 4 Dec" if ASC shows it
    demo: bool = False
    note: str = ""


class GetMyGradesInput(_StrictInput):
    semester: str | None = Field(default=None, max_length=40)  # None = all semesters


class AscGradesOutput(BaseModel):
    grades: list[AscGrade] = Field(default_factory=list)
    spi: str | None = None  # as ASC shows them; never computed by us
    cpi: str | None = None
    demo: bool = False
    note: str = ""


# ---------- Google Calendar (the only write; UI click only) ----------


class CalendarEventRequest(_StrictInput):
    """POST /v1/calendar/events, sent by the UI when the student clicks "Add" on an event card."""

    event_id: str = Field(min_length=8, max_length=64)  # DetectedEvent.id
    message_id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)
    start: datetime
    end: datetime | None = None  # None = start + 1 hour (or the whole day when all_day)
    all_day: bool = False
    venue: str | None = Field(default=None, max_length=200)
    mail_subject: str = Field(default="", max_length=300)  # goes in the event description

    @field_validator("start", "end")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("must include a time zone")
        return value


class CalendarEventResult(BaseModel):
    ok: bool
    status: Literal["created", "already_exists", "error"]
    google_event_id: str | None = None
    html_link: str | None = None  # "View in Calendar"
    message: str = ""


# ---------- cards (the `cards` SSE event) ----------


class _Card(BaseModel):
    id: str  # W1.. mail, E1.. events, A1.. ASC; for UI keys only (never cited)
    demo: bool = False


class MailCard(_Card):
    type: Literal["mail"] = "mail"
    source_label: Literal["Webmail"] = "Webmail"
    mail: MailMessage


class EventCard(_Card):
    type: Literal["event"] = "event"
    source_label: Literal["Webmail"] = "Webmail"
    event: DetectedEvent
    # True when Google Calendar is connected and the event has a clear start time.
    can_add_to_calendar: bool = False


class AscSlotCard(_Card):
    type: Literal["asc_slot"] = "asc_slot"
    source_label: Literal["ASC"] = "ASC"
    slot: AscTimetableSlot
    on_date: date | None = None


class AscCourseCard(_Card):
    type: Literal["asc_course"] = "asc_course"
    source_label: Literal["ASC"] = "ASC"
    course: AscCourse


class AscGradeCard(_Card):
    type: Literal["asc_grade"] = "asc_grade"
    source_label: Literal["ASC"] = "ASC"
    grade: AscGrade


Card = Annotated[
    MailCard | EventCard | AscSlotCard | AscCourseCard | AscGradeCard,
    Field(discriminator="type"),
]
