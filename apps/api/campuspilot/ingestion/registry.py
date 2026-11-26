"""Load data/sources/registry.csv (the only copy of the source registry)."""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel

from campuspilot.config import get_settings


class SourceRow(BaseModel):
    id: str
    title: str
    issuer: str
    category: str
    url: str
    authority_tier: int
    audience: str | None = "all"
    handling: str
    notes: str = ""


def load_registry(path: Path | None = None) -> list[SourceRow]:
    csv_path = path or get_settings().campuspilot_registry_csv
    with open(csv_path, newline="", encoding="utf-8") as f:
        return [SourceRow(**row) for row in csv.DictReader(f)]
