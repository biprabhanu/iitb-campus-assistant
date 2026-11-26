"""Per-IP abuse limits (in memory) and the client-IP rule (CONTRACT §10.3)."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque

from starlette.requests import Request

DAY_S = 86400.0
PRUNE_AT = 5000  # forget idle clients once this many are tracked


class RateLimiter:
    """Sliding windows: at most `per_min` hits per minute and `per_day` per day, per key."""

    def __init__(self, per_min: int, per_day: int) -> None:
        self.per_min = per_min
        self.per_day = per_day
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> int | None:
        """Record a hit. Returns None if allowed, else the seconds to wait before retrying."""
        now = time.monotonic()
        if len(self._hits) > PRUNE_AT:
            self._prune(now)
        hits = self._hits[key]
        while hits and now - hits[0] > DAY_S:
            hits.popleft()
        if len(hits) >= self.per_day:
            return math.ceil(DAY_S - (now - hits[0]))
        recent = [t for t in hits if now - t <= 60.0]
        if len(recent) >= self.per_min:
            return math.ceil(60.0 - (now - recent[0]))
        hits.append(now)
        return None

    def _prune(self, now: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] > DAY_S]:
            del self._hits[key]


def client_ip(request: Request, hosted: bool) -> str:
    """Who is calling? Hosted: Cloudflare's header, else the LAST X-Forwarded-For entry
    (the leftmost one is client-controlled). Local: the socket peer."""
    if hosted:
        cloudflare = request.headers.get("cf-connecting-ip", "").strip()
        if cloudflare:
            return cloudflare
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"
