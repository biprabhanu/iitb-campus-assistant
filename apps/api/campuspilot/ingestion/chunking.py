"""Split parsed sections into chunks of roughly 300-500 tokens (tokens ~ words x 1.3)."""

from __future__ import annotations

from campuspilot.ingestion.parsing import Section

MAX_TOKENS = 500
MIN_WORDS = 3  # drop sections that are only a few words


def approx_tokens(text: str) -> float:
    return len(text.split()) * 1.3


def _split_long(text: str) -> list[str]:
    """Split one section's text into pieces under MAX_TOKENS, on line breaks where possible."""
    pieces: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        # A single very long line is cut by words.
        words = line.split()
        parts = [line]
        if approx_tokens(line) > MAX_TOKENS:
            step = int(MAX_TOKENS / 1.3)
            parts = [" ".join(words[i : i + step]) for i in range(0, len(words), step)]
        for part in parts:
            if current and approx_tokens("\n".join([*current, part])) > MAX_TOKENS:
                pieces.append("\n".join(current))
                current = []
            current.append(part)
    if current:
        pieces.append("\n".join(current))
    return pieces


def chunk_sections(sections: list[Section]) -> list[tuple[str, int | None, str]]:
    """Return (heading_path, page, text) tuples; never crosses a heading or page boundary."""
    chunks: list[tuple[str, int | None, str]] = []
    for section in sections:
        if len(section.text.split()) < MIN_WORDS:
            continue
        for piece in _split_long(section.text):
            chunks.append((section.heading_path, section.page, piece))
    return chunks
