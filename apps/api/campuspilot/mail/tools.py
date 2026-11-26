"""The two tools the chat model may call, plus login / logout / status.

Everything here is read-only. The outputs are `MailMessage` / `DetectedEvent` cards: the chat
model never sees their content (CONTRACT §11.4), and nothing is written anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from campuspilot.config import Settings, get_settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.llm.base import LLMClient
from campuspilot.llm.personal import personal_data_llm
from campuspilot.mail import credentials, demo, imap_client
from campuspilot.mail.events import IST, detect_event
from campuspilot.mail.extract import refine_event
from campuspilot.mail.imap_client import ScanResult, matches_query
from campuspilot.mail.summary import summarise
from campuspilot.schemas.connectors import (
    ConnectorLoginRequest,
    ConnectorStatus,
    DetectedEvent,
    SearchMyMailInput,
    SearchMyMailOutput,
    UpcomingEventsInput,
    UpcomingEventsOutput,
)

MAX_RESULTS = 20  # SearchMyMailOutput allows at most 20 messages
EVENT_SCAN_DAYS = 14  # how far back we read mail when looking for events
MAX_MODEL_CALLS = 12  # at most this many mails go to the local model per question

NOTE_RULES_ONLY = "Found with simple rules; the local model is offline."
NOTE_NO_SUMMARY = "No summary: the local model is offline."
NOTE_DEMO = "Demo data: made-up mails, not your inbox."

# The last live problem, so Settings can show "error" without hitting the network on every
# status poll. Kept in memory only and holds a fixed friendly message, never mail text.
_last_error: str | None = None


def _record(exc: ConnectorError | None) -> None:
    global _last_error
    _last_error = exc.message if exc and exc.code != "not_connected" else None


async def _model(settings: Settings) -> LLMClient | None:
    """The local model, or None when there is none (mock counts as none: it cannot read mail)."""
    try:
        client = await personal_data_llm(settings)
    except Exception:  # a broken model setup must never break mail search
        return None
    return client if client is not None and client.mode != "mock" else None


async def _scan(
    settings: Settings, *, days: int, query: str | None = None
) -> tuple[ScanResult, bool]:
    """(mails newest first, is_demo)."""
    if settings.connectors_demo:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        mails = [m for m in demo.demo_mails() if m.message.date >= cutoff]
        if query:
            mails = [m for m in mails if matches_query(m, query)]
        return ScanResult(mails=mails, scanned=len(mails)), True
    creds = credentials.require()
    try:
        result = await imap_client.scan_mail(
            settings, creds.username, creds.password, days=days, query=query
        )
    except ConnectorError as exc:
        _record(exc)
        raise
    _record(None)
    return result, False


async def search_my_mail(args: SearchMyMailInput) -> SearchMyMailOutput:
    settings = get_settings()
    result, is_demo = await _scan(settings, days=args.days, query=args.query)
    found = result.mails[:MAX_RESULTS]
    summary, note = None, NOTE_DEMO if is_demo else ""
    if args.summarize and found:
        llm = await _model(settings)
        summary = await summarise(llm, found) if llm else None
        if summary is None:
            note = (note + " " + NOTE_NO_SUMMARY).strip()
    return SearchMyMailOutput(
        messages=[m.message for m in found],
        summary=summary,
        scanned=result.scanned,
        demo=is_demo,
        note=note,
    )


def _in_window(event: DetectedEvent, now: datetime, until: datetime) -> bool:
    if event.start is None:
        return False
    if event.all_day:  # an all-day event today is still upcoming
        return now.astimezone(IST).date() <= event.start.astimezone(IST).date() <= until.date()
    return now <= event.start <= until


def _sorted(events: list[DetectedEvent]) -> list[DetectedEvent]:
    """By start time; date-uncertain items last, newest mail first among them."""
    dated = sorted((e for e in events if e.start is not None), key=lambda e: e.start)  # type: ignore[arg-type,return-value]
    unclear = sorted(
        (e for e in events if e.start is None),
        key=lambda e: e.mail_date or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return dated + unclear


async def get_upcoming_institute_events(args: UpcomingEventsInput) -> UpcomingEventsOutput:
    settings = get_settings()
    result, is_demo = await _scan(settings, days=EVENT_SCAN_DAYS)
    llm = None if is_demo else await _model(settings)  # the demo stays deterministic
    now = datetime.now(IST)
    until = now + timedelta(days=args.days)

    events: list[DetectedEvent] = []
    model_used = False
    model_calls = 0
    for mail in result.mails:
        event = detect_event(mail)
        if event is None:
            continue
        if llm is not None and model_calls < MAX_MODEL_CALLS:
            model_calls += 1
            refined, used = await refine_event(llm, event, mail)
            model_used = model_used or used
            event = refined
        if event is None:
            continue
        if event.start is None or _in_window(event, now, until):
            events.append(event)

    if args.only_deadlines:
        events = [e for e in events if e.category == "deadline"]
    events = _sorted(events)

    if is_demo:
        note = NOTE_DEMO
    elif model_used:
        note = ""
    else:
        note = NOTE_RULES_ONLY
    return UpcomingEventsOutput(
        events=events, scanned=result.scanned, used_model=model_used, demo=is_demo, note=note
    )


# ---------- status, login, logout ----------


async def mail_status() -> ConnectorStatus:
    settings = get_settings()
    if settings.connectors_demo:
        return ConnectorStatus(
            name="webmail", enabled=True, state="connected", account="demo", demo=True,
            message=NOTE_DEMO,
        )  # fmt: skip
    username = credentials.saved_username()
    if credentials.load() is None:
        return ConnectorStatus(name="webmail", enabled=True, state="not_connected")
    if _last_error:
        return ConnectorStatus(
            name="webmail", enabled=True, state="error", account=username, message=_last_error
        )
    return ConnectorStatus(name="webmail", enabled=True, state="connected", account=username)


async def mail_login(req: ConnectorLoginRequest) -> ConnectorStatus:
    """Try a real IMAP LOGIN (then log out). Store the login only if it worked."""
    settings = get_settings()
    if settings.connectors_demo:
        return await mail_status()  # nothing to log in to; never store anything in demo mode
    username = credentials.normalise_username(req.username)
    try:
        await imap_client.check_login(settings, username, req.password)
    except ConnectorError as exc:
        _record(exc if exc.code != "auth_failed" else None)
        raise
    credentials.save(username, req.password)
    _record(None)
    return ConnectorStatus(name="webmail", enabled=True, state="connected", account=username)


def mail_logout() -> ConnectorStatus:
    credentials.delete()
    _record(None)
    return ConnectorStatus(name="webmail", enabled=True, state="not_connected")
