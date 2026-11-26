"""Ingest approved sources: python scripts/ingest.py --source ID | --all-approved [--dry-run]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from campuspilot.ingestion import db  # noqa: E402
from campuspilot.ingestion.demo import remove_demo_sources  # noqa: E402
from campuspilot.ingestion.fetcher import Fetcher  # noqa: E402
from campuspilot.ingestion.pipeline import ingest_source  # noqa: E402
from campuspilot.ingestion.registry import load_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", help="one source id, e.g. SRC-ACAD-CAL")
    group.add_argument("--all-approved", action="store_true", help="every registry row")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, fetch nothing")
    args = parser.parse_args()

    rows = load_registry()
    if args.source:
        rows = [r for r in rows if r.id == args.source]
        if not rows:
            print(f"Unknown source id: {args.source}")
            return 1

    if args.dry_run:
        for r in rows:
            action = {"ingest": "fetch page + linked PDFs", "link_only": "HEAD only"}.get(
                r.handling, "skip"
            )
            print(f"{r.id:22} {r.handling:12} {action}  {r.url}")
        return 0

    conn = db.connect(create=True)
    if removed := remove_demo_sources(conn):  # left over from `make mock-dev`
        print(f"Removed {removed} demo source(s) built by mock-dev.")
    for r in load_registry():  # the whole registry is always loaded into `sources`
        db.upsert_source(conn, r.model_dump())
    conn.commit()

    fetcher = Fetcher()
    registry_urls = {r.url for r in load_registry()}  # a PDF with its own row is fetched there
    for r in rows:
        report = ingest_source(conn, r, fetcher, skip_urls=frozenset(registry_urls - {r.url}))
        conn.commit()
        print(
            f"{r.id:22} {r.handling:11} http={report.http_status} via={report.fetched_via} "
            f"docs={report.documents} chunks={report.chunks} failed={report.failed} "
            f"unchanged={report.unchanged} title={report.title_seen!r} {'; '.join(report.notes)}"
        )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
