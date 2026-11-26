"""Demo mode (CONNECTORS_DEMO=true): synthetic `.eml` fixtures with dates shifted to "now".

The fixtures in data/fixtures/mail/ are made up. They hold placeholders that are filled in each
time, so the demo always shows events in the coming days:
  {NOW-5h}  the Date header, 5 hours ago      {D+3}   "3 December"  (3 days from today)
  {DN+4}    "04/12/2026" (day first)          {WD+5}  "Tuesday"     (weekday 5 days from today)
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from functools import lru_cache

from campuspilot.config import REPO_ROOT
from campuspilot.mail.events import IST
from campuspilot.mail.parsing import ParsedMail, parse_message

FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "mail"

_PLACEHOLDER = re.compile(r"\{(NOW|DN|D|WD)([+-])(\d+)h?\}")


@lru_cache
def _raw_fixtures() -> list[tuple[str, str]]:
    return [
        (path.name, path.read_text(encoding="utf-8")) for path in sorted(FIXTURE_DIR.glob("*.eml"))
    ]


def _fill(text: str, now: datetime) -> str:
    today = now.astimezone(IST).date()

    def sub(m: re.Match) -> str:
        kind, sign, amount = m[1], m[2], int(m[3])
        if kind == "NOW":
            return format_datetime(now - timedelta(hours=amount))
        day = today + timedelta(days=amount if sign == "+" else -amount)
        if kind == "D":
            return f"{day.day} {day:%B}"
        if kind == "DN":
            return f"{day.day:02d}/{day.month:02d}/{day.year}"
        return f"{day:%A}"

    return _PLACEHOLDER.sub(sub, text)


def demo_mails(now: datetime | None = None) -> list[ParsedMail]:
    """All demo mails, newest first, parsed by the same code as real mail."""
    now = now or datetime.now(UTC)
    mails = [
        parse_message(_fill(text, now).encode("utf-8"), uid=str(i))
        for i, (_, text) in enumerate(_raw_fixtures(), start=1)
    ]
    return sorted(mails, key=lambda m: m.message.date, reverse=True)
