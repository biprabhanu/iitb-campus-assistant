"""Hosted index bootstrap: download the newest `index-*` GitHub Release, verify it, or fall back.

`prepare_index(settings)` is synchronous; the app calls it with `asyncio.to_thread` at startup.
It never raises: any failure logs one line (no secrets, no URLs with tokens) and builds the
fixture demo index instead, so `/v1/status` can report `index: "fallback"`.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx

from campuspilot.config import Settings
from campuspilot.ingestion import db
from campuspilot.ingestion.demo import build_demo_index

log = logging.getLogger("campuspilot.index_release")

ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
MAX_DB_BYTES = 100 * 1024 * 1024
MAX_SUMS_BYTES = 64 * 1024
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
DB_ASSET = "campuspilot.db"
SUMS_ASSET = "SHA256SUMS"

IndexKind = Literal["release", "local", "fallback", "missing"]


@dataclass
class IndexInfo:
    kind: IndexKind
    version: str | None
    db_path: Path


class IndexDownloadError(Exception):
    """A safe-to-log reason the release could not be used."""


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") not in ALLOWED_HOSTS:
        raise IndexDownloadError(f"refused host {parts.hostname or '?'}")


class _Fetcher:
    def __init__(self, client: httpx.Client, deadline: float) -> None:
        self.client = client
        self.deadline = deadline

    def _remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise IndexDownloadError("timed out")
        return left

    def stream_to(self, url: str, sink, max_bytes: int) -> None:
        """GET with manual redirects (each hop validated); write at most max_bytes to `sink`."""
        for _ in range(MAX_REDIRECTS + 1):
            _check_url(url)
            timeout = httpx.Timeout(self._remaining())
            with self.client.stream("GET", url, follow_redirects=False, timeout=timeout) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise IndexDownloadError("redirect without location")
                    url = str(httpx.URL(url).join(location))
                    continue
                if resp.status_code != 200:
                    raise IndexDownloadError(f"http {resp.status_code}")
                total = 0
                for chunk in resp.iter_bytes(65536):
                    self._remaining()
                    total += len(chunk)
                    if total > max_bytes:
                        raise IndexDownloadError("download too large")
                    sink.write(chunk)
                return
        raise IndexDownloadError("too many redirects")

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        import io

        buf = io.BytesIO()
        self.stream_to(url, buf, max_bytes)
        return buf.getvalue()


def _newest_index_release(releases: object, prefix: str) -> dict:
    if not isinstance(releases, list):
        raise IndexDownloadError("unexpected releases response")
    candidates = [
        r
        for r in releases
        if isinstance(r, dict)
        and not r.get("draft")
        and str(r.get("tag_name", "")).startswith(prefix)
    ]
    if not candidates:
        raise IndexDownloadError("no matching release")
    candidates.sort(key=lambda r: str(r.get("published_at") or r.get("created_at") or ""))
    return candidates[-1]


def _asset_url(release: dict, name: str) -> str:
    for asset in release.get("assets") or []:
        if isinstance(asset, dict) and asset.get("name") == name:
            url = asset.get("browser_download_url")
            if isinstance(url, str):
                return url
    raise IndexDownloadError(f"release has no {name}")


def _expected_sha(sums_text: str, name: str) -> str:
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            digest = parts[0].lower()
            if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                return digest
    raise IndexDownloadError(f"no checksum for {name}")


def _download_release(settings: Settings) -> str:
    """Download and verify the newest release into settings.campuspilot_db_path; returns its tag."""
    import json

    target = settings.campuspilot_db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + settings.index_download_timeout_s
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "campuspilot-index/1"}
    with httpx.Client(headers=headers) as client:
        fetcher = _Fetcher(client, deadline)
        if settings.index_tag:
            # Pinned tag: build the download links directly and skip api.github.com.
            tag = settings.index_tag
            base = f"https://github.com/{settings.index_repo}/releases/download/{tag}"
            sums_url = f"{base}/{SUMS_ASSET}"
            db_url = f"{base}/{DB_ASSET}"
        else:
            api = f"https://api.github.com/repos/{settings.index_repo}/releases?per_page=20"
            try:
                releases = json.loads(fetcher.get_bytes(api, MAX_JSON_BYTES))
            except ValueError as exc:
                raise IndexDownloadError("bad releases json") from exc
            release = _newest_index_release(releases, settings.index_tag_prefix)
            tag = str(release["tag_name"])
            sums_url = _asset_url(release, SUMS_ASSET)
            db_url = _asset_url(release, DB_ASSET)
        sums = fetcher.get_bytes(sums_url, MAX_SUMS_BYTES)
        expected = _expected_sha(sums.decode("utf-8", "replace"), DB_ASSET)

        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".index-", suffix=".part")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fetcher.stream_to(db_url, fh, MAX_DB_BYTES)
            digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
            if digest != expected:
                raise IndexDownloadError("checksum mismatch")
            _remove_db_files(target)
            os.replace(tmp, target)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
    return tag


def _remove_db_files(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        with contextlib.suppress(FileNotFoundError):
            Path(str(path) + suffix).unlink()


def _build_fallback(settings: Settings) -> None:
    path = settings.campuspilot_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _remove_db_files(path)
    conn = db.connect(path, create=True)
    try:
        build_demo_index(conn, settings.campuspilot_raw_dir)
    finally:
        conn.close()


def prepare_index(settings: Settings) -> IndexInfo:
    path = settings.campuspilot_db_path
    if settings.index_source == "local":
        if path.exists():
            return IndexInfo("local", None, path)
        return IndexInfo("missing", None, path)
    try:
        tag = _download_release(settings)
    except (IndexDownloadError, httpx.HTTPError, OSError) as exc:
        reason = exc if isinstance(exc, IndexDownloadError) else type(exc).__name__
        log.warning("index release unavailable (%s); using the fixture fallback index", reason)
        _build_fallback(settings)
        return IndexInfo("fallback", "fixtures", path)
    log.info("index release %s verified and installed", tag)
    return IndexInfo("release", tag, path)
