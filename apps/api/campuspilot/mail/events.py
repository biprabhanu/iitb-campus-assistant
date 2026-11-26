"""Rule-based event detection: dates, times, venues and institute senders in a mail.

This runs first and alone is enough to produce useful suggestions. The local model (extract.py)
only fills gaps, and only with facts that these same rules can find in the mail text.

Conventions: dates are read day-first (Indian style: 02/12/2026 is 2 December), times are
Asia/Kolkata, and a date with no time becomes an all-day event. At most ONE event comes out of
one mail, so a mail cannot flood the list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from campuspilot.mail.parsing import ParsedMail, collapse
from campuspilot.schemas.connectors import DetectedEvent, EventCategory, event_key

IST = timezone(timedelta(hours=5, minutes=30), "IST")

# ---- who counts as an institute sender (edit these lists to tune) ----
INSTITUTE_DOMAINS = ("iitb.ac.in",)  # the domain or any subdomain, e.g. lists.iitb.ac.in
INSTITUTE_NAME_WORDS = frozenset(
    {"gymkhana", "acad", "deanacad", "dean", "placement", "placements", "cdc", "ismp", "sac"}
)


def is_institute_sender(email: str) -> bool:
    local, _, domain = email.lower().partition("@")
    if any(domain == d or domain.endswith("." + d) for d in INSTITUTE_DOMAINS):
        return True
    return any(word in INSTITUTE_NAME_WORDS for word in re.split(r"[^a-z0-9]+", local))


# ---- dates ----
_MONTH_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_MONTH = (
    r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_DAY_MONTH = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?{_MONTH}\b\.?(?:,?\s*(?P<year>\d{{4}}))?",
    re.I,
)
_MONTH_DAY = re.compile(
    rf"\b{_MONTH}\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s*(?P<year>\d{{4}}))?", re.I
)
_NUMERIC = re.compile(r"\b(?P<day>\d{1,2})[/.-](?P<month>\d{1,2})[/.-](?P<year>\d{4}|\d{2})\b")
_RELATIVE = re.compile(
    r"\b(?P<rel>day after tomorrow|tomorrow|today|tonight"
    r"|(?:(?:on|this|next|coming)\s+)(?P<wd>monday|tuesday|wednesday|thursday|friday"
    r"|saturday|sunday))\b",
    re.I,
)


@dataclass(frozen=True)
class DateHit:
    day: date
    text: str  # the exact phrase the date came from
    pos: int


def _build_date(day: int, month: int, year: int | None, ref: date) -> date | None:
    """A date with no year takes the mail's year, or the next one if that is long past."""
    try:
        if year is not None:
            return date(year + 2000 if year < 100 else year, month, day)
        candidate = date(ref.year, month, day)
        if candidate < ref - timedelta(days=60):
            candidate = date(ref.year + 1, month, day)
        return candidate
    except ValueError:
        return None  # e.g. 31 Feb: not a date, so not an event


def find_dates(text: str, ref: date) -> list[DateHit]:
    """Every date phrase in the text, in the order it appears. `ref` is the mail's date."""
    hits: list[DateHit] = []

    def add(match: re.Match, day: date | None) -> None:
        if day is not None:
            hits.append(DateHit(day, match.group(0).strip(), match.start()))

    for rx in (_DAY_MONTH, _MONTH_DAY):
        for m in rx.finditer(text):
            year = int(m["year"]) if m["year"] else None
            add(m, _build_date(int(m["day"]), _MONTH_NUM[m["mon"][:3].lower()], year, ref))
    for m in _NUMERIC.finditer(text):
        add(m, _build_date(int(m["day"]), int(m["month"]), int(m["year"]), ref))
    for m in _RELATIVE.finditer(text):
        rel = m["rel"].lower()
        if rel in ("today", "tonight"):
            add(m, ref)
        elif rel == "tomorrow":
            add(m, ref + timedelta(days=1))
        elif rel == "day after tomorrow":
            add(m, ref + timedelta(days=2))
        else:  # "on / this / next Friday": the first such weekday after the mail's date
            target = _WEEKDAYS.index(m["wd"].lower())
            ahead = (target - ref.weekday()) % 7 or 7
            add(m, ref + timedelta(days=ahead))
    return sorted(hits, key=lambda h: h.pos)


