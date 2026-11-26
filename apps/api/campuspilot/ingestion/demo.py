"""A tiny demo index built from data/fixtures/docs/ (for `make mock-dev` on a fresh clone).

The fixture pages are synthetic samples, so they live under their own `SRC-DEMO-*`
sources with an issuer that says so. A real `make ingest` removes them first.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from campuspilot.config import REPO_ROOT
from campuspilot.ingestion import db
from campuspilot.ingestion.fetcher import FetchResult
from campuspilot.ingestion.pipeline import reindex, store_document
from campuspilot.ingestion.registry import SourceRow, load_registry

FIXTURE_DOCS = REPO_ROOT / "data" / "fixtures" / "docs"
DEMO_PREFIX = "SRC-DEMO-"

# fixture file -> its demo source. injection.html is a prompt-injection test page, so it is
# deliberately left out of the demo index.
DEMO_SOURCES: dict[str, SourceRow] = {
    "calendar.html": SourceRow(
        id="SRC-DEMO-CAL",
        title="Academic Calendar (demo sample)",
        issuer="Demo fixture, not official",
        category="calendar",
        # Card links to the real calendar page, so the click still lands somewhere useful.
        url="https://acad.iitb.ac.in/academics/calendar-and-timetable",
        authority_tier=2,
        audience="all",
        handling="ingest",
        notes="synthetic sample page for mock mode; run make ingest for the real index",
    ),
}


def build_demo_index(conn: sqlite3.Connection, raw_dir: Path) -> tuple[int, int]:
    """Load the registry plus the demo sources and index the fixture pages.

    Returns (documents, chunks) added.
    """
    for row in load_registry():
        db.upsert_source(conn, row.model_dump())
    n_docs = n_chunks = 0
    for name, source in DEMO_SOURCES.items():
        db.upsert_source(conn, source.model_dump())
        content = (FIXTURE_DOCS / name).read_bytes()
        res = FetchResult(source.url, 200, content, "text/html", source.url)
        status, _, chunks = store_document(conn, source, res, raw_dir)
        n_docs += status == "indexed"
        n_chunks += chunks
    conn.commit()
    return n_docs, n_chunks


def remove_demo_sources(conn: sqlite3.Connection) -> int:
    """Delete every SRC-DEMO-* source with its documents and chunks, then rebuild the index.

    Returns the number of demo sources removed (0 means nothing changed).
    """
    pattern = DEMO_PREFIX + "%"
    ids = [r[0] for r in conn.execute("SELECT id FROM sources WHERE id LIKE ?", (pattern,))]
    if not ids:
        return 0
    conn.execute(
        "DELETE FROM chunks WHERE document_id IN (SELECT id FROM documents WHERE source_id LIKE ?)",
        (pattern,),
    )
    conn.execute("DELETE FROM documents WHERE source_id LIKE ?", (pattern,))
    conn.execute("DELETE FROM sources WHERE id LIKE ?", (pattern,))
    reindex(conn)  # the FTS table is contentless, so rebuild it rather than delete rows
    return len(ids)
