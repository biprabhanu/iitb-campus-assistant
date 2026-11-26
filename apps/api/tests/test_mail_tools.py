"""The Webmail tools, login/logout/status, the model-assisted path, and demo mode."""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime, timedelta

import pytest

from campuspilot.config import get_settings
from campuspilot.connectors.errors import ConnectorError
from campuspilot.llm.mock import MockLLM
from campuspilot.mail import (
    credentials,
    get_upcoming_institute_events,
    imap_client,
    mail_login,
    mail_logout,
    mail_status,
    search_my_mail,
)
from campuspilot.mail.events import IST, detect_event
from campuspilot.mail.extract import merge, parse_reply
from campuspilot.mail.parsing import parse_message
from campuspilot.schemas.connectors import (
    ConnectorLoginRequest,
    SearchMyMailInput,
    UpcomingEventsInput,
    event_key,
)
from tests.mail_helpers import (
    FRIEND,
    FakeImap,
    ScriptedLLM,
    day_text,
    install_fake_imap,
    make_eml,
    use_llm,
)

LOGIN = ConnectorLoginRequest(username="user", password="secret-pw")


def connect(monkeypatch, mails: list[bytes]) -> FakeImap:
    """A fake server holding `mails` and a saved login, as after a successful Settings login."""
    server = FakeImap({i: raw for i, raw in enumerate(mails, start=1)})
    install_fake_imap(monkeypatch, server)
    credentials.save("user", "secret-pw")
    return server


def event_mails() -> list[bytes]:
    return [
        make_eml("Guest Talk: Robots", f"On {day_text(2)}, 4:30-6 PM. Venue: LH 101"),
        make_eml(
            "Last date for course drop",
            f"Deadline: {day_text(3)}.",
            sender="Acad <acad-office@example.org>",
        ),
        make_eml("Workshop far away", f"Held on {day_text(20)} at 10 AM in VMCC."),
        make_eml("Old seminar", f"It was on {day_text(-5)} at 10 AM in VMCC."),
        make_eml(
            "Fest volunteers needed",
            "Schedule will be announced later.",
            sender="Fest <gymkhana-fest@example.org>",
        ),
        make_eml("Lunch?", f"Free on {day_text(2)}?", sender=FRIEND),
    ]


# ---------- credentials, status, login, logout ----------


async def test_tools_need_a_saved_login() -> None:
    for call in (
        search_my_mail(SearchMyMailInput(query="x")),
        get_upcoming_institute_events(UpcomingEventsInput()),
    ):
        with pytest.raises(ConnectorError) as info:
            await call
        assert info.value.code == "not_connected"
        assert info.value.message == "Connect IITB Webmail in Settings first."


async def test_login_stores_only_after_success_then_logout_deletes(
    monkeypatch, memory_keyring
) -> None:
    server = FakeImap()
    install_fake_imap(monkeypatch, server)
    assert (await mail_status()).state == "not_connected"

    status = await mail_login(LOGIN)
    assert (status.name, status.state, status.account) == ("webmail", "connected", "user")
    assert "secret-pw" not in status.model_dump_json()
    assert set(k[1] for k in memory_keyring.store) == {"webmail_username", "webmail_password"}
    assert [c[0] for c in server.commands] == ["LOGIN", "LOGOUT"]
    assert (await mail_status()).account == "user"

    assert mail_logout().state == "not_connected"
    assert memory_keyring.store == {}
    assert (await mail_status()).state == "not_connected"


async def test_wrong_password_is_not_stored(monkeypatch, memory_keyring) -> None:
    install_fake_imap(monkeypatch, FakeImap())
    with pytest.raises(ConnectorError) as info:
        await mail_login(ConnectorLoginRequest(username="user", password="nope"))
    assert info.value.code == "auth_failed"
    assert memory_keyring.store == {}
    assert (await mail_status()).state == "not_connected"


async def test_unreachable_server_is_not_stored_and_mentions_the_vpn(
    monkeypatch, memory_keyring
) -> None:
    def boom(*_a, **_k):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(imap_client, "IMAP4_SSL", boom)
    with pytest.raises(ConnectorError) as info:
        await mail_login(LOGIN)
    assert info.value.code == "unreachable" and "VPN" in info.value.message
    assert memory_keyring.store == {}


