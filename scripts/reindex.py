"""Rebuild chunks and the FTS index from the saved files in data/raw/."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from campuspilot.ingestion import db  # noqa: E402
from campuspilot.ingestion.pipeline import reindex  # noqa: E402


def main() -> int:
    conn = db.connect(create=True)
    documents, chunks = reindex(conn)
    conn.close()
    print(f"Reindexed {documents} documents into {chunks} chunks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
