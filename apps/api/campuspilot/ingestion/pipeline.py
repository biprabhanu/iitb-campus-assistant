"""Fetch -> save raw -> parse -> version -> chunk -> index."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from campuspilot.config import get_settings
from campuspilot.ingestion import db
from campuspilot.ingestion.chunking import chunk_sections
from campuspilot.ingestion.fetcher import Fetcher, FetchResult, fetch_via_passpoli
from campuspilot.ingestion.parsing import ParsedDoc, parse_html, parse_pdf
from campuspilot.ingestion.registry import SourceRow

MAX_PDFS_PER_SOURCE = 25
FallbackFn = Callable[[str], FetchResult]


@dataclass
class IngestReport:
    source_id: str
    handling: str
    http_status: int = 0
    robots_ok: bool | None = None
    fetched_via: str = "mac"
    title_seen: str = ""
    documents: int = 0  # indexed documents (page plus PDFs)
    chunks: int = 0
    failed: int = 0
    unchanged: int = 0
    notes: list[str] = field(default_factory=list)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def is_pdf(content: bytes, content_type: str = "") -> bool:
    return content[:5] == b"%PDF-" or "pdf" in content_type.lower()


def parse_bytes(content: bytes, content_type: str, url: str, title_hint: str = "") -> ParsedDoc:
    """Pick the right parser for the bytes."""
    if is_pdf(content, content_type):
        return parse_pdf(content, fallback_title=title_hint)
    return parse_html(content, url)


def save_raw(raw_dir: Path, source_id: str, content: bytes, content_hash: str, ext: str) -> str:
    """Write the raw file; returns the path relative to raw_dir."""
    rel = f"{source_id}/{content_hash[:16]}.{ext}"
    target = raw_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return rel


def store_document(
    conn: sqlite3.Connection,
    source: SourceRow,
    res: FetchResult,
    raw_dir: Path,
    title_hint: str = "",
) -> tuple[str, ParsedDoc | None, int]:
    """Save, parse, version and index one fetched file.

    Returns (outcome, parsed, n_chunks); outcome is indexed, failed or unchanged.
    A new documents row is added only when the content hash changes.
    """
    content_hash = hashlib.sha256(res.content).hexdigest()
    last = conn.execute(
        "SELECT id, content_hash FROM documents WHERE source_id=? AND url=? "
        "ORDER BY id DESC LIMIT 1",
        (source.id, res.url),
    ).fetchone()
    if last and last["content_hash"] == content_hash:
        conn.execute("UPDATE documents SET fetched_at=? WHERE id=?", (now_iso(), last["id"]))
        return "unchanged", None, 0

    pdf = is_pdf(res.content, res.content_type)
    raw_path = save_raw(raw_dir, source.id, res.content, content_hash, "pdf" if pdf else "html")
    try:
        parsed = parse_bytes(res.content, res.content_type, res.url, title_hint)
    except Exception as exc:  # noqa: BLE001 - any parser error means "failed extraction"
        parsed = ParsedDoc(title=title_hint, parser=f"error:{type(exc).__name__}")
    chunks = chunk_sections(parsed.sections)
    title = parsed.title or title_hint or source.title
    status = "indexed" if chunks else "failed"
    cur = conn.execute(
        "INSERT INTO documents (source_id, url, content_hash, title, published_at, fetched_at, "
        "parser, status, raw_path, fetched_via) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source.id, res.url, content_hash, title, parsed.published_at, now_iso(), parsed.parser,
         status, raw_path, res.via),
    )  # fmt: skip
    n = 0
    if status == "indexed" and cur.lastrowid is not None:
        n = db.add_chunks(conn, cur.lastrowid, title, chunks, source.audience)
    return status, parsed, n


def _fetch_with_fallback(fetcher: Fetcher, url: str, fallback: FallbackFn | None) -> FetchResult:
    """Try the Mac first; on a network-ish failure retry from Passpoli."""
    res = fetcher.get(url)
    needs_retry = res.error != "robots" and (res.status in (0, 403) or res.status >= 500)
    if needs_retry and fallback is not None:
        alt = fallback(url)
        if alt.ok:
            return alt
    return res


def _count(report: IngestReport, outcome: str, n_chunks: int) -> None:
    if outcome == "indexed":
        report.documents += 1
        report.chunks += n_chunks
    elif outcome == "failed":
        report.failed += 1
    else:
        report.unchanged += 1


def ingest_source(
    conn: sqlite3.Connection,
    source: SourceRow,
    fetcher: Fetcher,
    raw_dir: Path | None = None,
    fallback: FallbackFn | None = fetch_via_passpoli,
    skip_urls: frozenset[str] = frozenset(),
) -> IngestReport:
    """Ingest one `ingest` row (page, plus same-host PDFs one level deep).

    link_only rows get a reachability HEAD only; blocked and needs_review rows are not fetched.
    """
    raw_dir = raw_dir or get_settings().campuspilot_raw_dir
    report = IngestReport(source.id, source.handling)
    checked = now_iso()

    if source.handling != "ingest":
        if source.handling == "link_only":
            head = fetcher.head(source.url)
            report.http_status = head.status
            report.notes.append("HEAD only")
        status = source.handling
        conn.execute(
            "UPDATE sources SET status=?, last_checked_at=? WHERE id=?",
            (status, checked, source.id),
        )
        return report

    report.robots_ok = fetcher.robots_allowed(source.url)
    res = _fetch_with_fallback(fetcher, source.url, fallback) if report.robots_ok else None
    if res is None:
        report.notes.append("blocked by robots.txt")
        conn.execute(
            "UPDATE sources SET status='failed', robots_ok=0, last_checked_at=? WHERE id=?",
            (checked, source.id),
        )
        return report

    report.http_status, report.fetched_via = res.status, res.via
    if not res.ok:
        report.notes.append(f"fetch failed: {res.error or res.status}")
        conn.execute(
            "UPDATE sources SET status='failed', robots_ok=1, last_checked_at=? WHERE id=?",
            (checked, source.id),
        )
        return report

    res.url = source.url
    outcome, parsed, n = store_document(conn, source, res, raw_dir, title_hint=source.title)
    _count(report, outcome, n)
    report.title_seen = parsed.title if parsed else ""
    if parsed is None:  # unchanged: re-read the stored title for the audit
        row = conn.execute(
            "SELECT title FROM documents WHERE source_id=? AND url=? ORDER BY id DESC LIMIT 1",
            (source.id, source.url),
        ).fetchone()
        report.title_seen = row["title"] if row else ""

    # PDFs linked from an HTML page: same host, one level deep, capped per source.
    links: list[tuple[str, str]] = []
    if not is_pdf(res.content, res.content_type):
        links = parse_html(res.content, source.url).pdf_links
    for pdf_url, link_text in links[:MAX_PDFS_PER_SOURCE]:
        if urlparse(pdf_url).netloc != urlparse(source.url).netloc or pdf_url in skip_urls:
            continue  # other host, or a PDF that has its own registry row
        pdf_res = _fetch_with_fallback(fetcher, pdf_url, fallback)
        if not pdf_res.ok:
            report.notes.append(f"pdf skipped ({pdf_res.error or pdf_res.status}): {pdf_url}")
            continue
        pdf_res.url = pdf_url
        outcome, _, n = store_document(conn, source, pdf_res, raw_dir, title_hint=link_text)
        _count(report, outcome, n)

    total = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE source_id=? AND status='indexed'", (source.id,)
    ).fetchone()[0]
    conn.execute(
        "UPDATE sources SET status=?, robots_ok=1, last_checked_at=? WHERE id=?",
        ("indexed" if total else "failed", checked, source.id),
    )
    return report


def reindex(conn: sqlite3.Connection, raw_dir: Path | None = None) -> tuple[int, int]:
    """Rebuild chunks and FTS from the saved raw files. Returns (documents, chunks)."""
    raw_dir = raw_dir or get_settings().campuspilot_raw_dir
    db.clear_index(conn)
    docs = conn.execute(
        "SELECT d.*, s.audience AS source_audience FROM documents d "
        "JOIN sources s ON s.id = d.source_id WHERE d.status IN ('indexed', 'failed')"
    ).fetchall()
    n_docs = n_chunks = 0
    for d in docs:
        path = raw_dir / (d["raw_path"] or "")
        if not d["raw_path"] or not path.is_file():
            continue
        content = path.read_bytes()
        try:
            parsed = parse_bytes(content, "", d["url"], d["title"] or "")
            chunks = chunk_sections(parsed.sections)
        except Exception:  # noqa: BLE001
            chunks, parsed = [], None
        status = "indexed" if chunks else "failed"
        title = (parsed.title if parsed else "") or d["title"] or ""
        conn.execute(
            "UPDATE documents SET status=?, title=?, published_at=? WHERE id=?",
            (status, title, parsed.published_at if parsed else None, d["id"]),
        )
        if chunks:
            n_chunks += db.add_chunks(conn, d["id"], title, chunks, d["source_audience"])
            n_docs += 1
    conn.commit()
    return n_docs, n_chunks
