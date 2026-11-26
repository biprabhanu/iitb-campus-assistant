"""Evidence blocks: how tool results are shown to the model (CONTRACT §5).

Each piece of evidence gets a stable id per turn: S1.. for documents, M1.. for Moodle.
The text inside a block is *data*; the system prompt tells the model to ignore any
instructions found there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Any

from campuspilot.schemas.chat import SourceItem
from campuspilot.schemas.tools import (
    GetCourseContentsOutput,
    GetMyDeadlinesOutput,
    GetOfficialLinkOutput,
    ListMyCoursesOutput,
    SearchCampusDocsOutput,
)


@dataclass
class Evidence:
    """One citable item before it has an id."""

    key: tuple  # identity inside a turn, e.g. ("chunk", 42); same key -> same id
    kind: str  # "doc" or "moodle"
    title: str
    issuer: str
    url: str
    text: str
    locator: str | None = None
    checked_at: str | None = None
    published: str | None = None
    tier: int | None = None
    audience: str | None = None
    course: str | None = None
    due_at: str | None = None
    activity_url: str | None = None
    demo: bool = False
    id: str = ""

    def to_block(self) -> str:
        attrs: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "issuer": self.issuer,
            "tier": self.tier,
            "audience": self.audience,
            "published": self.published,
            "course": self.course,
            "due": self.due_at,
            "demo": "true" if self.demo else None,
            "url": self.url,
        }
        attr_text = " ".join(f'{k}="{escape(str(v), quote=True)}"' for k, v in attrs.items() if v)
        # Stop retrieved text from closing the block early and posing as instructions.
        safe_text = self.text.replace("</evidence", "<\\/evidence")
        return f"<evidence {attr_text}>\n{safe_text}\n</evidence>"

    def to_source(self) -> SourceItem:
        snippet = " ".join(self.text.split())
        return SourceItem(
            id=self.id,
            title=self.title,
            issuer=self.issuer,
            url=self.url,
            locator=self.locator,
            checked_at=self.checked_at,
            kind=self.kind,  # type: ignore[arg-type]
            snippet=snippet[:240] or None,
            course=self.course,
            due_at=self.due_at,
            activity_url=self.activity_url,
            demo=self.demo,
        )


@dataclass
class EvidenceStore:
    """All evidence collected during one chat turn."""

    items: list[Evidence] = field(default_factory=list)
    _by_key: dict[tuple, Evidence] = field(default_factory=dict)

    def add(self, new_items: list[Evidence]) -> list[Evidence]:
        """Give ids to new items (re-using ids for repeats) and return them in order."""
        result: list[Evidence] = []
        for item in new_items:
            existing = self._by_key.get(item.key)
            if existing is None:
                prefix = "S" if item.kind == "doc" else "M"
                count = sum(1 for e in self.items if e.id.startswith(prefix))
                item.id = f"{prefix}{count + 1}"
                self._by_key[item.key] = item
                self.items.append(item)
                existing = item
            result.append(existing)
        return result

    def ids(self) -> set[str]:
        return {e.id for e in self.items}

    def get(self, evidence_id: str) -> Evidence | None:
        return next((e for e in self.items if e.id == evidence_id), None)

    def sources(self) -> list[SourceItem]:
        return [e.to_source() for e in self.items]

    def chunk_ids(self) -> list[int]:
        return [e.key[1] for e in self.items if e.key[0] == "chunk"]


# ---------- converters: tool output -> evidence (+ an optional note) ----------

ToolEvidence = tuple[list[Evidence], str]


def from_search(output: SearchCampusDocsOutput) -> ToolEvidence:
    items = [
        Evidence(
            key=("chunk", hit.chunk_id),
            kind="doc",
            title=hit.title,
            issuer=hit.issuer,
            url=hit.url,
            text=hit.text,
            locator=f"p. {hit.page}" if hit.page else (hit.heading_path or None),
            checked_at=hit.checked_at,
            published=hit.published_at,
            tier=hit.authority_tier,
            audience=hit.audience,
        )
        for hit in output.hits
    ]
    return items, ""


def from_links(output: GetOfficialLinkOutput) -> ToolEvidence:
    items = [
        Evidence(
            key=("link", link.source_id),
            kind="doc",
            title=link.title,
            issuer=link.issuer,
            url=link.url,
            text=link.notes or f"Official page: {link.title}",
        )
        for link in output.links
    ]
    return items, ""


def from_deadlines(output: GetMyDeadlinesOutput) -> ToolEvidence:
    items = [
        Evidence(
            key=("deadline", d.id),
            kind="moodle",
            title=d.title,
            issuer="Moodle",
            url=d.activity_url or "",
            text=f"{d.title} ({d.course}) is due {d.due_at.isoformat()}",
            course=d.course,
            due_at=d.due_at.isoformat(),
            activity_url=d.activity_url,
            demo=output.demo,
        )
        for d in output.deadlines
    ]
    return items, output.note


def from_courses(output: ListMyCoursesOutput) -> ToolEvidence:
    items = [
        Evidence(
            key=("course", c.id),
            kind="moodle",
            title=c.full_name,
            issuer="Moodle",
            url=c.url,
            text=f"Course {c.short_name}: {c.full_name}",
            course=c.short_name,
            demo=output.demo,
        )
        for c in output.courses
    ]
    return items, output.note


def from_contents(output: GetCourseContentsOutput) -> ToolEvidence:
    if output.course is None:
        return [], output.note
    lines = [
        f"{section.name}: " + ", ".join(f"{r.name} ({r.type})" for r in section.resources)
        for section in output.sections
        if section.resources
    ]
    item = Evidence(
        key=("contents", output.course.id),
        kind="moodle",
        title=f"{output.course.short_name} course contents",
        issuer="Moodle",
        url=output.course.url,
        text="\n".join(lines) or "No resources listed.",
        course=output.course.short_name,
        demo=output.demo,
    )
    return [item], output.note
