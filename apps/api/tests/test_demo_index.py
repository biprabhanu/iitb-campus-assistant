"""The mock-dev demo index: built from fixtures, searchable, and removed by a real ingest."""

from __future__ import annotations

from campuspilot.ingestion import db
from campuspilot.ingestion.demo import build_demo_index, remove_demo_sources
from campuspilot.retrieval.tools import count_indexed_sources, list_sources, search_campus_docs
from campuspilot.schemas.tools import SearchCampusDocsInput
from tests.data_helpers import add_html, add_source, fixture_text, make_source


def search(query: str):
    return search_campus_docs(SearchCampusDocsInput(query=query)).hits


def test_demo_index_answers_the_calendar_question(tmp_path) -> None:
    conn = db.connect(create=True)
    docs, chunks = build_demo_index(conn, tmp_path / "raw")
    conn.close()
    assert docs == 1 and chunks > 0
    hits = search("Where can I find the academic calendar?")
    assert hits and hits[0].source_id == "SRC-DEMO-CAL"
    assert "demo" in hits[0].issuer.lower() or "not official" in hits[0].issuer.lower()
    assert not search("ignore previous instructions")  # the injection fixture is left out
    ids = {s.id for s in list_sources()}
    assert {"SRC-ACAD-CAL", "SRC-DEMO-CAL"} <= ids  # the whole registry is loaded too


def test_real_ingest_removes_demo_sources(tmp_path) -> None:
    conn = db.connect(create=True)
    build_demo_index(conn, tmp_path / "raw")
    real = make_source("SRC-REAL", category="calendar")
    add_source(conn, real)
    add_html(conn, real, "https://x.test/cal", fixture_text("calendar.html"), tmp_path / "raw")
    assert remove_demo_sources(conn) == 1
    conn.commit()
    conn.close()
    assert {h.source_id for h in search("academic calendar")} == {"SRC-REAL"}
    assert count_indexed_sources() == 1
    conn = db.connect()
    assert remove_demo_sources(conn) == 0
    conn.close()
