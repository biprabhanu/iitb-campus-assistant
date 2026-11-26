"""Citation markers like [S1], [M2] or [S1][S2]: parse, validate, strip invalid ones.

`CitationFilter` works on streamed text. A '[' might be the start of a marker split
across two chunks, so we hold a few characters back until we know.
"""

from __future__ import annotations

import re

MARKER_RE = re.compile(r"\[([SM]\d+)\]")
_PARTIAL_RE = re.compile(r"\[(?:[SM]\d*)?$")  # "[", "[S", "[S1": might still become a marker


def find_markers(text: str) -> list[str]:
    """All citation ids mentioned in `text`, in order (valid or not)."""
    return MARKER_RE.findall(text)


class CitationFilter:
    def __init__(self, valid_ids: set[str]) -> None:
        self._valid = valid_ids
        self._buf = ""
        self.cited: list[str] = []  # valid ids, first-use order, no repeats
        self.removed = 0  # count of invalid markers dropped

    def feed(self, text: str) -> str:
        """Take the next piece of text, return what is safe to show now."""
        self._buf += text
        out: list[str] = []
        while self._buf:
            start = self._buf.find("[")
            if start == -1:
                out.append(self._buf)
                self._buf = ""
                break
            out.append(self._buf[:start])
            rest = self._buf[start:]
            match = MARKER_RE.match(rest)
            if match:
                self._handle(match.group(1), out, match.group(0))
                self._buf = rest[match.end() :]
            elif _PARTIAL_RE.match(rest):
                self._buf = rest  # wait for more text
                break
            else:
                out.append("[")  # just a normal bracket
                self._buf = rest[1:]
        return "".join(out)

    def flush(self) -> str:
        """End of stream: release whatever is still held back."""
        rest, self._buf = self._buf, ""
        return rest

    def _handle(self, marker_id: str, out: list[str], raw: str) -> None:
        if marker_id in self._valid:
            out.append(raw)
            if marker_id not in self.cited:
                self.cited.append(marker_id)
        else:
            self.removed += 1

    def limitation(self) -> str | None:
        if not self.removed:
            return None
        return f"Removed {self.removed} unverified citation(s)"


def strip_invalid(text: str, valid_ids: set[str]) -> tuple[str, list[str], int]:
    """Non-streaming helper: (clean text, cited ids, removed count)."""
    f = CitationFilter(valid_ids)
    clean = f.feed(text) + f.flush()
    return clean, f.cited, f.removed
