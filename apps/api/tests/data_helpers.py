"""Helpers that build a small test index from synthetic fixtures (no network)."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from campuspilot.ingestion import db
from campuspilot.ingestion.fetcher import FetchResult
from campuspilot.ingestion.pipeline import store_document
from campuspilot.ingestion.registry import SourceRow

FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "docs"


def make_pdf(pages: list[str]) -> bytes:
    """A tiny PDF with one text block per page."""
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def make_source(
    source_id: str = "SRC-TEST",
    tier: int = 1,
    audience: str = "all",
    handling: str = "ingest",
    category: str = "academics",
    title: str = "Test Source",
    notes: str = "",
) -> SourceRow:
    return SourceRow(
        id=source_id,
        title=title,
        issuer="Test Office",
        category=category,
        url=f"https://example.test/{source_id}",
        authority_tier=tier,
        audience=audience,
        handling=handling,
        notes=notes,
    )


def add_source(conn, source: SourceRow) -> None:
    db.upsert_source(conn, source.model_dump())
    conn.commit()


def add_html(conn, source: SourceRow, url: str, html: str, raw_dir: Path):
    res = FetchResult(url, 200, html.encode(), "text/html", url)
    out = store_document(conn, source, res, raw_dir)
    conn.commit()
    return out


def add_pdf(conn, source: SourceRow, url: str, pages: list[str], raw_dir: Path, title: str = ""):
    res = FetchResult(url, 200, make_pdf(pages), "application/pdf", url)
    out = store_document(conn, source, res, raw_dir, title_hint=title)
    conn.commit()
    return out


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
