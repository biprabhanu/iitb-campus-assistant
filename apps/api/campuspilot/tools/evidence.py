"""Evidence blocks: how tool results are shown to the model (CONTRACT §5).

Each piece of evidence gets a stable id per turn: S1.. for documents, M1.. for Moodle.
The text inside a block is *data*; the system prompt tells the model to ignore any
instructions found there.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    chunk_ids: list[int] = field(default_factory=list)  # every chunk merged into this item

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
        """Give ids to new items and return what the model should see for this tool call.

        Documents get ONE id per URL, so several chunks of the same page share an id
        (the UI shows one card per document, and the model cites one id per document).
        A later chunk of an already-seen document is merged into it, and the returned
        copy carries only the new text, so the model never sees the same text twice.
        """
        result: list[Evidence] = []
        for item in new_items:
            if item.key[0] == "chunk":
                item.chunk_ids = [item.key[1]]
            existing = self._find_existing(item)
            if existing is None:
                prefix = "S" if item.kind == "doc" else "M"
                count = sum(1 for e in self.items if e.id.startswith(prefix))
                item.id = f"{prefix}{count + 1}"
                self._remember(item)
                self.items.append(item)
                result.append(item)
                continue
            if item.key in self._by_key:  # the exact same chunk/link again: nothing new
                if existing not in result:
                    result.append(existing)
                continue
            self._merge(existing, item)
            self._remember(item, existing)
            # One block per id per tool call: fold into a block already returned this call.
            same_call = next((r for r in result if r.id == existing.id), None)
            if same_call is None:
                result.append(replace(item, id=existing.id))
            elif same_call is not existing:  # `existing` already holds the merged text
                same_call.text = f"{same_call.text}\n...\n{item.text}"
        return result

    def _find_existing(self, item: Evidence) -> Evidence | None:
        found = self._by_key.get(item.key)
        if found is None and item.kind == "doc" and item.url:
            found = self._by_key.get(("url", item.url))
        return found

    def _remember(self, item: Evidence, target: Evidence | None = None) -> None:
        target = target or item
        self._by_key[item.key] = target
        if item.kind == "doc" and item.url:
            self._by_key.setdefault(("url", item.url), target)

    @staticmethod
    def _merge(existing: Evidence, item: Evidence) -> None:
        existing.text = f"{existing.text}\n...\n{item.text}"
        existing.chunk_ids.extend(i for i in item.chunk_ids if i not in existing.chunk_ids)
        if item.locator and item.locator != existing.locator:
            existing.locator = ", ".join(x for x in (existing.locator, item.locator) if x)
        # A real document chunk is a better title/metadata source than a registry link.
        if existing.key[0] == "link" and item.key[0] == "chunk":
            for name in ("title", "checked_at", "published", "tier", "audience"):
                setattr(existing, name, getattr(item, name) or getattr(existing, name))

    def ids(self) -> set[str]:
        return {e.id for e in self.items}

    def get(self, evidence_id: str) -> Evidence | None:
        return next((e for e in self.items if e.id == evidence_id), None)

    def sources(self) -> list[SourceItem]:
        return [e.to_source() for e in self.items]

    def chunk_ids(self) -> list[int]:
        return [chunk_id for e in self.items for chunk_id in e.chunk_ids]


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
