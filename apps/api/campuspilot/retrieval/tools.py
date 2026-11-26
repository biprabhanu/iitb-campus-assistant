"""Doc tools from CONTRACT section 4: search, official links, source listing and counts."""

from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from campuspilot.ingestion.db import connect, resolve_db_path
from campuspilot.ingestion.registry import SourceRow, load_registry
from campuspilot.schemas.chat import SourcePublic
from campuspilot.schemas.tools import (
    DocChunkHit,
    GetOfficialLinkInput,
    GetOfficialLinkOutput,
    OfficialLink,
    SearchCampusDocsInput,
    SearchCampusDocsOutput,
)

TIER1_BOOST = 1.25
MAX_CHUNKS_PER_DOC = 2
CANDIDATES = 100  # rows pulled from FTS before the per-document limit is applied

STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how"}
    | {"i", "in", "is", "it", "me", "my", "of", "on", "or", "the", "to", "was", "what", "when"}
    | {"where", "which", "who", "why", "will", "with", "you", "your", "about", "get", "have"}
    | {"has", "should", "not", "near"}
)

# Latest indexed document per URL, from enabled (ingest) sources only.
_LATEST_DOC = (
    "d.status='indexed' AND s.handling='ingest' "
    "AND d.id = (SELECT MAX(id) FROM documents"
    " WHERE source_id=d.source_id AND url=d.url AND status='indexed')"
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens without stopwords. Operators, quotes and symbols are dropped."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]
    return list(dict.fromkeys(tokens))  # unique, keep order


def build_match_query(text: str) -> str:
    """Safe FTS5 query: every term quoted, joined with OR. Empty string if nothing is left."""
    return " OR ".join(f'"{t}"' for t in tokenize(text)[:20])


def _open_existing(db_path: Path | None) -> sqlite3.Connection | None:
    if not resolve_db_path(db_path).is_file():
        return None
    return connect(db_path)


def search_campus_docs(
    args: SearchCampusDocsInput, db_path: Path | None = None
) -> SearchCampusDocsOutput:
    match = build_match_query(args.query)
    conn = _open_existing(db_path)
    if conn is None or not match:
        return SearchCampusDocsOutput()
    sql = f"""
        SELECT c.id AS chunk_id, c.document_id, c.heading_path, c.page, c.text, c.audience,
               d.url, d.title, d.fetched_at, d.published_at,
               s.id AS source_id, s.title AS source_title, s.issuer, s.authority_tier, s.category,
               bm25(chunks_fts, 1.0, 0.5, 0.5) AS rank
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        JOIN sources s ON s.id = d.source_id
        WHERE chunks_fts MATCH ? AND {_LATEST_DOC}
    """  # noqa: S608 - the fragment is a constant, values are bound
    params: list[object] = [match]
    if args.category:
        sql += " AND s.category = ?"
        params.append(args.category)
    if args.audience:
        sql += " AND (c.audience IS NULL OR c.audience = 'all' OR c.audience = ?)"
        params.append(args.audience)
    sql += " ORDER BY rank LIMIT ?"
    params.append(CANDIDATES)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return SearchCampusDocsOutput()  # e.g. empty or half-built DB
    finally:
        conn.close()

    scored = sorted(rows, key=_score, reverse=True)
    hits: list[DocChunkHit] = []
    per_doc: dict[int, int] = {}
    seen_text: set[str] = set()  # the same PDF can be linked from two sources
    for row in scored:
        if row["text"] in seen_text:
            continue
        seen_text.add(row["text"])
        if per_doc.get(row["document_id"], 0) >= MAX_CHUNKS_PER_DOC:
            continue
        per_doc[row["document_id"]] = per_doc.get(row["document_id"], 0) + 1
        hits.append(_to_hit(row))
        if len(hits) >= args.k:
            break
    return SearchCampusDocsOutput(hits=hits)


def _score(row: sqlite3.Row) -> float:
    """Higher is better: negated BM25, boosted for tier 1 (the responsible office)."""
    score = -float(row["rank"])
    return score * TIER1_BOOST if row["authority_tier"] == 1 else score


def display_title(title: str | None, url: str, fallback: str) -> str:
    """A readable title. Some PDFs have no title, and the parser stored the URL instead;
    then we use the file name ("UG_RULE_BOOK.pdf" -> "UG RULE BOOK")."""
    if title and not title.startswith(("http://", "https://")):
        return title
    name = PurePosixPath(unquote(urlparse(url).path)).stem
    name = re.sub(r"[_\-]+", " ", name).strip()
    return name or fallback


def _to_hit(row: sqlite3.Row) -> DocChunkHit:
    return DocChunkHit(
        chunk_id=row["chunk_id"],
        source_id=row["source_id"],
        document_id=row["document_id"],
        title=display_title(row["title"], row["url"], row["source_title"]),
        issuer=row["issuer"],
        url=row["url"],
        heading_path=row["heading_path"] or "",
        page=row["page"],
        text=row["text"],
        audience=row["audience"],
        authority_tier=row["authority_tier"],
        category=row["category"],
        checked_at=row["fetched_at"],
        published_at=row["published_at"],
        score=_score(row),
    )


# ---------- get_official_link ----------


def _stem(word: str) -> str:
    """Very small stemmer so 'complaints' matches 'complaint'."""
    for suffix in ("ing", "es", "s", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _stems(text: str) -> set[str]:
    return {_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower())}


def _link_score(topic_tokens: list[str], row: SourceRow) -> int:
    fields = [  # (text, weight)
        (row.title, 3),
        (row.category, 3),
        (row.notes, 2),
        (row.issuer, 1),
    ]
    stems = [_stem(t) for t in topic_tokens]
    score = 0
    for text, weight in fields:
        field_stems = _stems(text)
        score += weight * sum(1 for s in stems if s in field_stems)
    # Bonus when two neighbouring topic words appear next to each other in the title or notes.
    words = re.findall(r"[a-z0-9]+", f"{row.title} {row.notes}".lower())
    haystack = " ".join(_stem(w) for w in words)
    for a, b in zip(stems, stems[1:], strict=False):
        if f"{a} {b}" in haystack:
            score += 5
    return score


def get_official_link(
    args: GetOfficialLinkInput, registry_path: Path | None = None
) -> GetOfficialLinkOutput:
    """Look up portal/office links in data/sources/registry.csv.

    Reads the CSV directly (not the database), so links work on a fresh clone before
    anything has been ingested.
    """
    tokens = tokenize(args.topic)
    if not tokens:
        return GetOfficialLinkOutput()
    try:
        rows = [r for r in load_registry(registry_path) if r.handling != "blocked"]
    except (OSError, ValueError, csv.Error):  # missing or malformed registry: no links
        return GetOfficialLinkOutput()
    scored = [(_link_score(tokens, r), r) for r in rows]
    # Best score first; tier 1 before tier 2 on ties.
    scored = sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], x[1].authority_tier))
    links = [
        OfficialLink(
            source_id=r.id,
            title=r.title,
            issuer=r.issuer,
            url=r.url,
            category=r.category,
            notes=r.notes or "",
        )
        for _, r in scored[:3]
    ]
    return GetOfficialLinkOutput(links=links)