async def test_login_timeout_code(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise TimeoutError

    monkeypatch.setattr(imap_client, "IMAP4_SSL", boom)
    with pytest.raises(ConnectorError) as info:
        await mail_login(LOGIN)
    assert info.value.code == "timeout"


async def test_status_shows_error_after_a_failed_read_and_recovers(monkeypatch) -> None:
    server = connect(monkeypatch, event_mails())
    server.login_error = imaplib_error()
    with pytest.raises(ConnectorError):
        await search_my_mail(SearchMyMailInput(query="talk"))
    status = await mail_status()
    assert status.state == "error" and status.account == "user" and status.message
    server.login_error = None
    await search_my_mail(SearchMyMailInput(query="talk"))
    assert (await mail_status()).state == "connected"


def imaplib_error() -> Exception:
    import imaplib

    return imaplib.IMAP4.error("AUTHENTICATIONFAILED")


# ---------- search_my_mail ----------


async def test_search_returns_newest_first_at_most_20(monkeypatch) -> None:
    base = datetime.now(UTC)
    mails = [
        make_eml(f"Project update {i}", "status", date=base - timedelta(minutes=i))
        for i in range(25)
    ]
    connect(monkeypatch, mails)
    out = await search_my_mail(SearchMyMailInput(query="project update"))
    assert len(out.messages) == 20 and out.scanned == 25 and not out.demo
    dates = [m.date for m in out.messages]
    assert dates == sorted(dates, reverse=True)
    assert out.summary is None and out.note == ""
    assert all(len(m.snippet) <= 300 for m in out.messages)


async def test_summary_only_when_asked_and_from_the_local_model(monkeypatch) -> None:
    connect(monkeypatch, [make_eml("Hackathon news", "Teams of four. Register soon.")])
    llm = ScriptedLLM("word " * 300)
    use_llm(monkeypatch, llm)

    plain = await search_my_mail(SearchMyMailInput(query="hackathon"))
    assert plain.summary is None and llm.calls == []  # not asked: the model is not even called

    out = await search_my_mail(SearchMyMailInput(query="hackathon", summarize=True))
    assert out.summary is not None and len(out.summary.split()) <= 121
    (messages, tools) = llm.calls[0]
    assert tools is None  # no tools for the summary call
    assert "<mail>" in messages[1]["content"] and "UNTRUSTED" in messages[0]["content"]


@pytest.mark.parametrize("model", [None, MockLLM()])
async def test_summary_without_a_real_model_is_none_with_a_note(monkeypatch, model) -> None:
    connect(monkeypatch, [make_eml("Hackathon news", "Teams of four.")])
    use_llm(monkeypatch, model)
    out = await search_my_mail(SearchMyMailInput(query="hackathon", summarize=True))
    assert out.summary is None and "offline" in out.note and len(out.messages) == 1


async def test_summary_model_error_gives_a_note_not_a_crash(monkeypatch) -> None:
    connect(monkeypatch, [make_eml("Hackathon news", "Teams of four.")])
    use_llm(monkeypatch, ScriptedLLM(error=RuntimeError("boom")))
    out = await search_my_mail(SearchMyMailInput(query="hackathon", summarize=True))
    assert out.summary is None and out.note and len(out.messages) == 1


# ---------- get_upcoming_institute_events ----------


async def test_events_rules_only(monkeypatch) -> None:
    connect(monkeypatch, event_mails())
    use_llm(monkeypatch, None)
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=7))
    titles = [e.title for e in out.events]
    # In window and sorted by start; the unclear institute item last; far / past / personal out.
    assert titles == ["Guest Talk: Robots", "Last date for course drop", "Fest volunteers needed"]
    assert out.events[-1].date_uncertain and out.events[-1].start is None
    starts = [e.start for e in out.events[:-1]]
    assert starts == sorted(starts)
    assert out.used_model is False and "local model is offline" in out.note
    assert out.scanned == 6 and not out.demo
    for e in out.events:
        assert e.id == event_key(e.message_id, e.start) and e.detected_by == "rules"


async def test_all_day_event_today_still_counts(monkeypatch) -> None:
    connect(monkeypatch, [make_eml("Last date to submit", f"Deadline {day_text(0)}.")])
    use_llm(monkeypatch, None)
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=1))
    assert [e.category for e in out.events] == ["deadline"]


async def test_only_deadlines(monkeypatch) -> None:
    connect(monkeypatch, event_mails())
    use_llm(monkeypatch, None)
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=7, only_deadlines=True))
    assert {e.category for e in out.events} == {"deadline"} and len(out.events) == 1


async def test_longer_window_includes_the_far_event(monkeypatch) -> None:
    connect(monkeypatch, event_mails())
    use_llm(monkeypatch, None)
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=30))
    assert "Workshop far away" in [e.title for e in out.events]


def _good_json(**over) -> str:
    base = {"is_event": True, "title": "Robots talk", "category": "talk", "date_text": None,
            "start_date": None, "time_text": None, "start_time": None, "end_time": None,
            "venue": "LH 101", "confidence": 0.9}  # fmt: skip
    return json.dumps({**base, **over})


async def test_model_fills_fields_with_one_tool_less_call_per_mail(monkeypatch) -> None:
    connect(
        monkeypatch, [make_eml("Guest Talk: Robots", f"On {day_text(2)}. LH 101 is the venue.")]
    )
    llm = ScriptedLLM("```json\n" + _good_json() + "\n```")
    use_llm(monkeypatch, llm)
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=7))
    assert out.used_model and out.note == ""
    (event,) = out.events
    assert event.detected_by == "rules+llm" and event.title == "Robots talk"
    assert len(llm.calls) == 1 and llm.calls[0][1] is None