# ---- times ----
_RANGE = re.compile(
    r"\b(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*(?P<ap1>[ap]\.?m\.?)?\s*(?:-|–|—|to)\s*"
    r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*(?P<ap2>[ap]\.?m\.?)",
    re.I,
)
_AMPM = re.compile(r"\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>[ap]\.?m\.?)(?!\w)", re.I)
_H24 = re.compile(r"\b(?P<h>[01]?\d|2[0-3])[:.](?P<m>[0-5]\d)\s*(?:hrs|hours|h)?\b", re.I)


@dataclass(frozen=True)
class TimeHit:
    start: time
    end: time | None
    text: str
    pos: int


def _to_24(hour: int, minute: int, meridiem: str | None) -> time | None:
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.lower().startswith("p") else 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def find_times(text: str) -> list[TimeHit]:
    hits: list[TimeHit] = []
    taken: list[tuple[int, int]] = []

    def free(m: re.Match) -> bool:
        return not any(a < m.end() and m.start() < b for a, b in taken)

    for m in _RANGE.finditer(text):
        ap2 = m["ap2"][0].lower()
        ap1 = (m["ap1"] or m["ap2"])[0].lower()
        end = _to_24(int(m["h2"]), int(m["m2"] or 0), ap2 + "m")
        start = _to_24(int(m["h1"]), int(m["m1"] or 0), ap1 + "m")
        if start and end and not m["ap1"] and start >= end:
            # "11-1 pm" means 11 am to 1 pm: the start borrowed the wrong meridiem.
            start = _to_24(int(m["h1"]), int(m["m1"] or 0), "am")
        if start and end:
            hits.append(TimeHit(start, end, m.group(0), m.start()))
            taken.append((m.start(), m.end()))
    for m in _AMPM.finditer(text):
        t = _to_24(int(m["h"]), int(m["m"] or 0), m["ap"][0] + "m")
        if t and free(m):
            hits.append(TimeHit(t, None, m.group(0), m.start()))
            taken.append((m.start(), m.end()))
    for m in _H24.finditer(text):
        t = _to_24(int(m["h"]), int(m["m"]), None)
        if t and free(m):
            hits.append(TimeHit(t, None, m.group(0), m.start()))
    return sorted(hits, key=lambda h: h.pos)


# ---- venues ----
_VENUE_LABEL = re.compile(r"\b(?:venue|location|where)\s*[:\-]\s*(?P<v>[^\n.;]{2,80})", re.I)
_VENUE_CASED = re.compile(
    r"\b(?:(?:LH|LT|LC)[\s-]?\d{1,3}[A-Z]?|VMCC|KReSIT|SOM|SJMSOM|CTARA|IRCC|SAC)\b"
)
_VENUE_WORDS = re.compile(
    r"\b(?:convocation hall|lecture hall complex|main building|gymkhana|auditorium"
    r"|seminar hall|conference room|room\s*no?\.?\s*\d{1,4}[A-Z]?|room\s*\d{1,4}[A-Z]?"
    r"|classroom\s*\d{1,4}|hall\s*\d{1,2}|guest house)\b",
    re.I,
)


def find_venue(text: str) -> str | None:
    if m := _VENUE_LABEL.search(text):
        return collapse(m["v"])[:200]
    if m := _VENUE_CASED.search(text):
        return m.group(0)
    if m := _VENUE_WORDS.search(text):
        return collapse(m.group(0))
    return None


# ---- category ----
_CATEGORY_WORDS: list[tuple[EventCategory, tuple[str, ...]]] = [
    ("deadline", ("deadline", "last date", "due date", "due on", "due by", "submit by",
                  "submission", "apply by", "register by", "registration closes", "closes on")),
    ("exam", ("exam", "quiz", "midsem", "mid-sem", "endsem", "end-sem", "viva", "test")),
    ("workshop", ("workshop", "bootcamp", "hands-on", "hands on", "training session")),
    ("talk", ("talk", "seminar", "lecture", "colloquium", "webinar", "speaker", "panel",
              "fireside", "symposium", "guest session")),
    ("fest", ("fest", "festival", "mood indigo", "techfest", "e-summit", "cultural",
              "hackathon", "competition", "contest", "meetup")),
]  # fmt: skip
_ANY_EVENT_WORD = re.compile(
    "|".join(re.escape(w) for _, words in _CATEGORY_WORDS for w in words)
    + r"|\bregistrations?\b|\bmeeting\b|\bcompany\b|\bpre-?placement\b|\binfosession\b",
    re.I,
)


