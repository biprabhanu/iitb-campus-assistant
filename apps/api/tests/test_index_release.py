"""Index release download, verification, fallback, and the release_index script (offline)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
import respx

from campuspilot import config
from campuspilot.index_release import prepare_index
from campuspilot.ingestion import db
from tests.data_helpers import add_html, add_source, fixture_text, make_source

API = "https://api.github.com/repos/o/r/releases?per_page=20"
DB_URL = "https://github.com/o/r/releases/download/index-2026-01-04/campuspilot.db"
SUMS_URL = "https://github.com/o/r/releases/download/index-2026-01-04/SHA256SUMS"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_db_bytes(path: Path) -> bytes:
    conn = db.connect(path, create=True)
    conn.execute("INSERT INTO sources (id, title) VALUES ('SRC-REL', 'from release')")
    conn.commit()
    conn.close()
    return path.read_bytes()


def releases(tag="index-2026-01-04", draft=False):
    return [
        {
            "tag_name": tag,
            "draft": draft,
            "published_at": "2026-01-04T00:00:00Z",
            "assets": [
                {"name": "campuspilot.db", "browser_download_url": DB_URL},
                {"name": "SHA256SUMS", "browser_download_url": SUMS_URL},
            ],
        }
    ]


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_SOURCE", "release")
    monkeypatch.setenv("INDEX_REPO", "o/r")
    config.get_settings.cache_clear()
    return config.get_settings()


@pytest.fixture
def release_db(tmp_path) -> bytes:
    return make_db_bytes(tmp_path / "src" / "campuspilot.db")


def has_source(path: Path, source_id: str) -> bool:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone() is not None
    finally:
        conn.close()


@respx.mock
def test_release_happy_path(settings, release_db):
    respx.get(API).respond(200, json=releases())
    respx.get(SUMS_URL).respond(200, text=f"{sha(release_db)}  campuspilot.db\n")
    respx.get(DB_URL).respond(200, content=release_db)
    info = prepare_index(settings)
    assert (info.kind, info.version) == ("release", "index-2026-01-04")
    assert info.db_path == settings.campuspilot_db_path
    assert has_source(info.db_path, "SRC-REL")
    assert not list(info.db_path.parent.glob(".index-*"))


@respx.mock
def test_bad_checksum_falls_back(settings, release_db):
    respx.get(API).respond(200, json=releases())
    respx.get(SUMS_URL).respond(200, text=f"{'0' * 64}  campuspilot.db\n")
    respx.get(DB_URL).respond(200, content=release_db)
    info = prepare_index(settings)
    assert (info.kind, info.version) == ("fallback", "fixtures")
    assert has_source(info.db_path, "SRC-DEMO-CAL")
    assert not has_source(info.db_path, "SRC-REL")
    assert not list(info.db_path.parent.glob(".index-*"))


@respx.mock
def test_redirect_to_foreign_host_refused(settings, release_db):
    respx.get(API).respond(200, json=releases())
    respx.get(SUMS_URL).respond(200, text=f"{sha(release_db)}  campuspilot.db\n")
    respx.get(DB_URL).respond(302, headers={"location": "https://evil.example/campuspilot.db"})
    evil = respx.get("https://evil.example/campuspilot.db").respond(200, content=release_db)
    info = prepare_index(settings)
    assert info.kind == "fallback"
    assert not evil.called


@respx.mock
def test_redirect_to_allowed_host_followed(settings, release_db):
    respx.get(API).respond(200, json=releases())
    respx.get(SUMS_URL).respond(200, text=f"{sha(release_db)}  campuspilot.db\n")
    cdn = "https://objects.githubusercontent.com/abc"
    respx.get(DB_URL).respond(302, headers={"location": cdn})
    respx.get(cdn).respond(200, content=release_db)
    assert prepare_index(settings).kind == "release"


@respx.mock
def test_no_matching_release_falls_back(settings):
    respx.get(API).respond(200, json=releases(tag="v1.0") + releases(draft=True))
    info = prepare_index(settings)
    assert (info.kind, info.version) == ("fallback", "fixtures")


@respx.mock
def test_network_error_falls_back(settings):
    respx.get(API).mock(side_effect=httpx.ConnectError("down"))
    assert prepare_index(settings).kind == "fallback"


def test_local_kind_and_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_SOURCE", "local")
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert prepare_index(s).kind == "missing"
    make_db_bytes(s.campuspilot_db_path)
    info = prepare_index(s)
    assert (info.kind, info.version) == ("local", None)


# ---------- scripts/release_index.py ----------


def load_script():
    path = Path(__file__).resolve().parents[3] / "scripts" / "release_index.py"
    spec = importlib.util.spec_from_file_location("release_index_script", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_index(tmp_path: Path, pages: int) -> Path:
    path = tmp_path / "idx.db"
    conn = db.connect(path, create=True)
    src = make_source()
    add_source(conn, src)
    for i in range(pages):
        add_html(conn, src, f"https://example.test/p{i}", fixture_text("calendar.html"), tmp_path)
    conn.close()
    return path


def test_release_script_writes_manifest_and_sums(tmp_path, capsys):
    script = load_script()
    path = build_index(tmp_path, pages=1)
    conn = sqlite3.connect(path)
    # Pad the chunk count so the 100-chunk floor is met without needing a huge fixture.
    conn.execute(
        "INSERT INTO chunks (document_id, text) SELECT 1, 'x' FROM "
        "(WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<150) "
        "SELECT i FROM n)"
    )
    conn.commit()
    conn.close()
    out = tmp_path / "out"
    assert script.main(["--db", str(path), "--out", str(out)]) == 0
    tag = capsys.readouterr().out.strip()
    assert tag.startswith("index-") and len(tag) == len("index-2026-01-04")
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["tag"] == tag and manifest["totals"]["chunks"] >= 100
    doc = manifest["sources"][0]["documents"][0]
    assert doc["url"] == "https://example.test/p0" and len(doc["sha256"]) == 64
    sums = dict(line.split("  ")[::-1] for line in (out / "SHA256SUMS").read_text().splitlines())
    assert sums["campuspilot.db"] == sha((out / "campuspilot.db").read_bytes())
    assert sums["manifest.json"] == sha((out / "manifest.json").read_bytes())


def test_release_script_refuses_small_index(tmp_path):
    script = load_script()
    path = build_index(tmp_path, pages=1)
    out = tmp_path / "out"
    assert script.main(["--db", str(path), "--out", str(out)]) == 1
    assert not (out / "SHA256SUMS").exists()


@respx.mock
def test_pinned_tag_skips_github_api(settings, release_db, monkeypatch):
    """With INDEX_TAG set, the API is never called (Render's shared IPs get 403 there)."""
    monkeypatch.setenv("INDEX_TAG", "index-2026-01-04")
    config.get_settings.cache_clear()
    pinned = config.get_settings()
    api_route = respx.get(API).respond(403)
    respx.get(SUMS_URL).respond(200, text=f"{sha(release_db)}  campuspilot.db\n")
    respx.get(DB_URL).respond(200, content=release_db)
    info = prepare_index(pinned)
    assert (info.kind, info.version) == ("release", "index-2026-01-04")
    assert not api_route.called
    assert has_source(info.db_path, "SRC-REL")


@respx.mock
def test_api_403_without_pinned_tag_falls_back(settings):
    respx.get(API).respond(403)
    assert prepare_index(settings).kind == "fallback"