@pytest.mark.parametrize(
    "llm",
    [
        ScriptedLLM("sorry, I cannot help"),  # not JSON
        ScriptedLLM('{"is_event": "maybe", "confidence": 7}'),  # fails validation
        ScriptedLLM(error=TimeoutError()),  # model unreachable
        MockLLM(),  # the scripted mock never reads mail
        None,
    ],
)
async def test_bad_or_missing_model_means_rules_only(monkeypatch, llm) -> None:
    connect(monkeypatch, [make_eml("Guest Talk: Robots", f"On {day_text(2)}, 5 PM in LH 101")])
    use_llm(monkeypatch, llm)
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=7))
    assert out.used_model is False and out.note
    (event,) = out.events
    assert event.detected_by == "rules" and event.venue == "LH 101"


def test_a_model_date_is_kept_only_when_the_mail_text_supports_it() -> None:
    mail = parse_message(
        make_eml(
            "Annual fest", "Register by 5 Dec 2026, 6 pm.", date=datetime(2026, 11, 27, tzinfo=UTC)
        ),
        uid="1",
    )
    rules = detect_event(mail).model_copy(  # pretend the rules had missed the date
        update={"start": None, "date_uncertain": True, "date_text": "", "all_day": False}
    )
    ok = merge(
        rules, parse_reply(_good_json(date_text="5 Dec 2026", start_date="2026-12-05")), mail
    )
    assert ok.start == datetime(2026, 12, 5, 0, 0, tzinfo=IST) and not ok.date_uncertain
    assert ok.date_text == "5 Dec 2026" and ok.detected_by == "rules+llm"

    # (a) the phrase is not in the mail, (b) it is, but it does not mean that date
    for bad in (
        _good_json(date_text="next Tuesday", start_date="2026-12-01"),
        _good_json(date_text="5 Dec 2026", start_date="2026-12-25"),
        _good_json(date_text=None, start_date="2026-12-05"),
    ):
        merged = merge(rules, parse_reply(bad), mail)
        assert merged.start is None and merged.date_uncertain


async def test_model_cannot_invent_a_date_for_an_undated_mail(monkeypatch) -> None:
    connect(
        monkeypatch,
        [make_eml("Fest volunteers", "Schedule later.", sender="F <gymkhana-fest@example.org>")],
    )
    use_llm(
        monkeypatch, ScriptedLLM(_good_json(date_text="tomorrow evening", start_date="2026-12-01"))
    )
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=7))
    (event,) = out.events
    assert event.start is None and event.date_uncertain and event.date_text == ""


async def test_model_saying_not_an_event_drops_an_undated_guess(monkeypatch) -> None:
    connect(
        monkeypatch,
        [make_eml("Fest volunteers", "Schedule later.", sender="F <gymkhana-fest@example.org>")],
    )
    use_llm(monkeypatch, ScriptedLLM(_good_json(is_event=False)))
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=7))
    assert out.events == []


def test_model_venue_must_appear_in_the_mail() -> None:
    mail = parse_message(make_eml("Seminar", "On 2 Dec 2026 at 4 PM."), uid="1")
    rules = detect_event(mail)
    assert merge(rules, parse_reply(_good_json(venue="Moon Base")), mail).venue is None
    assert merge(rules, parse_reply(_good_json(venue="4 PM")), mail).venue == "4 PM"


# ---------- demo mode ----------


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setenv("CONNECTORS_DEMO", "true")
    get_settings.cache_clear()

    def no_network(*_a, **_k):
        raise AssertionError("demo mode must not open an IMAP connection")

    monkeypatch.setattr(imap_client, "IMAP4_SSL", no_network)


async def test_demo_status_and_login(demo_on, memory_keyring) -> None:
    status = await mail_status()
    assert status.demo and status.state == "connected" and status.account == "demo"
    await mail_login(LOGIN)
    assert memory_keyring.store == {}  # nothing is stored in demo mode


async def test_demo_search(demo_on) -> None:
    out = await search_my_mail(SearchMyMailInput(query="hackathon"))
    assert out.demo and [m.subject for m in out.messages][0].startswith("Hackathon")
    assert "Demo data" in out.note
    everything = await search_my_mail(SearchMyMailInput(query="the"))
    dates = [m.date for m in everything.messages]
    assert dates == sorted(dates, reverse=True)


async def test_demo_events_are_in_the_coming_days_and_labelled(demo_on) -> None:
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=7))
    assert out.demo and not out.used_model and "Demo data" in out.note
    now = datetime.now(IST)
    dated = [e for e in out.events if e.start]
    assert len(dated) >= 4
    assert all(now - timedelta(days=1) <= e.start <= now + timedelta(days=8) for e in dated)
    assert [e.start for e in dated] == sorted(e.start for e in dated)
    assert out.events[-1].date_uncertain  # the fest mail has no date and sits last
    assert {"talk", "workshop", "deadline", "exam"} <= {e.category for e in out.events}
    assert "Lunch on Sunday?" not in [e.title for e in out.events]


async def test_demo_only_deadlines(demo_on) -> None:
    out = await get_upcoming_institute_events(UpcomingEventsInput(days=7, only_deadlines=True))
    assert out.events and {e.category for e in out.events} == {"deadline"}