def _category(text: str) -> EventCategory | None:
    low = text.lower()
    for category, words in _CATEGORY_WORDS:
        if any(re.search(rf"\b{re.escape(w)}", low) for w in words):
            return category
    return None


def categorise(subject: str, body: str) -> EventCategory:
    """The subject decides first (it is what the sender wants you to notice), then the body."""
    return _category(subject) or _category(body[:800]) or "other"


# ---- putting it together ----
_SUBJECT_PREFIX = re.compile(r"^\s*(?:(?:re|fwd?|fw)\s*:\s*|\[[^\]]{1,40}\]\s*)+", re.I)


def clean_title(subject: str) -> str:
    title = _SUBJECT_PREFIX.sub("", subject).strip() or subject.strip() or "Untitled mail"
    return title[:200]


def combine(day: date, t: time | None) -> datetime:
    return datetime.combine(day, t or time(0, 0), tzinfo=IST)


def is_candidate(mail: ParsedMail) -> bool:
    """Is this mail worth treating as an event at all? Cheap rules only."""
    text = f"{mail.message.subject}\n{mail.body[:3000]}"
    if not _ANY_EVENT_WORD.search(text):
        return False
    ref = mail.message.date.astimezone(IST).date()
    return bool(find_dates(text, ref)) or is_institute_sender(mail.message.sender_email)


def _pick_date(subject: str, body: str, ref: date) -> DateHit | None:
    """The subject's date wins; else the first date in the body."""
    for text in (subject, body):
        hits = find_dates(text, ref)
        if hits:
            return hits[0]
    return None


def _time_near(body: str, subject: str, hit: DateHit | None) -> TimeHit | None:
    """A time close to the date phrase (same sentence or line) beats one far away."""
    if hit:
        for text in (subject, body):
            if hit.text not in text:
                continue
            at = text.find(hit.text)
            window = text[max(0, at - 60) : at + len(hit.text) + 120]
            near = find_times(window)
            if near:
                return near[0]
    for text in (subject, body[:3000]):
        found = find_times(text)
        if found:
            return found[0]
    return None


def detect_event(mail: ParsedMail) -> DetectedEvent | None:
    """Rules-only detection: one DetectedEvent (maybe date-uncertain) or None."""
    if not is_candidate(mail):
        return None
    m = mail.message
    ref = m.date.astimezone(IST).date()
    subject, body = m.subject, mail.body
    institute = is_institute_sender(m.sender_email)

    date_hit = _pick_date(subject, body, ref)
    time_hit = _time_near(body, subject, date_hit) if date_hit else None
    venue = find_venue(f"{subject}\n{body[:3000]}")

    start = end = None
    uncertain = False
    all_day = False
    if date_hit:
        start = combine(date_hit.day, time_hit.start if time_hit else None)
        all_day = time_hit is None
        if time_hit and time_hit.end:
            end = combine(date_hit.day, time_hit.end)
    else:
        uncertain = True
        if not institute:
            return None  # no date and not from the institute: not worth a card

    confidence = 0.3 if uncertain else 0.5
    confidence += 0.1 * bool(time_hit) + 0.1 * bool(venue) + 0.1 * institute
    return DetectedEvent(
        id=event_key(m.message_id, start),
        message_id=m.message_id,
        title=clean_title(subject),
        category=categorise(subject, body),
        start=start,
        end=end,
        all_day=all_day,
        date_uncertain=uncertain,
        date_text=(date_hit.text if date_hit else "")[:200],
        venue=venue,
        organizer=(m.sender_name or m.sender_email or None),
        confidence=min(confidence, 0.9),
        detected_by="rules",
        mail_subject=subject[:300],
        mail_sender=m.sender_name or m.sender_email,
        mail_date=m.date,
        open_url=m.open_url,
    )
