"""A polite fetcher: robots.txt, one request per 2 s per host, clear User-Agent.

If the Mac cannot reach a page (some IITB pages load only on campus), `fetch_via_passpoli`
retries the same URL from the IEOR server with curl. It never prompts for anything.
"""

from __future__ import annotations

import http.client
import shlex
import subprocess  # noqa: S404 - used only for ssh/curl to our own server
import time
import urllib.error
import urllib.request
import urllib.robotparser
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urlparse

USER_AGENT = "CampusPilot-student-prototype (IE624 course project)"
MIN_INTERVAL_S = 2.0
TIMEOUT_S = 30
MAX_BYTES = 30 * 1024 * 1024
REMOTE_DIR = "/scratch/$USER/campuspilot"


@dataclass
class FetchResult:
    url: str
    status: int  # HTTP status, 0 if the request failed
    content: bytes = b""
    content_type: str = ""
    final_url: str = ""
    via: str = "mac"
    error: str = ""  # "robots", "network: ..." or ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error and bool(self.content)


class Fetcher:
    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # ---------- politeness ----------

    def _wait_turn(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = MIN_INTERVAL_S - (time.monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = time.monotonic()

    def _open(self, url: str, method: str = "GET") -> FetchResult:
        """One rate-limited request. Errors become a FetchResult, not an exception."""
        self._wait_turn(urlparse(url).netloc)
        url = quote(url, safe=":/?&=%#~+@,;")  # file names on IITB sites may contain spaces
        req = urllib.request.Request(  # noqa: S310 - http(s) only, checked by caller
            url, method=method, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310
                body = resp.read(MAX_BYTES) if method == "GET" else b""
                return FetchResult(
                    url, resp.status, body, resp.headers.get("Content-Type", ""), resp.geturl()
                )
        except urllib.error.HTTPError as e:
            return FetchResult(url, e.code, error=f"http {e.code}", final_url=url)
        except (urllib.error.URLError, http.client.HTTPException, ValueError, OSError) as e:
            return FetchResult(url, 0, error=f"network: {e}", final_url=url)

    def robots_allowed(self, url: str) -> bool:
        """robots.txt per host, cached. A missing robots.txt (404) allows everything."""
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._robots:
            res = self._open(f"{host}/robots.txt")
            parser: urllib.robotparser.RobotFileParser | None = None
            if res.status == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(res.content.decode("utf-8", errors="replace").splitlines())
            elif res.status in (401, 403):
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(["User-agent: *", "Disallow: /"])
            self._robots[host] = parser  # None = no usable robots.txt = allowed
        parser = self._robots[host]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    # ---------- public API ----------

    def get(self, url: str) -> FetchResult:
        if urlparse(url).scheme not in ("http", "https"):
            return FetchResult(url, 0, error="network: unsupported scheme")
        if not self.robots_allowed(url):
            return FetchResult(url, 0, error="robots", final_url=url)
        return self._open(url)

    def head(self, url: str) -> FetchResult:
        """Reachability check only (used for link_only rows). No body is read."""
        if urlparse(url).scheme not in ("http", "https"):
            return FetchResult(url, 0, error="network: unsupported scheme")
        return self._open(url, method="HEAD")


def fetch_via_passpoli(url: str) -> FetchResult:
    """Fetch `url` with curl on Passpoli, copy the bytes back, delete the remote file."""
    name = f"f_{uuid.uuid4().hex[:10]}"
    remote_file = f"{REMOTE_DIR}/{name}"
    fetch_cmd = (
        f"mkdir -p {REMOTE_DIR} && nice -n 10 curl -sL -m 60 --max-filesize 50000000 "
        f"-A {shlex.quote(USER_AGENT)} -o {remote_file} "
        f"-w '%{{http_code}} %{{content_type}}' {shlex.quote(url)}"
    )
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "passpoli"]
    try:
        info = subprocess.run(  # noqa: S603
            [*ssh, fetch_cmd], capture_output=True, text=True, timeout=120, check=False
        )
        if info.returncode != 0:
            return FetchResult(url, 0, error="passpoli: ssh or curl failed", via="passpoli")
        code_text, _, ctype = info.stdout.strip().partition(" ")
        body = subprocess.run(  # noqa: S603
            [*ssh, f"cat {remote_file}"], capture_output=True, timeout=120, check=False
        ).stdout
        status = int(code_text) if code_text.isdigit() else 0
        return FetchResult(url, status, body, ctype, url, via="passpoli")
    except (subprocess.TimeoutExpired, OSError):
        return FetchResult(url, 0, error="passpoli: timeout", via="passpoli")
    finally:
        subprocess.run(  # noqa: S603
            [*ssh, f"rm -f {remote_file}"], capture_output=True, timeout=60, check=False
        )
