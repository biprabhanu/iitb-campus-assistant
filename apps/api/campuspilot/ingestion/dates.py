"""Find a document's own date in its text (never the crawl time)."""

from __future__ import annotations

import re
from datetime import date

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_MON = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)

# Each pattern yields (day, month, year) through named groups.
_PATTERNS = [
    re.compile(
        rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?[\s\-]+{_MON}\.?,?[\s\-]+(?P<y>\d{{4}})\b", re.I
    ),
    re.compile(rf"\b{_MON}\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b", re.I),
    re.compile(r"\b(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{4})\b"),
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"),
]

# Words that usually sit right before a document's own date.
_KEYWORDS = re.compile(
    r"(approved(?:\s+by[^.\n]{0,40})?\s+on|w\.?\s?e\.?\s?f\.?|effective(?:\s+from)?|"
    r"revised(?:\s+on)?|amended(?:\s+on)?|last\s+updated(?:\s+on)?|updated\s+on|"
    r"last\s+modified|published(?:\s+on)?|issued(?:\s+on)?|dated|date\s*:)",
    re.I,
)


def _to_date(match: re.Match[str]) -> date | None:
    groups = match.groupdict()
    month_text = next((g for g in match.groups() if g and g[:3].lower() in MONTHS), None)
    try:
        month = MONTHS[month_text[:3].lower()] if month_text else int(groups["m"])
        return date(int(groups["y"]), month, int(groups["d"]))
    except (KeyError, ValueError, TypeError):
        return None


def _first_date(text: str) -> date | None:
    """Earliest-positioned valid date in `text`."""
    found: list[tuple[int, date]] = []
    for pattern in _PATTERNS:
        for m in pattern.finditer(text):
            d = _to_date(m)
            if d and 1990 <= d.year <= date.today().year + 2:
                found.append((m.start(), d))
    return min(found, key=lambda x: x[0])[1] if found else None


def extract_published_at(text: str, title: str = "") -> str | None:
    """ISO date from a keyword-led date in the text, else a date in the title, else None."""
    for kw in _KEYWORDS.finditer(text):
        d = _first_date(text[kw.end() : kw.end() + 40])
        if d:
            return d.isoformat()
    d = _first_date(title)
    return d.isoformat() if d else None
