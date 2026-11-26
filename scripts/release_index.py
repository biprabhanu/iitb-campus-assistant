#!/usr/bin/env python3
"""Write manifest.json and SHA256SUMS for an index DB, ready to attach to a GitHub Release.

Usage: python scripts/release_index.py [--db PATH] [--out DIR]
Prints the release tag (index-YYYY-MM-DD, UTC). Exits 1 if the index has fewer than 100 chunks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

MIN_CHUNKS = 100


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_manifest(db_path: Path, tag: str, now: datetime) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sources = []
        n_docs = 0
        for s in conn.execute("SELECT id, url, handling FROM sources ORDER BY id"):
            docs = [
                {"url": d["url"], "fetched_at": d["fetched_at"], "sha256": d["content_hash"]}
                for d in conn.execute(
                    "SELECT url, fetched_at, content_hash FROM documents"
                    " WHERE source_id = ? AND status = 'indexed' ORDER BY url",
                    (s["id"],),
                )
            ]
            if not docs:
                continue
            n_docs += len(docs)
            sources.append(
                {"id": s["id"], "url": s["url"], "handling": s["handling"], "documents": docs}
            )
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        conn.close()
    return {
        "version": tag,
        "tag": tag,
        "created_at": now.isoformat(timespec="seconds"),
        "sources": sources,
        "totals": {"sources": len(sources), "documents": n_docs, "chunks": chunks},
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=root / "data" / "campuspilot.db")
    parser.add_argument("--out", type=Path, default=root / "dist" / "index")
    args = parser.parse_args(argv)

    if not args.db.is_file():
        print(f"error: database not found: {args.db}", file=sys.stderr)
        return 1
    now = datetime.now(UTC)
    tag = f"index-{now:%Y-%m-%d}"
    manifest = build_manifest(args.db, tag, now)
    chunks = manifest["totals"]["chunks"]
    if chunks < MIN_CHUNKS:
        print(f"error: only {chunks} chunks indexed (need {MIN_CHUNKS}); refusing", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    out_db = args.out / "campuspilot.db"
    if args.db.resolve() != out_db.resolve():
        shutil.copyfile(args.db, out_db)
    manifest_path = args.out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    sums = "".join(f"{sha256_file(p)}  {p.name}\n" for p in (out_db, manifest_path))
    (args.out / "SHA256SUMS").write_text(sums, encoding="utf-8")
    print(
        f"{manifest['totals']['documents']} documents, {chunks} chunks -> {args.out}",
        file=sys.stderr,
    )
    print(tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