# ---------- registry views ----------


def list_sources(db_path: Path | None = None) -> list[SourcePublic]:
    conn = _open_existing(db_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """SELECT s.*, COUNT(DISTINCT d.id) AS n_docs, COUNT(c.id) AS n_chunks
                FROM sources s
                LEFT JOIN documents d ON d.source_id = s.id AND d.status='indexed'
                  AND d.id = (SELECT MAX(id) FROM documents
                    WHERE source_id=d.source_id AND url=d.url AND status='indexed')
                LEFT JOIN chunks c ON c.document_id = d.id
                GROUP BY s.id ORDER BY s.rowid"""
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [
        SourcePublic(
            id=r["id"],
            title=r["title"],
            issuer=r["issuer"],
            category=r["category"],
            url=r["url"],
            authority_tier=r["authority_tier"],
            audience=r["audience"],
            handling=r["handling"],
            status=r["status"] or "not_fetched",
            last_checked_at=r["last_checked_at"],
            documents=r["n_docs"],
            chunks=r["n_chunks"],
        )
        for r in rows
    ]


def count_indexed_sources(db_path: Path | None = None) -> int:
    """Number of enabled sources that have at least one indexed document."""
    conn = _open_existing(db_path)
    if conn is None:
        return 0
    try:
        return conn.execute(
            "SELECT COUNT(DISTINCT s.id) FROM sources s JOIN documents d ON d.source_id = s.id "
            "WHERE s.handling='ingest' AND d.status='indexed'"
        ).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
