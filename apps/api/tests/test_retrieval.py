"""Offline tests: FTS search, tier boost, audience filter, sanitising, link lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from campuspilot.ingestion import db
from campuspilot.retrieval.tools import (
    build_match_query,
    count_indexed_sources,
    get_official_link,
    list_sources,
    search_campus_docs,
)
from campuspilot.schemas.tools import GetOfficialLinkInput, SearchCampusDocsInput
from tests.data_helpers import add_html, add_pdf, add_source, fixture_text, make_source


def search(query: str, **kw):
    return search_campus_docs(SearchCampusDocsInput(query=query, **kw)).hits


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(create=True)
    yield connection
    connection.close()


def test_empty_when_db_missing() -> None:
    assert not Path(db.resolve_db_path()).exists()
    assert search("academic calendar") == []
    assert get_official_link(GetOfficialLinkInput(topic="hostel")).links == []
    assert list_sources() == []
    assert count_indexed_sources() == 0


def test_fts_search_returns_heading_and_metadata(conn, tmp_path) -> None:
    src = make_source("SRC-CAL", category="calendar")
    add_source(conn, src)
    add_html(conn, src, "https://x.test/cal", fixture_text("calendar.html"), tmp_path / "raw")
    hits = search("holidays in spring semester")
    assert hits and hits[0].heading_path.endswith("Spring Semester > Holidays")
    assert hits[0].source_id == "SRC-CAL" and hits[0].published_at == "2025-08-22"
    assert hits[0].url == "https://x.test/cal" and hits[0].score > 0
    assert search("holiday", category="hostel") == []  # category filter


def test_tier1_beats_tier2_for_same_text(conn, tmp_path) -> None:
    text = "<main><h1>Mess</h1><p>The hostel mess timings are fixed for all meals.</p></main>"
    t1, t2 = make_source("SRC-T1", tier=1), make_source("SRC-T2", tier=2)
    for s, url in ((t2, "https://x.test/2"), (t1, "https://x.test/1")):
        add_source(conn, s)
        add_html(conn, s, url, text.replace("fixed", "set" if s is t2 else "fixed"), tmp_path / "r")
    hits = search("hostel mess timings")
    assert [h.source_id for h in hits][0] == "SRC-T1"


def test_audience_filter(conn, tmp_path) -> None:
    ug = make_source("SRC-UG", audience="ug_entrants_2026_27")
    pg = make_source("SRC-PG", audience="pg_phd_entrants")
    allsrc = make_source("SRC-ALL", audience="all")
    page = "<main><h1>Joining</h1><p>Bring the {} documents for registration on arrival.</p></main>"
    for s, word in ((ug, "undergraduate"), (pg, "postgraduate"), (allsrc, "general")):
        add_source(conn, s)
        add_html(conn, s, f"https://x.test/{s.id}", page.format(word), tmp_path / "raw")
    ids = {h.source_id for h in search("documents registration", audience="pg_phd_entrants")}
    assert ids == {"SRC-PG", "SRC-ALL"}
    assert {h.source_id for h in search("documents registration")} == {
        "SRC-UG",
        "SRC-PG",
        "SRC-ALL",
    }


def test_max_two_chunks_per_document(conn, tmp_path) -> None:
    src = make_source()
    add_source(conn, src)
    pages = [f"scholarship rules page {i} scholarship details" for i in range(5)]
    add_pdf(conn, src, "https://x.test/s.pdf", pages, tmp_path / "raw", title="Scholarship PDF")
    hits = search("scholarship", k=8)
    assert len(hits) == 2 and {h.page for h in hits} <= {1, 2, 3, 4, 5}


def test_only_enabled_sources_and_latest_version(conn, tmp_path) -> None:
    on, off = make_source("SRC-ON"), make_source("SRC-OFF", handling="link_only")
    for s in (on, off):
        add_source(conn, s)
    raw = tmp_path / "raw"
    add_html(conn, off, "https://x.test/off", "<main><p>zebra crossing policy text</p></main>", raw)
    add_html(conn, on, "https://x.test/on", "<main><p>giraffe old policy text</p></main>", raw)
    add_html(conn, on, "https://x.test/on", "<main><p>giraffe new policy text</p></main>", raw)
    assert search("zebra") == []
    texts = [h.text for h in search("giraffe")]
    assert texts == ["giraffe new policy text"]  # only the latest version is searchable


@pytest.mark.parametrize(
    "query",
    ['"unbalanced', "a AND OR NOT b", "hostel* NEAR(x y)", "col:umn -minus ()", "'; DROP--"],
)
def test_query_sanitising_never_breaks_match(conn, tmp_path, query) -> None:
    src = make_source()
    add_source(conn, src)
    add_html(conn, src, "https://x.test/a", fixture_text("calendar.html"), tmp_path / "raw")
    search(query)  # must not raise


def test_build_match_query_drops_stopwords_and_operators() -> None:
    assert build_match_query('What is the "academic" calendar? AND NOT*') == (
        '"academic" OR "calendar"'
    )
    assert build_match_query("the of a") == ""


def test_prompt_injection_text_is_stored_as_plain_data(conn, tmp_path) -> None:
    src = make_source()
    add_source(conn, src)
    add_html(conn, src, "https://x.test/n", fixture_text("injection.html"), tmp_path / "raw")
    hits = search("ignore previous instructions system prompt")
    assert hits and "Ignore previous instructions" in hits[0].text  # returned as plain text


def test_official_link_hostel_maintenance(conn) -> None:
    rows = [
        make_source(
            "SRC-HOSTEL-RULES", category="hostel", title="Hostel Rules", notes="hostel rules"
        ),
        make_source(
            "SRC-SUPPORT",
            category="maintenance",
            handling="link_only",
            title="Support Portal",
            notes="hostel maintenance complaints, repairs, plumbing",
        ),
        make_source("SRC-BLOCKED", category="maintenance", handling="blocked", notes="maintenance"),
    ]
    for r in rows:
        add_source(conn, r)
    links = get_official_link(GetOfficialLinkInput(topic="hostel maintenance")).links
    assert links[0].source_id == "SRC-SUPPORT"
    assert links[0].url == "https://example.test/SRC-SUPPORT"  # URL from the registry
    assert "SRC-BLOCKED" not in {link.source_id for link in links}
    assert get_official_link(GetOfficialLinkInput(topic="zzzz")).links == []


def test_list_sources_and_count(conn, tmp_path) -> None:
    a, b = make_source("SRC-A"), make_source("SRC-B", handling="link_only")
    for s in (a, b):
        add_source(conn, s)
    add_html(conn, a, "https://x.test/a", fixture_text("calendar.html"), tmp_path / "raw")
    listed = {s.id: s for s in list_sources()}
    assert listed["SRC-A"].documents == 1 and listed["SRC-A"].chunks > 0
    assert listed["SRC-B"].documents == 0
    assert count_indexed_sources() == 1


def test_display_title_falls_back_to_file_name():
    from campuspilot.retrieval.tools import display_title

    url = "https://acad.iitb.ac.in/sites/default/files/UG_RULE_BOOK.pdf"
    assert display_title(url, url, "Source") == "UG RULE BOOK"
    assert (
        display_title(None, "https://x.in/Academic%20Calendar-2026.pdf", "S")
        == "Academic Calendar 2026"
    )
    assert display_title("Code of Conduct", url, "Source") == "Code of Conduct"
