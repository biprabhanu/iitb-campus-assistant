"""Build a small demo index from data/fixtures/docs/ (used by `make mock-dev`).

python scripts/build_demo_index.py [--if-missing]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from campuspilot.config import get_settings  # noqa: E402
from campuspilot.ingestion import db  # noqa: E402
from campuspilot.ingestion.demo import build_demo_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--if-missing", action="store_true", help="do nothing if the database already exists"
    )
    args = parser.parse_args()

    settings = get_settings()
    path = db.resolve_db_path()
    if args.if_missing and path.exists():
        print("An index already exists; keeping it (delete it to rebuild the demo index).")
        return 0
    conn = db.connect(create=True)
    documents, chunks = build_demo_index(conn, settings.campuspilot_raw_dir)
    conn.close()
    print(
        f"Built a demo index: {documents} sample document(s), {chunks} chunks. "
        "Run `make ingest` for the real IITB pages."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
