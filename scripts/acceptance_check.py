"""Live acceptance check: ask the running API every question in data/eval/questions.jsonl.

Usage (from the repo root, with the API running):
    apps/api/.venv/bin/python scripts/acceptance_check.py [--api URL] [--limit N]

Questions are sent one at a time (the GPU is shared). For each one we record whether the
behaviour matched, whether an expected source was cited, time to first token, total latency
and any error code. Results go to data/eval/results-<date>.json (gitignored) and a markdown
summary is printed. It talks to the network, so no pytest test imports it.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data" / "eval" / "questions.jsonl"
REGISTRY = ROOT / "data" / "sources" / "registry.csv"
DB = ROOT / "data" / "campuspilot.db"


def load_questions(limit: int | None) -> list[dict]:
    lines = [ln for ln in QUESTIONS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    questions = [json.loads(ln) for ln in lines]
    return questions[:limit] if limit else questions


class SourceMapper:
    """Turns a cited URL into a registry id (via indexed documents, else the registry URL)."""

    def __init__(self) -> None:
        self.doc_urls: dict[str, str] = {}
        if DB.exists():
            with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
                self.doc_urls = dict(conn.execute("SELECT url, source_id FROM documents"))
        with REGISTRY.open(encoding="utf-8", newline="") as f:
            self.registry_urls = {row["url"]: row["id"] for row in csv.DictReader(f)}

    def source_id(self, url: str) -> str | None:
        if url in self.doc_urls:
            return self.doc_urls[url]
        for registry_url, source_id in self.registry_urls.items():
            if url.rstrip("/") == registry_url.rstrip("/"):
                return source_id
        return None


def read_sse(response: httpx.Response, started: float):
    """Yield (event_name, data, seconds_since_start) for each server-sent event."""
    name = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name:
            yield name, json.loads(line.removeprefix("data: ")), time.monotonic() - started
            name = None


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """Send one question and collect what the stream said."""
    out: dict = {"sources": [], "done": None, "error": None, "ttft_s": None}
    started = time.monotonic()
    try:
        with client.stream("POST", f"{api}/v1/chat", json={"message": question}) as response:
            if response.status_code != 200:
                out["error"] = f"HTTP_{response.status_code}"
                return out
            for name, data, elapsed in read_sse(response, started):
                if name == "token" and out["ttft_s"] is None:
                    out["ttft_s"] = elapsed
                elif name == "sources":
                    out["sources"] = data
                elif name == "done":
                    out["done"] = data
                elif name == "error":
                    out["error"] = data.get("code", "UNKNOWN")
    except httpx.HTTPError as exc:
        out["error"] = type(exc).__name__
    out["total_s"] = time.monotonic() - started
    return out


def judge(item: dict, run: dict, mapper: SourceMapper) -> dict:
    """Compare one run with what the question expected."""
    done = run["done"] or {}
    kind = done.get("answer_kind")
    if item["expect"] == "moodle":
        behaviour_ok = any(
            s.get("kind") == "moodle" and (s.get("due_at") or s.get("course"))
            for s in run["sources"]
        )
    else:
        behaviour_ok = kind == item["expect"]
    by_id = {s["id"]: s for s in run["sources"]}
    cited = [by_id[c]["url"] for c in done.get("citations", []) if c in by_id]
    cited_registry_ids = sorted({sid for u in cited if (sid := mapper.source_id(u))})
    expected = item.get("expected_source_ids", [])
    source_ok = bool(set(expected) & set(cited_registry_ids)) if expected else None
    return {
        "id": item["id"],
        "question": item["question"],
        "expect": item["expect"],
        "answer_kind": kind,
        "behaviour_ok": behaviour_ok,
        "expected_source_ids": expected,
        "cited_source_ids": cited_registry_ids,
        "source_cited": source_ok,
        "ttft_s": run["ttft_s"],
        "total_s": run.get("total_s"),
        "error": run["error"],
    }


def percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def summarise(rows: list[dict]) -> dict:
    with_sources = [r for r in rows if r["source_cited"] is not None]
    ttfts = [r["ttft_s"] for r in rows if r["ttft_s"] is not None]
    totals = [r["total_s"] for r in rows if r["total_s"] is not None]
    return {
        "questions": len(rows),
        "behaviour_match_pct": 100 * sum(r["behaviour_ok"] for r in rows) / max(len(rows), 1),
        "source_cited_pct": (
            100 * sum(r["source_cited"] for r in with_sources) / len(with_sources)
            if with_sources
            else None
        ),
        "errors": sum(1 for r in rows if r["error"]),
        "ttft_median_s": statistics.median(ttfts) if ttfts else None,
        "ttft_p90_s": percentile(ttfts, 90),
        "latency_median_s": statistics.median(totals) if totals else None,
        "latency_p90_s": percentile(totals, 90),
    }


def print_report(rows: list[dict], totals: dict) -> None:
    print("| id | expect | got | behaviour | source cited | TTFT s | total s | error |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        cited = "n/a" if r["source_cited"] is None else ("yes" if r["source_cited"] else "NO")
        print(
            f"| {r['id']} | {r['expect']} | {r['answer_kind'] or '-'} "
            f"| {'ok' if r['behaviour_ok'] else 'MISS'} | {cited} "
            f"| {fmt(r['ttft_s'])} | {fmt(r['total_s'])} | {r['error'] or ''} |"
        )
    source_pct = totals["source_cited_pct"]
    print(f"\n**Questions:** {totals['questions']}  **Errors:** {totals['errors']}")
    print(f"**Behaviour match:** {totals['behaviour_match_pct']:.0f}%")
    print(f"**Source cited:** {'n/a' if source_pct is None else f'{source_pct:.0f}%'}")
    print(f"**TTFT (s):** median {fmt(totals['ttft_median_s'])}, p90 {fmt(totals['ttft_p90_s'])}")
    print(
        f"**Latency (s):** median {fmt(totals['latency_median_s'])}, "
        f"p90 {fmt(totals['latency_p90_s'])}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--limit", type=int, default=None, help="only the first N questions")
    args = parser.parse_args()
    api = args.api.rstrip("/")

    questions = load_questions(args.limit)
    mapper = SourceMapper()
    rows = []
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=5.0)) as client:
        try:
            client.get(f"{api}/health").raise_for_status()
        except httpx.HTTPError:
            print(f"The API is not reachable at {api}. Start it first.", file=sys.stderr)
            return 1
        for item in questions:
            print(f"asking {item['id']}...", file=sys.stderr)
            rows.append(judge(item, ask(client, api, item["question"]), mapper))

    totals = summarise(rows)
    out_path = ROOT / "data" / "eval" / f"results-{date.today().isoformat()}.json"
    out_path.write_text(
        json.dumps({"api": api, "totals": totals, "results": rows}, indent=2), encoding="utf-8"
    )
    print_report(rows, totals)
    print(f"\nSaved {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
