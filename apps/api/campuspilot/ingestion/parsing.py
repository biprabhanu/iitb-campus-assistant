"""Turn raw HTML / PDF bytes into sections of text that keep headings and pages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote, urldefrag, urljoin, urlparse

import pymupdf
from bs4 import BeautifulSoup, Tag

from campuspilot.ingestion.dates import extract_published_at


@dataclass
class Section:
    heading_path: str
    text: str
    page: int | None = None


@dataclass
class ParsedDoc:
    title: str
    sections: list[Section] = field(default_factory=list)
    published_at: str | None = None
    parser: str = ""
    pdf_links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, link text)

    @property
    def full_text(self) -> str:
        return "\n".join(s.text for s in self.sections)


_DROP_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"]
_HEADINGS = ["h1", "h2", "h3", "h4"]
_BLOCKS = _HEADINGS + ["p", "li", "tr", "pre", "blockquote", "dt", "dd"]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _page_title(soup: BeautifulSoup) -> str:
    raw = soup.title.get_text() if soup.title else ""
    # "Calendar and Timetable | Academic Office" -> "Calendar and Timetable"
    return _clean(raw.split("|")[0]) if raw else ""


def _main_node(soup: BeautifulSoup) -> Tag:
    for finder in (lambda: soup.find("main"), lambda: soup.find("article"), lambda: soup.body):
        node = finder()
        if isinstance(node, Tag):
            return node
    return soup  # type: ignore[return-value]


def _row_text(tr: Tag) -> str:
    cells = [_clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
    return " | ".join(c for c in cells if c)


def collect_pdf_links(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """PDF links on the same host as the page, in page order, without duplicates."""
    host = urlparse(base_url).netloc
    seen: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        url = quote(urldefrag(urljoin(base_url, str(a["href"])))[0], safe=":/?&=%#~+@,;")
        parsed = urlparse(url)
        if parsed.netloc == host and parsed.path.lower().endswith(".pdf") and url not in seen:
            seen[url] = _clean(a.get_text(" "))
    return list(seen.items())


def _faq_sections(soup: BeautifulSoup, title: str) -> list[Section]:
    """Some pages keep their FAQ answers only in JSON-LD (schema.org FAQPage)."""
    sections: list[Section] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        for item in data.get("mainEntity", []) if isinstance(data, dict) else []:
            question = _clean(str(item.get("name", "")))
            answer = _clean(str((item.get("acceptedAnswer") or {}).get("text", "")))
            if question and answer:
                sections.append(Section(f"{title} > {question}", answer))
    return sections


def parse_html(html: bytes | str, url: str = "") -> ParsedDoc:
    """Keep the heading structure: each section has the path of headings above it."""
    soup = BeautifulSoup(html, "html.parser")
    title = _page_title(soup)
    pdf_links = collect_pdf_links(soup, url) if url else []
    faq_sections = _faq_sections(soup, title)
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    root = _main_node(soup)

    sections: list[Section] = []
    stack: list[tuple[int, str]] = []  # (heading level, heading text)
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            path = " > ".join(h for _, h in stack) or title
            sections.append(Section(heading_path=path, text=text))
        buffer.clear()

    for el in root.find_all(_BLOCKS):
        if el.find_parent(["li", "tr", "p", "pre", "blockquote", "dt", "dd"]):
            continue  # already covered by its parent block
        text = _row_text(el) if el.name == "tr" else _clean(el.get_text(" "))
        if not text:
            continue
        if el.name in _HEADINGS:
            flush()
            level = int(el.name[1])
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
        else:
            buffer.append(text)
    flush()
    sections.extend(faq_sections)

    doc = ParsedDoc(title=title, sections=sections, parser="bs4", pdf_links=pdf_links)
    doc.published_at = extract_published_at(doc.full_text, title)
    return doc


def parse_pdf(data: bytes, fallback_title: str = "") -> ParsedDoc:
    """One section per page (PyMuPDF). Pages with no text are skipped."""
    sections: list[Section] = []
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        meta_title = _clean((pdf.metadata or {}).get("title") or "")
        # Link text that is just a URL is not a title.
        hint = "" if fallback_title.startswith("http") else fallback_title
        title = hint or meta_title
        for number, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            if text:
                sections.append(Section(heading_path=title, text=text, page=number))
    doc = ParsedDoc(title=title, sections=sections, parser="pymupdf")
    doc.published_at = extract_published_at(doc.full_text, title)
    return doc
