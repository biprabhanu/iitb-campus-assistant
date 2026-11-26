"""SQLite schema (docs/CONTRACT.md section 7) and small write helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from campuspilot.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, title TEXT, issuer TEXT, category TEXT,
  url TEXT, authority_tier INTEGER, audience TEXT, handling TEXT, robots_ok INTEGER, status TEXT,
  last_checked_at TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, source_id TEXT REFERENCES sources(id),
  url TEXT, content_hash TEXT, title TEXT, published_at TEXT, fetched_at TEXT, parser TEXT,
  status TEXT, raw_path TEXT, fetched_via TEXT DEFAULT 'mac');
CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY,
  document_id INTEGER REFERENCES documents(id),
  heading_path TEXT, page INTEGER, text TEXT, audience TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, heading_path, title,
  content='', tokenize='porter unicode61');
CREATE INDEX IF NOT EXISTS idx_documents_url ON documents(url);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
"""


def resolve_db_path(db_path: Path | None = None) -> Path:
    """`None` means the path from settings (CONTRACT section 4)."""
    return db_path if db_path is not None else get_settings().campuspilot_db_path


def connect(db_path: Path | None = None, create: bool = False) -> sqlite3.Connection:
    """Open the DB. With create=True the folder and tables are created if missing."""
    path = resolve_db_path(db_path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if create:
        conn.executescript(SCHEMA)
    return conn


def upsert_source(conn: sqlite3.Connection, row: dict[str, object]) -> None:
    """Load one registry row; keeps the crawl fields (robots_ok, status, last_checked_at)."""
    conn.execute(
        """INSERT INTO sources (id, title, issuer, category, url, authority_tier, audience,
               handling, notes, status)
           VALUES (:id, :title, :issuer, :category, :url, :authority_tier, :audience,
               :handling, :notes, 'not_fetched')
           ON CONFLICT(id) DO UPDATE SET title=:title, issuer=:issuer, category=:category,
               url=:url, authority_tier=:authority_tier, audience=:audience,
               handling=:handling, notes=:notes""",
        row,
    )


def add_chunks(
    conn: sqlite3.Connection,
    document_id: int,
    doc_title: str,
    chunks: list[tuple[str, int | None, str]],
    audience: str | None,
) -> int:
    """Insert chunks (heading_path, page, text) and mirror them into the FTS table."""
    for heading_path, page, text in chunks:
        cur = conn.execute(
            "INSERT INTO chunks (document_id, heading_path, page, text, audience) "
            "VALUES (?, ?, ?, ?, ?)",
            (document_id, heading_path, page, text, audience),
        )
        conn.execute(
            "INSERT INTO chunks_fts (rowid, text, heading_path, title) VALUES (?, ?, ?, ?)",
            (cur.lastrowid, text, heading_path, doc_title),
        )
    return len(chunks)


def clear_index(conn: sqlite3.Connection) -> None:
    """Empty chunks and the FTS table (used by reindex)."""
    conn.execute("DROP TABLE IF EXISTS chunks_fts")
    conn.execute("DELETE FROM chunks")
    conn.execute(
        "CREATE VIRTUAL TABLE chunks_fts USING fts5(text, heading_path, title, "
        "content='', tokenize='porter unicode61')"
    )
