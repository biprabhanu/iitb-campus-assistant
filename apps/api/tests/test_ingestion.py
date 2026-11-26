"""Offline tests: parsing, chunking, dates, versioning, fetcher rules, reindex."""

from __future__ import annotations

from campuspilot.config import get_settings
from campuspilot.ingestion import db
from campuspilot.ingestion.chunking import approx_tokens, chunk_sections
from campuspilot.ingestion.dates import extract_published_at
from campuspilot.ingestion.fetcher import Fetcher, FetchResult
from campuspilot.ingestion.parsing import Section, parse_html, parse_pdf
from campuspilot.ingestion.pipeline import ingest_source, reindex
from tests.data_helpers import (
    add_html,
    add_pdf,
    add_source,
    fixture_text,
    make_pdf,
    make_source,
)


def test_parse_html_keeps_headings_and_drops_nav() -> None:
    doc = parse_html(fixture_text("calendar.html"), "https://acad.test/page")
    paths = [s.heading_path for s in doc.sections]
    assert doc.title == "Academic Calendar Sample"
    assert "Academic Calendar Sample > Spring Semester > Holidays" in paths
    assert "Academic Calendar Sample > Autumn Semester" in paths
    assert "Footer text" not in doc.full_text and "Menu menu" not in doc.full_text
    assert doc.pdf_links == [("https://acad.test/files/sample-calendar.pdf", "Sample Calendar PDF")]


def test_parse_pdf_page_by_page() -> None:
    doc = parse_pdf(make_pdf(["First page text here", "Second page text here"]), "My PDF")
    assert [s.page for s in doc.sections] == [1, 2]
    assert doc.title == "My PDF" and doc.parser == "pymupdf"


def test_published_at_from_text_keywords() -> None:
    assert extract_published_at("Policy approved on 22 Aug 2025 by the Senate") == "2025-08-22"
    assert extract_published_at("Rules w.e.f. 1st July, 2024.") == "2024-07-01"
    assert extract_published_at("No: 1\nDate: 8th July, 2026") == "2026-07-08"
    assert extract_published_at("Last updated on 05/03/2025") == "2025-03-05"


def test_published_at_none_without_a_date() -> None:
    assert extract_published_at("Registration opens in July. Classes begin in August.") is None
    # An ordinary date that is not a publication date is not used.
    assert extract_published_at("Exam on 12 Oct 2026 in hall A") is None


def test_published_at_from_title_date() -> None:
    assert extract_published_at("body text", "Circular 10 May 2026") == "2026-05-10"


def test_chunks_respect_size_and_boundaries() -> None:
    long_text = "\n".join(f"Line {i} " + "word " * 40 for i in range(40))
    sections = [
        Section("A > B", long_text),
        Section("C", "short but valid text"),
        Section("D", "tiny"),
        Section("PDF", "page text goes here", page=3),
    ]
    chunks = chunk_sections(sections)
    big = [c for c in chunks if c[0] == "A > B"]
    assert len(big) > 1
    assert all(approx_tokens(c[2]) <= 500 for c in big)
    assert ("C", None, "short but valid text") in chunks
    assert not any(c[0] == "D" for c in chunks)  # fewer than 3 words is dropped
    assert ("PDF", 3, "page text goes here") in chunks


def test_hash_versioning_adds_row_only_on_change(tmp_path) -> None:
    conn = db.connect(create=True)
    src = make_source()
    add_source(conn, src)
    raw = tmp_path / "raw"
    html = fixture_text("calendar.html")
    first = add_html(conn, src, "https://x.test/a", html, raw)
    again = add_html(conn, src, "https://x.test/a", html, raw)
    changed = add_html(conn, src, "https://x.test/a", html + "<p>New paragraph added.</p>", raw)
    assert first[0] == "indexed" and again[0] == "unchanged" and changed[0] == "indexed"
    rows = conn.execute("SELECT status, published_at FROM documents ORDER BY id").fetchall()
    assert len(rows) == 2  # history kept, nothing overwritten
    assert rows[0]["published_at"] == "2025-08-22"
    assert len(list((raw / "SRC-TEST").iterdir())) == 2


def test_empty_pdf_is_failed_and_not_indexed(tmp_path) -> None:
    conn = db.connect(create=True)
    src = make_source()
    add_source(conn, src)
    outcome, _, n = add_pdf(conn, src, "https://x.test/empty.pdf", [""], tmp_path / "raw")
    assert outcome == "failed" and n == 0
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    assert conn.execute("SELECT status FROM documents").fetchone()[0] == "failed"


def test_reindex_rebuilds_chunks_from_raw(tmp_path) -> None:
    conn = db.connect(create=True)
    src = make_source()
    add_source(conn, src)
    raw = get_settings().campuspilot_raw_dir
    add_html(conn, src, "https://x.test/a", fixture_text("calendar.html"), raw)
    before = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_docs, n_chunks = reindex(conn, raw)
    assert (n_docs, n_chunks) == (1, before)
    fts = conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'holi'").fetchone()
    assert fts[0] == 1


class _FakeFetcher(Fetcher):
    """Never touches the network; counts calls."""

    def __init__(self) -> None:
        super().__init__(sleep=lambda _s: None)
        self.heads: list[str] = []
        self.gets: list[str] = []

    def head(self, url: str) -> FetchResult:
        self.heads.append(url)
        return FetchResult(url, 200, final_url=url)

    def get(self, url: str) -> FetchResult:
        self.gets.append(url)
        return FetchResult(
            url, 200, b"<html><title>T</title><main><p>some page text here</p></main>"
        )

    def robots_allowed(self, url: str) -> bool:
        return True


def test_link_only_gets_head_only(tmp_path) -> None:
    conn = db.connect(create=True)
    src = make_source(handling="link_only")
    add_source(conn, src)
    fetcher = _FakeFetcher()
    report = ingest_source(conn, src, fetcher, tmp_path / "raw")
    assert fetcher.heads == [src.url] and fetcher.gets == []
    assert report.http_status == 200
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_ingest_source_fetches_and_indexes(tmp_path) -> None:
    conn = db.connect(create=True)
    src = make_source()
    add_source(conn, src)
    fetcher = _FakeFetcher()
    report = ingest_source(conn, src, fetcher, tmp_path / "raw", fallback=None)
    assert report.documents == 1 and report.chunks == 1
    status = conn.execute("SELECT status FROM sources WHERE id='SRC-TEST'").fetchone()[0]
    assert status == "indexed"


def test_fetcher_rate_limit_and_robots() -> None:
    sleeps: list[float] = []
    fetcher = Fetcher(sleep=sleeps.append)
    fetcher._wait_turn("a.test")
    fetcher._wait_turn("a.test")  # second request to the same host must wait ~2 s
    fetcher._wait_turn("b.test")  # a different host does not wait
    assert len(sleeps) == 1 and 1.5 < sleeps[0] <= 2.0

    fetcher._robots["https://c.test"] = None
    assert fetcher.robots_allowed("https://c.test/anything")
    from urllib.robotparser import RobotFileParser

    parser = RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /private"])
    fetcher._robots["https://d.test"] = parser
    assert not fetcher.robots_allowed("https://d.test/private/x")
    assert fetcher.get("https://d.test/private/x").error == "robots"
